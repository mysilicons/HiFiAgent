import json
from pathlib import Path

import pytest
import yaml

import hifi_agent.orchestration.controller as controller_module
from hifi_agent.config import validate_config_file
from hifi_agent.exceptions import AgentStateError, InterruptedExecutionError, ToolExecutionError
from hifi_agent.executors import (
    AssemblyExecutor,
    AssemblyInputManifest,
    AttemptCoordinate,
    InputArtifact,
    NextflowAssemblyRunner,
    WorkflowInvocation,
    WorkflowResult,
)
from hifi_agent.executors.hifiasm_contract import (
    parse_hifiasm_argv,
    parse_hifiasm_parameter_argv,
    render_hifiasm_argv,
    render_hifiasm_parameter_argv,
)
from hifi_agent.executors.models import PostQcContract
from hifi_agent.executors.nextflow import run_pre_qc_workflow
from hifi_agent.orchestration.budget import BudgetLedger, BudgetLimits, BudgetResource
from hifi_agent.orchestration.controller import RunCoordinator
from hifi_agent.orchestration.manifests import ManifestStore, ResourceUsage
from hifi_agent.orchestration.runtime_models import RunPhase
from hifi_agent.orchestration.verifier import require_verification_success, verify_run
from hifi_agent.schemas.assembly import AssemblyConfig, AssemblyParameters
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.schemas.sample import ExecutionBudgetConfig, ResourceConfig, SampleConfig


class FixtureRunner:
    def __init__(self, actions: list[str] | None = None) -> None:
        self.actions = actions or ["success"]
        self.calls: list[WorkflowInvocation] = []

    def run(self, invocation: WorkflowInvocation) -> WorkflowResult:
        self.calls.append(invocation)
        action = self.actions.pop(0)
        if action == "interrupt":
            raise InterruptedExecutionError("host interrupted")
        if action == "fail":
            raise ToolExecutionError("hifiasm exit 2")
        assembly = invocation.attempt_root / "assembly/fasta/primary.fa"
        post_qc = invocation.attempt_root / "post_qc/assembly_metrics.json"
        assembly.parent.mkdir(parents=True, exist_ok=True)
        post_qc.parent.mkdir(parents=True, exist_ok=True)
        assembly.write_text(">contig\nACGT\n")
        post_qc.write_text(
            AssemblyMetrics(
                run_id=invocation.coordinate.logical_run_id,
                assembly_size=4,
                contig_count=1,
                contig_n50=4,
                busco_complete=98.0,
                kmer_completeness=97.0,
            ).model_dump_json(indent=2)
            + "\n"
        )
        realized = list(invocation.rendered_hifiasm_argv)
        if action == "mismatch":
            realized[realized.index("-l") + 1] = "2"
        if action == "invalid_argv":
            realized = ["not-hifiasm", "bad"]
        return WorkflowResult(
            command=("nextflow", "run"),
            realized_hifiasm_argv=tuple(realized),
            artifacts=(assembly, post_qc),
            tool_versions={"hifiasm": "0.25.0"},
            resource_usage=ResourceUsage(cpu_hours=1, walltime_hours=0.5),
        )


def _sample(tmp_path: Path) -> SampleConfig:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    return SampleConfig(
        schema_id="hifi-agent",
        sample_id="sample",
        read_technology="pacbio_hifi",
        hifi_reads=[reads],
        outdir=tmp_path / "run",
        resources=ResourceConfig(max_threads=8, max_memory_gb=16),
        execution_budget=ExecutionBudgetConfig(min_free_disk_gib=0),
    )


def _executor(
    tmp_path: Path,
    runner: FixtureRunner,
) -> tuple[AssemblyExecutor, SampleConfig, BudgetLedger]:
    sample = _sample(tmp_path)
    input_file = tmp_path / "input.json"
    input_file.write_text("{}\n")
    inputs = AssemblyInputManifest(artifacts={"fixture": InputArtifact.from_path(input_file)})
    ledger = BudgetLedger(sample.outdir)
    ledger.initialize(
        BudgetLimits(
            max_total_assemblies=7,
            max_tool_retries=3,
            max_cpu_hours=100,
            max_walltime_hours=100,
            min_free_disk_gib=0,
            max_llm_calls_per_round=1,
            max_total_llm_calls=3,
        )
    )
    manifests = ManifestStore(sample.outdir)
    manifests.initialize_history()
    return (
        AssemblyExecutor(
            sample.outdir,
            sample=sample,
            inputs=inputs,
            environment_manifest_sha256="a" * 64,
            budget=ledger,
            manifests=manifests,
            runner=runner,
        ),
        sample,
        ledger,
    )


