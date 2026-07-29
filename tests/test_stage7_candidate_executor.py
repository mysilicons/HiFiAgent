import hashlib
import json
from pathlib import Path

import pytest
import yaml

from hifi_agent.agent.models import AssemblyConfig
from hifi_agent.config import validate_config_file
from hifi_agent.exceptions import AgentStateError, HiFiAgentError, ToolExecutionError
from hifi_agent.executors.candidate import (
    ArtifactInventory,
    CandidateExecutionReceipt,
    CandidateExecutor,
)
from hifi_agent.executors.hifiasm_contract import write_hifiasm_contract_artifacts
from hifi_agent.executors.nextflow import NextflowRunResult
from hifi_agent.rag.models import ApprovedCandidate
from hifi_agent.rules.models import CandidateParameters
from hifi_agent.schemas.metrics import AssemblyMetrics


@pytest.fixture(autouse=True)
def _stable_hifiasm_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hifi_agent.executors.candidate._resolve_hifiasm_version",
        lambda: ("/test/bin/hifiasm", "0.25.0-r726"),
    )


def _fingerprint(parameters: CandidateParameters) -> str:
    payload = json.dumps(
        parameters.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _approved(
    *,
    parameters: CandidateParameters | None = None,
    requires_confirmation: bool = False,
) -> ApprovedCandidate:
    selected = parameters or CandidateParameters(disable_post_join=True)
    return ApprovedCandidate(
        candidate_id="approved_disable_join",
        origin="llm",
        requested_parameters=selected,
        approved_parameters=selected,
        source_ids=["hifiasm_parameters"],
        metric_ids=["quast_misassemblies"],
        reason_codes=["REFERENCE_SUPPORTED_STRUCTURAL_ERRORS"],
        risk_level="medium_high" if requires_confirmation else "medium",
        requires_user_confirmation=requires_confirmation,
        confidence=0.7,
        parameter_fingerprint=_fingerprint(selected),
    )


def _tool_metadata() -> dict[str, object]:
    return {
        "busco": {
            "requested_lineage": "fungi_odb12",
            "actual_lineage": "fungi_odb12",
            "lineage_selection": "explicit",
        },
        "mapping_filter": {
            "min_read_length": 1000,
            "min_mean_qscore": 20.0,
        },
        "merqury": {"kmer_source": "same_data_advisory"},
    }


def _metrics(
    run_id: str,
    *,
    tool_failures: list[str] | None = None,
    version_suffix: str = "",
) -> AssemblyMetrics:
    return AssemblyMetrics(
        run_id=run_id,
        contig_n50=1_000_000,
        quast_misassemblies=10,
        busco_complete=98.0,
        kmer_qv=30.0,
        mapped_read_fraction=0.99,
        tool_failures=tool_failures or [],
        metric_limitations=[
            "MAPPING_FILTERED_HIFI_READS",
            "MERQURY_SAME_HIFI_DATA_NOT_INDEPENDENT",
        ],
        tool_versions={
            "hifiasm": f"0.25.0-r726{version_suffix}",
            "quast": f"QUAST 5.3{version_suffix}",
            "busco": f"BUSCO 6.0{version_suffix}",
            "merqury": f"Merqury 1.3{version_suffix}",
            "minimap2": f"2.30{version_suffix}",
            "samtools": f"1.22{version_suffix}",
            "coverage": f"bedtools 2.31{version_suffix}",
        },
        tool_metadata=_tool_metadata(),
    )


def _source_run(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    reference = tmp_path / "reference.fa"
    reference.write_text(">chr1\nACGT\n")
    run_dir = tmp_path / "source"
    config_path = tmp_path / "sample.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "sample_id": "sample",
                "hifi_reads": [str(reads)],
                "reference_genome": str(reference),
                "outdir": str(run_dir),
                "busco_lineage": "fungi_odb12",
                "resources": {"max_threads": 8, "max_memory_gb": 32},
            }
        )
    )
    validation = validate_config_file(config_path)
    files = {
        "01_pre_qc/raw_metrics.json": "{}\n",
        "01_pre_qc/kmer/kmer_histogram.tsv": "1\t1\n",
        "02_assembly/baseline/metadata/assembly_manifest.json": json.dumps(
            {"run_id": "baseline", "hifiasm_version": "0.25.0-r726"}
        ),
        "03_post_qc/baseline/assembly_metrics.json": _metrics("baseline").model_dump_json(indent=2),
    }
    for relative, content in files.items():
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    meryl = run_dir / "01_pre_qc/kmer/read.meryl"
    meryl.mkdir()
    (meryl / "data").write_text("meryl\n")
    bins = run_dir / "02_assembly/baseline/bins"
    bins.mkdir()
    for name in ("ec.bin", "ovlp.source.bin", "ovlp.reverse.bin"):
        (bins / f"sample.baseline.{name}").write_bytes(name.encode())
    return run_dir, validation.resolved_config


class FakeRunner:
    def __init__(
        self,
        *,
        tool_failures: list[str] | None = None,
        wrong_run_id: bool = False,
        version_suffix: str = "",
        fail: bool = False,
        interrupt: bool = False,
    ) -> None:
        self.tool_failures = tool_failures or []
        self.wrong_run_id = wrong_run_id
        self.version_suffix = version_suffix
        self.fail = fail
        self.interrupt = interrupt
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        run_dir: Path,
        candidate: AssemblyConfig,
        *,
        resume: bool,
        execution_run_dir: Path,
    ) -> NextflowRunResult:
        self.calls.append(
            {
                "run_dir": run_dir,
                "candidate": candidate,
                "resume": resume,
                "execution_run_dir": execution_run_dir,
            }
        )
        partial = execution_run_dir / "logs/partial.log"
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text("partial output is retained\n")
        if self.interrupt:
            raise KeyboardInterrupt
        if self.fail:
            raise ToolExecutionError("Nextflow workflow failed with injected error")
        observed_run_id = "candidate_r03_c02" if self.wrong_run_id else candidate.run_id
        assembly = execution_run_dir / f"02_assembly/{candidate.run_id}"
        post_qc = execution_run_dir / f"03_post_qc/{candidate.run_id}"
        metadata = assembly / "metadata"
        fasta = assembly / "fasta"
        gfa = assembly / "gfa"
        bins = assembly / "bins"
        logs = assembly / "logs"
        for directory in (metadata, fasta, gfa, bins, logs, post_qc):
            directory.mkdir(parents=True, exist_ok=True)
        command = metadata / "hifiasm_command.txt"
        parameters = candidate.parameters
        argv = [
            "hifiasm",
            "-o",
            f"sample.{candidate.run_id}",
            "-t",
            str(candidate.threads),
            "-l",
            str(parameters.purge_level),
            "-s",
            str(parameters.purge_similarity),
        ]
        if parameters.hom_cov is not None:
            argv.extend(["--hom-cov", str(parameters.hom_cov)])
        if parameters.disable_post_join:
            argv.append("-u0")
        argv.append(candidate.input_reads[0].name)
        command.write_text(" ".join(argv) + "\n")
        write_hifiasm_contract_artifacts(candidate, metadata, command_path=command)
        (metadata / "assembly_manifest.json").write_text(
            json.dumps(
                {
                    "run_id": observed_run_id,
                    "hifiasm_version": f"0.25.0-r726{self.version_suffix}",
                    "cpu_seconds": 1.0,
                    "real_time_seconds": 1.0,
                    "peak_rss_gb": 1.0,
                    "reused_bin_count": 3,
                }
            )
        )
        (metadata / "hifiasm.version.txt").write_text("0.25.0-r726\n")
        (fasta / f"{candidate.run_id}.primary.fa").write_text(">ctg\nACGT\n")
        (fasta / f"{candidate.run_id}.hap1.fa").write_text(">hap1\nACGT\n")
        (fasta / f"{candidate.run_id}.hap2.fa").write_text(">hap2\nACGT\n")
        (gfa / f"sample.{candidate.run_id}.bp.p_ctg.gfa").write_text("H\tVN:Z:1.0\n")
        (bins / f"sample.{candidate.run_id}.ec.bin").write_bytes(b"bin")
        (logs / "hifiasm.stdout").write_text("")
        (logs / "hifiasm.stderr").write_text("loaded corrected reads and overlaps from disk\n")
        (logs / "hifiasm.time.txt").write_text("elapsed 1\n")
        (post_qc / "assembly_metrics.json").write_text(
            _metrics(
                observed_run_id,
                tool_failures=self.tool_failures,
                version_suffix=self.version_suffix,
            ).model_dump_json(indent=2)
        )
        for tool in ("quast", "busco", "merqury", "mapping"):
            tool_dir = post_qc / tool
            tool_dir.mkdir()
            (tool_dir / f"{tool}.txt").write_text(f"{tool} retained output\n")
        return NextflowRunResult(
            command=("nextflow", "run", "workflow/main.nf"),
            outdir=execution_run_dir,
            reads_manifest=run_dir / "00_metadata/hifi_reads.list",
        )