def _config(
    sample: SampleConfig,
    parameters: AssemblyParameters | None = None,
) -> AssemblyConfig:
    return AssemblyConfig(
        input_reads=tuple(sample.hifi_reads),
        threads=4,
        parameters=parameters or AssemblyParameters(),
        reason_codes=("TEST",),
    )


def test_baseline_generates_six_piece_round_trip_contract(tmp_path: Path) -> None:
    executor, sample, _ledger = _executor(tmp_path, FixtureRunner())
    approved = _config(sample)
    record = executor.execute(
        coordinate=AttemptCoordinate(round_index=0),
        requested_config=approved.model_dump(mode="json"),
        approved_config=approved,
    )

    assert record is not None
    assert record.comparison_eligible
    contract = sample.outdir / "02_assembly/baseline/attempt_001/contract"
    assert {path.name for path in contract.iterdir()} == {
        "requested_config.json",
        "approved_config.json",
        "rendered_argv.json",
        "hifiasm_command.txt",
        "realized_parameters.json",
        "parameter_contract_check.json",
    }
    assert json.loads((contract / "parameter_contract_check.json").read_text())["status"] == "PASS"
    assert (sample.outdir / "02_assembly/baseline/attempt_001/COMPLETED.json").is_file()


@pytest.mark.parametrize(
    "parameters",
    [
        AssemblyParameters(purge_level=0, purge_similarity=0.0),
        AssemblyParameters(purge_level=3, purge_similarity=1.0, hom_cov=None),
        AssemblyParameters(hom_cov=1, disable_post_join=True),
    ],
)
def test_none_bool_and_boundary_parameters_round_trip(parameters: AssemblyParameters) -> None:
    argv = render_hifiasm_parameter_argv(parameters)
    assert parse_hifiasm_parameter_argv(argv) == parameters
    assert ("--hom-cov" in argv) == (parameters.hom_cov is not None)
    assert ("-u0" in argv) == parameters.disable_post_join


@pytest.mark.parametrize(
    "argv",
    [
        ("--unknown", "1"),
        ("-u0", "true"),
        ("-l", "3", "-l", "2"),
        ("--hom-cov", "$HOME"),
        ("-s", "../../etc/passwd"),
        ("-l", "4"),
        ("-l",),
        ("-l", "not-an-int"),
    ],
)
def test_illegal_parameter_tokens_are_blocked(argv: tuple[str, ...]) -> None:
    with pytest.raises(ToolExecutionError):
        parse_hifiasm_parameter_argv(argv)


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("other", "-o", "out", "-t", "4", "reads.fastq"),
        ("hifiasm", "-o", "out", "-o", "again", "-t", "4", "reads.fastq"),
        ("hifiasm", "-o", "out", "-t", "bad", "reads.fastq"),
        ("hifiasm", "-o", "out", "-t", "4", "--hom-cov"),
        ("hifiasm", "-o", "out", "-t", "4", "--unapproved", "reads.fastq"),
        ("hifiasm", "-o", "out", "-t", "0", "reads.fastq"),
    ],
)
def test_full_hifiasm_argv_parser_fails_closed(argv: tuple[str, ...]) -> None:
    with pytest.raises(ToolExecutionError):
        parse_hifiasm_argv(argv)


def test_hifiasm_renderer_rejects_invalid_runtime_identity(tmp_path: Path) -> None:
    sample = _sample(tmp_path)
    with pytest.raises(ToolExecutionError, match="Invalid hifiasm executable"):
        render_hifiasm_argv(_config(sample), executable="", output_prefix="baseline")