def test_approved_candidate_executes_in_immutable_attempt_and_retains_all_outputs(
    tmp_path: Path,
) -> None:
    run_dir, _ = _source_run(tmp_path)
    execution_root = tmp_path / "stage7"
    runner = FakeRunner()
    executor = CandidateExecutor(run_dir, execution_root, runner=runner)

    receipt = executor.execute(
        _approved(),
        round_index=1,
        candidate_index=1,
        threads=4,
    )

    assert receipt.status == "COMPLETED"
    assert receipt.attempt.run_id == "candidate_r01_c01"
    assert receipt.attempt.attempt_id == "attempt_001"
    assert receipt.biological_quality_interpretation == "NOT_EVALUATED_IN_STAGE7"
    assert executor.history.is_complete(receipt.attempt)
    attempt_dir = execution_root / "02_assembly/round_01/candidate_01/attempt_001"
    assert (attempt_dir / "cache_compatibility.json").is_file()
    cache = json.loads((attempt_dir / "cache_compatibility.json").read_text())
    assert cache["baseline_hifiasm_version"] == cache["runtime_hifiasm_version"]
    assert json.loads((attempt_dir / "attempt_binding.json").read_text())["status"] == "PASS"
    assert json.loads((attempt_dir / "post_qc_homology.json").read_text())["status"] == "PASS"
    lineage = json.loads((attempt_dir / "parameter_lineage.json").read_text())
    assert lineage["status"] == "PASS"
    assert lineage["requested_parameters"] == lineage["approved_parameters"]
    assert (
        lineage["rendered_parameters_with_defaults"]
        == (lineage["realized_parameters_with_defaults"])
    )
    inventory = ArtifactInventory.model_validate_json(
        (attempt_dir / "artifact_inventory.json").read_text()
    )
    paths = {str(item.relative_path) for item in inventory.entries}
    assert any("/gfa/" in path for path in paths)
    assert any("/fasta/" in path for path in paths)
    assert any("/bins/" in path for path in paths)
    assert any("/logs/" in path for path in paths)
    assert any("/quast/" in path for path in paths)
    assert any("/busco/" in path for path in paths)
    assert any("/merqury/" in path for path in paths)
    assert any("/mapping/" in path for path in paths)
    contract = json.loads(
        (
            receipt.workflow_run_dir
            / "02_assembly/candidate_r01_c01/metadata/parameter_contract_check.json"
        ).read_text()
    )
    assert contract["status"] == "PASS"
    assert contract["approved_parameters"]["disable_post_join"] is True


def test_workflow_failure_retains_partial_artifacts_and_retry_uses_attempt_002(
    tmp_path: Path,
) -> None:
    run_dir, _ = _source_run(tmp_path)
    execution_root = tmp_path / "stage7"
    executor = CandidateExecutor(run_dir, execution_root, runner=FakeRunner(fail=True))

    with pytest.raises(ToolExecutionError, match="injected"):
        executor.execute(_approved(), round_index=1, candidate_index=1)

    first_dir = execution_root / "02_assembly/round_01/candidate_01/attempt_001"
    failed = CandidateExecutionReceipt.model_validate_json(
        (first_dir / "stage7_execution.json").read_text()
    )
    assert failed.status == "FAILED"
    assert failed.failure_category == "WORKFLOW"
    assert (first_dir / "workflow/logs/partial.log").is_file()
    assert (first_dir / "artifact_inventory.json").is_file()
    executor.runner = FakeRunner()

    recovered = executor.execute(
        _approved(),
        round_index=1,
        candidate_index=1,
        retry=True,
    )

    assert recovered.status == "COMPLETED"
    assert recovered.attempt.attempt_id == "attempt_002"
    assert (first_dir / "workflow/logs/partial.log").read_text() == ("partial output is retained\n")


def test_interrupted_attempt_resumes_same_attempt_and_nextflow_cache(tmp_path: Path) -> None:
    run_dir, _ = _source_run(tmp_path)
    execution_root = tmp_path / "stage7"
    executor = CandidateExecutor(run_dir, execution_root, runner=FakeRunner(interrupt=True))

    with pytest.raises(KeyboardInterrupt):
        executor.execute(_approved(), round_index=2, candidate_index=1)

    resumed_runner = FakeRunner()
    executor.runner = resumed_runner
    resumed = executor.execute(
        _approved(),
        round_index=2,
        candidate_index=1,
        resume=True,
    )

    assert resumed.status == "COMPLETED"
    assert resumed.attempt.attempt_id == "attempt_001"
    assert resumed_runner.calls[0]["resume"] is True


def test_post_qc_tool_failure_is_not_interpreted_as_biological_quality(
    tmp_path: Path,
) -> None:
    run_dir, _ = _source_run(tmp_path)
    executor = CandidateExecutor(
        run_dir,
        tmp_path / "stage7",
        runner=FakeRunner(tool_failures=["BUSCO_FAILED"]),
    )

    receipt = executor.execute(_approved(), round_index=1, candidate_index=1)

    assert receipt.status == "FAILED"
    assert receipt.failure_category == "POST_QC_TOOL_FAILURE"
    assert receipt.tool_failures == ["BUSCO_FAILED"]
    assert receipt.biological_quality_interpretation == "NOT_EVALUATED_IN_STAGE7"
    assert executor.history.load_attempt(receipt.attempt).status == "FAILED"


@pytest.mark.parametrize(
    ("runner", "match"),
    [
        (FakeRunner(wrong_run_id=True), "not bound"),
        (FakeRunner(version_suffix="-drift"), "not homologous"),
    ],
)
def test_attempt_binding_or_tool_version_drift_fails_closed(
    tmp_path: Path,
    runner: FakeRunner,
    match: str,
) -> None:
    run_dir, _ = _source_run(tmp_path)
    executor = CandidateExecutor(run_dir, tmp_path / "stage7", runner=runner)

    with pytest.raises(ToolExecutionError, match=match):
        executor.execute(_approved(), round_index=1, candidate_index=1)

    receipt = CandidateExecutionReceipt.model_validate_json(
        (
            tmp_path / "stage7/02_assembly/round_01/candidate_01/attempt_001/stage7_execution.json"
        ).read_text()
    )
    assert receipt.status == "FAILED"
    assert receipt.failure_category == "HOMOLOGY_MISMATCH"


def test_tampered_input_checksum_and_missing_bins_fail_preflight(tmp_path: Path) -> None:
    run_dir, _ = _source_run(tmp_path)
    reads = tmp_path / "reads.fastq"
    reads.write_text("@changed\nACGT\n+\nIIII\n")
    first = CandidateExecutor(run_dir, tmp_path / "checksum", runner=FakeRunner())

    with pytest.raises(HiFiAgentError, match="Validated input"):
        first.execute(_approved(), round_index=1, candidate_index=1)

    run_dir, _ = _source_run(tmp_path / "second")
    for path in (run_dir / "02_assembly/baseline/bins").glob("*.bin"):
        path.unlink()
    second = CandidateExecutor(run_dir, tmp_path / "bins", runner=FakeRunner())

    with pytest.raises(ToolExecutionError, match="No baseline hifiasm bins"):
        second.execute(_approved(), round_index=1, candidate_index=1)