def test_baseline_and_candidate_use_identical_post_qc_contract(tmp_path: Path) -> None:
    runner = FixtureRunner(["success", "success"])
    executor, sample, _ledger = _executor(tmp_path, runner)
    baseline = _config(sample)
    candidate = _config(sample, AssemblyParameters(purge_level=2))
    executor.execute(
        coordinate=AttemptCoordinate(round_index=0),
        requested_config=baseline.model_dump(mode="json"),
        approved_config=baseline,
    )
    executor.execute(
        coordinate=AttemptCoordinate(round_index=1, candidate_index=1),
        requested_config={"purge_level": 2},
        approved_config=candidate,
    )
    baseline_contract = json.loads(
        (
            sample.outdir / "02_assembly/baseline/attempt_001/metadata/post_qc_contract.json"
        ).read_text()
    )
    candidate_contract = json.loads(
        (
            sample.outdir
            / "02_assembly/round_01/candidate_01/attempt_001/metadata/post_qc_contract.json"
        ).read_text()
    )
    assert baseline_contract == candidate_contract
    assert all(call.post_qc_contract.contract_id == "post-qc" for call in runner.calls)


def test_tool_retry_allocates_attempt_002_without_overwrite(tmp_path: Path) -> None:
    runner = FixtureRunner(["fail", "success"])
    executor, sample, ledger = _executor(tmp_path, runner)
    approved = _config(sample, AssemblyParameters(purge_similarity=0.6))
    coordinate = AttemptCoordinate(round_index=1, candidate_index=1)
    failed = executor.execute(
        coordinate=coordinate,
        requested_config={"purge_similarity": 0.6},
        approved_config=approved,
    )
    assert failed is not None
    assert failed.status == "FAILED"
    first = sample.outdir / "02_assembly/round_01/candidate_01/attempt_001"
    assert failed.artifacts_inventory_ref is not None
    assert (first / "partial_artifacts_manifest.json").is_file()
    assert not (first / "COMPLETED.json").exists()
    first_manifest = (first / "attempt_manifest.json").read_bytes()

    completed = executor.execute(
        coordinate=coordinate,
        requested_config={"purge_similarity": 0.6},
        approved_config=approved,
        retry=True,
    )
    assert completed is not None
    assert completed.attempt_index == 2
    assert (first / "attempt_manifest.json").read_bytes() == first_manifest
    assert ledger.snapshot().committed[BudgetResource.ASSEMBLY] == 2
    assert ledger.snapshot().committed[BudgetResource.TOOL_RETRY] == 1


def test_interruption_resumes_same_attempt_and_reuses_budget(tmp_path: Path) -> None:
    runner = FixtureRunner(["interrupt", "success"])
    executor, sample, ledger = _executor(tmp_path, runner)
    approved = _config(sample)
    coordinate = AttemptCoordinate(round_index=0)
    assert (
        executor.execute(
            coordinate=coordinate,
            requested_config=approved.model_dump(mode="json"),
            approved_config=approved,
        )
        is None
    )
    assert ledger.snapshot().reserved[BudgetResource.ASSEMBLY] == 1

    completed = executor.execute(
        coordinate=coordinate,
        requested_config=approved.model_dump(mode="json"),
        approved_config=approved,
        resume=True,
    )
    assert completed is not None
    assert completed.attempt_index == 1
    assert len(runner.calls) == 2
    assert runner.calls[1].resume is True
    assert ledger.snapshot().committed[BudgetResource.ASSEMBLY] == 1


def test_missing_marker_and_inventory_drift_block_comparison(tmp_path: Path) -> None:
    executor, sample, _ledger = _executor(tmp_path, FixtureRunner())
    approved = _config(sample)
    record = executor.execute(
        coordinate=AttemptCoordinate(round_index=0),
        requested_config=approved.model_dump(mode="json"),
        approved_config=approved,
    )
    assert record is not None
    attempt = sample.outdir / "02_assembly/baseline/attempt_001"
    marker = attempt / "COMPLETED.json"
    marker_content = marker.read_text()
    marker.unlink()
    with pytest.raises(AgentStateError, match="completion evidence"):
        executor.verify_completed_attempt(record)
    marker.write_text(marker_content)
    marker.write_text("{corrupt\n")
    with pytest.raises(AgentStateError, match="completion evidence"):
        executor.verify_completed_attempt(record)
    marker.write_text(marker_content)
    inventory = attempt / "artifacts_manifest.json"
    inventory_content = inventory.read_text()
    inventory.write_text(inventory_content[: len(inventory_content) // 2])
    with pytest.raises(AgentStateError, match="completion evidence"):
        executor.verify_completed_attempt(record)
    inventory.write_text(inventory_content)
    (attempt / "post_qc/assembly_metrics.json").write_text('{"schema_id": "hifi-agent"}\n')
    with pytest.raises(AgentStateError, match="inventory drift"):
        executor.verify_completed_attempt(record)
    (attempt / "assembly/fasta/primary.fa").write_text("tampered")
    with pytest.raises(AgentStateError):
        executor.verify_completed_attempt(record)


def test_contract_mismatch_is_retained_but_ineligible(tmp_path: Path) -> None:
    executor, sample, _ledger = _executor(tmp_path, FixtureRunner(["mismatch"]))
    approved = _config(sample)
    record = executor.execute(
        coordinate=AttemptCoordinate(round_index=0),
        requested_config=approved.model_dump(mode="json"),
        approved_config=approved,
    )
    assert record is not None
    assert record.status == "CONTRACT_VIOLATION"
    assert not record.comparison_eligible
    assert not (sample.outdir / "02_assembly/baseline/attempt_001/COMPLETED.json").exists()


def test_invalid_workflow_result_is_finalized_without_leaking_budget(tmp_path: Path) -> None:
    executor, sample, ledger = _executor(tmp_path, FixtureRunner(["invalid_argv"]))
    record = executor.execute(
        coordinate=AttemptCoordinate(round_index=0),
        requested_config={"source": "fixture"},
        approved_config=_config(sample),
    )
    assert record is not None
    assert record.status == "FAILED"
    assert record.ineligible_reason_codes == ["INVALID_WORKFLOW_RESULT"]
    assert ledger.snapshot().reserved[BudgetResource.ASSEMBLY] == 0
    assert (sample.outdir / "02_assembly/baseline/attempt_001/attempt_manifest.json").is_file()


def test_attempt_selection_and_approved_config_guards_fail_closed(tmp_path: Path) -> None:
    executor, sample, _ledger = _executor(tmp_path, FixtureRunner(["success"]))
    coordinate = AttemptCoordinate(round_index=0)
    wrong_reads = tmp_path / "other.fastq"
    wrong_reads.write_text("@r\nA\n+\nI\n")
    with pytest.raises(ToolExecutionError, match="reads differ"):
        executor.execute(
            coordinate=coordinate,
            requested_config={},
            approved_config=AssemblyConfig(
                input_reads=(wrong_reads,),
                threads=1,
                reason_codes=("BAD",),
            ),
        )
    with pytest.raises(ToolExecutionError, match="threads exceed"):
        executor.execute(
            coordinate=coordinate,
            requested_config={},
            approved_config=_config(sample).model_copy(update={"threads": 9}),
        )
    with pytest.raises(AgentStateError, match="mutually exclusive"):
        executor.execute(
            coordinate=coordinate,
            requested_config={},
            approved_config=_config(sample),
            resume=True,
            retry=True,
        )
    with pytest.raises(AgentStateError, match="requires a prior failed"):
        executor.execute(
            coordinate=coordinate,
            requested_config={},
            approved_config=_config(sample),
            retry=True,
        )

    completed = executor.execute(
        coordinate=coordinate,
        requested_config={},
        approved_config=_config(sample),
    )
    assert completed is not None
    with pytest.raises(AgentStateError, match="cannot be resumed"):
        executor.execute(
            coordinate=coordinate,
            requested_config={},
            approved_config=_config(sample),
            resume=True,
        )
    with pytest.raises(AgentStateError, match="use resume or retry"):
        executor.execute(
            coordinate=coordinate,
            requested_config={},
            approved_config=_config(sample),
        )


def test_parallel_candidate_directories_never_overlap(tmp_path: Path) -> None:
    executor, sample, _ledger = _executor(tmp_path, FixtureRunner(["success", "success"]))
    for index, purge in ((1, 2), (2, 1)):
        config = _config(sample, AssemblyParameters(purge_level=purge))
        executor.execute(
            coordinate=AttemptCoordinate(round_index=1, candidate_index=index),
            requested_config={"purge_level": purge},
            approved_config=config,
        )
    root = sample.outdir / "02_assembly/round_01"
    assert (root / "candidate_01/attempt_001/COMPLETED.json").is_file()
    assert (root / "candidate_02/attempt_001/COMPLETED.json").is_file()


def test_nextflow_runner_uses_attempt_local_publish_work_and_cache(tmp_path: Path) -> None:
    sample = _sample(tmp_path)
    fake_nextflow = tmp_path / "nextflow"
    fake_nextflow.write_text("#!/bin/sh\nexit 0\n")
    fake_nextflow.chmod(0o755)
    sample = sample.model_copy(
        update={
            "tools": sample.tools.model_copy(
                update={"executable_overrides": {"nextflow": fake_nextflow}}
            )
        }
    )
    config_path = tmp_path / "sample.yaml"
    config_path.write_text(
        "schema_id: 'hifi-agent'\nsample_id: sample\nread_technology: pacbio_hifi\n"
        f"hifi_reads: ['{sample.hifi_reads[0]}']\noutdir: '{sample.outdir}'\n"
        "execution_budget:\n  min_free_disk_gib: 0\n"
    )
    validation = validate_config_file(config_path)
    reads_manifest = sample.outdir / "00_metadata/hifi_reads.list"
    reads_manifest.write_text(f"{sample.hifi_reads[0]}\n")
    raw = sample.outdir / "01_pre_qc/raw_metrics.json"
    meryl = sample.outdir / "01_pre_qc/kmer/read.meryl/data"
    histogram = sample.outdir / "01_pre_qc/kmer/kmer_histogram.tsv"
    raw.parent.mkdir(parents=True)
    meryl.parent.mkdir(parents=True)
    raw.write_text("{}\n")
    meryl.write_text("db")
    histogram.write_text("1\t1\n")
    inputs = AssemblyInputManifest(
        artifacts={
            role: InputArtifact.from_path(path)
            for role, path in {
                "resolved_config": validation.resolved_config,
                "validation_receipt": validation.validation_receipt,
                "input_checksums": validation.input_checksums,
                "reads_manifest": reads_manifest,
                "raw_metrics": raw,
                "meryl_db": meryl.parent,
                "kmer_histogram": histogram,
            }.items()
        }
    )
    observed: list[str] = []
    observed_cwd: list[Path] = []

    def fake_command(command: list[str], cwd: Path, _env: dict[str, str]) -> None:
        observed.extend(command)
        observed_cwd.append(cwd)
        assembly_root = Path(command[command.index("--assembly_publish_dir") + 1])
        post_root = Path(command[command.index("--post_qc_publish_dir") + 1])
        run_id = command[command.index("--assembly_run_id") + 1]
        command_file = assembly_root / "metadata/hifiasm_command.txt"
        primary = assembly_root / f"fasta/{run_id}.primary.fa"
        metrics = post_root / "assembly_metrics.json"
        command_file.parent.mkdir(parents=True, exist_ok=True)
        primary.parent.mkdir(parents=True, exist_ok=True)
        post_root.mkdir(parents=True, exist_ok=True)
        command_file.write_text(
            f"hifiasm -o sample.{run_id} -t 4 -l 3 -s 0.55 {sample.hifi_reads[0]}\n"
        )
        (assembly_root / "metadata/assembly_manifest.json").write_text(
            json.dumps({"schema_id": "hifi-agent", "cpu_seconds": 3600, "peak_rss_gb": 2})
        )
        primary.write_text(">c\nA\n")
        metrics.write_text(AssemblyMetrics(run_id=run_id).model_dump_json())

    attempt_root = sample.outdir / "02_assembly/baseline/attempt_001"
    invocation = WorkflowInvocation(
        coordinate=AttemptCoordinate(round_index=0),
        attempt_id="baseline.attempt_001",
        attempt_root=attempt_root,
        sample=sample,
        approved_config=_config(sample),
        inputs=inputs,
        post_qc_contract=PostQcContract.from_sample(sample),
        rendered_hifiasm_argv=(
            "hifiasm",
            "-o",
            "sample.baseline",
            "-t",
            "4",
            "-l",
            "3",
            "-s",
            "0.55",
            str(sample.hifi_reads[0]),
        ),
    )
    nextflow_runner = NextflowAssemblyRunner(command_runner=fake_command)
    result = nextflow_runner.run(invocation)
    assert observed[observed.index("-entry") + 1] == "ASSEMBLY_ATTEMPT"
    assert Path(observed[observed.index("-work-dir") + 1]).is_relative_to(attempt_root)
    assert observed_cwd == [attempt_root / "workflow"]
    assert Path(observed[observed.index("--assembly_publish_dir") + 1]) == attempt_root / "assembly"
    assert Path(observed[observed.index("--post_qc_publish_dir") + 1]) == attempt_root / "post_qc"
    assert result.post_qc_contract_id == "post-qc"
    assert result.resource_usage.cpu_hours == 1
    assert result.resource_usage.peak_rss_gib == pytest.approx(1.862645)

    resume_invocation = invocation.model_copy(update={"resume": True})
    with pytest.raises(InterruptedExecutionError, match="cache is missing"):
        nextflow_runner.run(resume_invocation)
    cache = attempt_root / "workflow/.nextflow/cache"
    cache.mkdir(parents=True)
    (cache / "fixture-cache-entry").write_text("cached")
    observed.clear()
    resumed = nextflow_runner.run(resume_invocation)
    assert "-resume" in observed
    assert resumed.realized_hifiasm_argv == result.realized_hifiasm_argv


def test_pre_qc_runner_materializes_and_resumes_from_verified_inventory(
    tmp_path: Path,
) -> None:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    fake_nextflow = tmp_path / "nextflow"
    fake_nextflow.write_text("#!/bin/sh\nexit 0\n")
    fake_nextflow.chmod(0o755)
    config_path = tmp_path / "sample.yaml"
    run_dir = tmp_path / "run"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent",
                "sample_id": "sample",
                "read_technology": "pacbio_hifi",
                "hifi_reads": [str(reads)],
                "outdir": str(run_dir),
                "execution_budget": {"min_free_disk_gib": 0},
                "tools": {"executable_overrides": {"nextflow": str(fake_nextflow)}},
            }
        )
    )
    sample = validate_config_file(config_path).config
    commands: list[list[str]] = []
    command_cwds: list[Path] = []

    def fake_pre_qc(command: list[str], cwd: Path, _env: dict[str, str]) -> None:
        commands.append(command)
        command_cwds.append(cwd)
        raw = run_dir / "01_pre_qc/raw_metrics.json"
        database = run_dir / "01_pre_qc/kmer/read.meryl/data"
        histogram = run_dir / "01_pre_qc/kmer/kmer_histogram.tsv"
        work_file = run_dir / "01_pre_qc/work/ignored.txt"
        for path in (raw, database, histogram, work_file):
            path.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text('{"schema_id":"hifi-agent"}\n')
        database.write_text("database")
        histogram.write_text("1\t1\n")
        work_file.write_text("cache")

    inputs = run_pre_qc_workflow(sample, command_runner=fake_pre_qc)
    assert len(commands) == 1
    command = commands[0]
    assert "--run_assembly" not in command
    assert "--run_post_qc" not in command
    assert Path(command[command.index("-work-dir") + 1]).is_relative_to(run_dir / "01_pre_qc")
    assert command_cwds == [run_dir / "01_pre_qc"]
    assert inputs.require("meryl_db") == run_dir / "01_pre_qc/kmer/read.meryl"
    inventory = json.loads((run_dir / "01_pre_qc/artifacts_manifest.json").read_text())
    assert all("work" not in item["relative_path"] for item in inventory["entries"])

    def should_not_launch(_command: list[str], _cwd: Path, _env: dict[str, str]) -> None:
        raise AssertionError("verified pre-QC resume must not relaunch Nextflow")

    resumed = run_pre_qc_workflow(
        sample,
        resume=True,
        command_runner=should_not_launch,
    )
    assert resumed == inputs

    (run_dir / "01_pre_qc/raw_metrics.json").write_text("tampered\n")
    with pytest.raises(ToolExecutionError, match="inventory drift"):
        run_pre_qc_workflow(sample, resume=True, command_runner=should_not_launch)