def test_incompatible_hifiasm_cache_is_rejected_before_runner(tmp_path: Path) -> None:
    run_dir, _ = _source_run(tmp_path)
    runner = FakeRunner()
    executor = CandidateExecutor(
        run_dir,
        tmp_path / "stage7",
        runner=runner,
        hifiasm_version_resolver=lambda: ("/other/hifiasm", "0.24.0-r702"),
    )

    with pytest.raises(ToolExecutionError, match="Incompatible hifiasm cache rejected"):
        executor.execute(_approved(), round_index=1, candidate_index=1)

    assert runner.calls == []
    receipt = CandidateExecutionReceipt.model_validate_json(
        (
            tmp_path / "stage7/02_assembly/round_01/candidate_01/attempt_001/stage7_execution.json"
        ).read_text()
    )
    assert receipt.failure_category == "PREFLIGHT"
    assert "baseline=0.25.0-r726" in (receipt.error or "")
    assert "runtime=0.24.0-r702" in (receipt.error or "")


def test_resource_and_risk_confirmation_are_enforced_before_launch(tmp_path: Path) -> None:
    run_dir, _ = _source_run(tmp_path)
    runner = FakeRunner()
    resource_executor = CandidateExecutor(
        run_dir,
        tmp_path / "resource",
        runner=runner,
    )

    with pytest.raises(ToolExecutionError, match="threads exceed"):
        resource_executor.execute(
            _approved(),
            round_index=1,
            candidate_index=1,
            threads=9,
        )
    assert runner.calls == []

    risk_executor = CandidateExecutor(run_dir, tmp_path / "risk", runner=runner)
    with pytest.raises(ToolExecutionError, match="risk confirmation"):
        risk_executor.execute(
            _approved(requires_confirmation=True),
            round_index=1,
            candidate_index=1,
        )
    confirmed = CandidateExecutor(
        run_dir,
        tmp_path / "confirmed",
        runner=runner,
    ).execute(
        _approved(requires_confirmation=True),
        round_index=3,
        candidate_index=2,
        confirm_medium_high_risk=True,
    )
    assert confirmed.status == "COMPLETED"
    assert confirmed.attempt.run_id == "candidate_r03_c02"


def test_attempt_resume_retry_and_idempotence_remain_bound_to_same_approval(
    tmp_path: Path,
) -> None:
    run_dir, _ = _source_run(tmp_path)
    original = _approved()
    different = _approved(parameters=CandidateParameters(purge_similarity=0.5))

    runner = FakeRunner()
    completed_executor = CandidateExecutor(
        run_dir,
        tmp_path / "completed",
        runner=runner,
    )
    first = completed_executor.execute(original, round_index=1, candidate_index=1)
    repeated = completed_executor.execute(original, round_index=1, candidate_index=1)
    assert repeated == first
    assert len(runner.calls) == 1
    with pytest.raises(AgentStateError, match="different ApprovedCandidate"):
        completed_executor.execute(different, round_index=1, candidate_index=1)

    failed_executor = CandidateExecutor(
        run_dir,
        tmp_path / "failed",
        runner=FakeRunner(fail=True),
    )
    with pytest.raises(ToolExecutionError):
        failed_executor.execute(original, round_index=1, candidate_index=1)
    with pytest.raises(AgentStateError, match="different ApprovedCandidate"):
        failed_executor.execute(
            different,
            round_index=1,
            candidate_index=1,
            retry=True,
        )
    assert not (tmp_path / "failed/02_assembly/round_01/candidate_01/attempt_002").exists()

    fresh_executor = CandidateExecutor(run_dir, tmp_path / "fresh", runner=FakeRunner())
    with pytest.raises(AgentStateError, match="requires an existing failed attempt"):
        fresh_executor.execute(
            original,
            round_index=1,
            candidate_index=1,
            retry=True,
        )