def test_public_coordinator_reports_terminal_baseline_evidence_stop_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    run_dir = tmp_path / "run"
    config_path = tmp_path / "sample.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent",
                "sample_id": "sample",
                "read_technology": "pacbio_hifi",
                "hifi_reads": [str(reads)],
                "outdir": str(run_dir),
                "resources": {"max_threads": 4, "max_memory_gb": 16},
                "execution_budget": {"min_free_disk_gib": 0},
            }
        )
    )
    monkeypatch.setattr(
        controller_module,
        "run_environment_preflight",
        lambda _sample: object(),
    )
    monkeypatch.setattr(
        controller_module,
        "require_environment_preflight",
        lambda _manifest: None,
    )

    def materialize(_manifest: object, output: Path) -> Path:
        output.write_text('{"schema_id": "hifi-agent"}\n')
        return output

    monkeypatch.setattr(controller_module, "materialize_environment_manifest", materialize)

    def pre_qc(sample: SampleConfig, *, resume: bool) -> AssemblyInputManifest:
        del resume
        metadata = sample.outdir / "00_metadata"
        reads_manifest = metadata / "hifi_reads.list"
        reads_manifest.write_text(f"{sample.hifi_reads[0]}\n")
        raw = sample.outdir / "01_pre_qc/raw_metrics.json"
        meryl = sample.outdir / "01_pre_qc/kmer/read.meryl"
        histogram = sample.outdir / "01_pre_qc/kmer/kmer_histogram.tsv"
        inventory = sample.outdir / "01_pre_qc/artifacts_manifest.json"
        raw.parent.mkdir(parents=True, exist_ok=True)
        meryl.mkdir(parents=True, exist_ok=True)
        (meryl / "data").write_text("db")
        raw.write_text("{}\n")
        histogram.write_text("1\t1\n")
        inventory.write_text('{"schema_id": "hifi-agent"}\n')
        return AssemblyInputManifest(
            artifacts={
                role: InputArtifact.from_path(path)
                for role, path in {
                    "resolved_config": metadata / "resolved_config.yaml",
                    "validation_receipt": metadata / "validation_receipt.json",
                    "input_checksums": metadata / "input_checksums.tsv",
                    "reads_manifest": reads_manifest,
                    "raw_metrics": raw,
                    "meryl_db": meryl,
                    "kmer_histogram": histogram,
                    "pre_qc_inventory": inventory,
                }.items()
            }
        )

    runner = FixtureRunner(["success"])
    coordinator = RunCoordinator(
        config_path,
        workflow_runner=runner,
        pre_qc_runner=pre_qc,
    )
    result = coordinator.run()
    assert result.state.state == RunPhase.TERMINAL
    assert result.state.terminal_outcome == "STOP_INSUFFICIENT_EVIDENCE"
    assert result.baseline_attempt is not None
    assert result.baseline_attempt.comparison_eligible
    assert result.baseline_attempt.relative_directory() == Path("baseline/attempt_001")
    assert all(path.is_file() for path in result.report_bundle.paths())
    resumed = coordinator.run(resume=True)
    assert resumed.state.state == RunPhase.TERMINAL
    assert resumed.baseline_attempt is not None
    assert resumed.baseline_attempt.attempt_id == result.baseline_attempt.attempt_id
    assert len(runner.calls) == 1
    verification = verify_run(run_dir, deep=True)
    assert verification.status == "PASS"
    require_verification_success(verification)

    primary = run_dir / "02_assembly/baseline/attempt_001/assembly/fasta/primary.fa"
    primary.write_text("tampered\n")
    failed_verification = verify_run(run_dir, deep=True)
    assert failed_verification.status == "FAIL"
    with pytest.raises(AgentStateError, match="DEEP_ARTIFACTS"):
        require_verification_success(failed_verification)
