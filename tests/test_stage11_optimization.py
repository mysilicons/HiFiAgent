import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import hifi_agent.executors.nextflow as nextflow_executor
from hifi_agent.agent.models import AssemblyConfig, AssemblyParameters
from hifi_agent.exceptions import RuleEvaluationError
from hifi_agent.optimization.comparator import CandidateComparator
from hifi_agent.optimization.engine import select_optimization_outcome
from hifi_agent.optimization.models import CandidateAssessment, Stage11SyntheticScenario
from hifi_agent.optimization.synthetic import load_stage11_synthetic_scenario
from hifi_agent.rules.models import RuleDecision
from hifi_agent.schemas.metrics import AssemblyMetrics

FIXED_TIME = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def _config(
    run_id: str,
    *,
    purge_similarity: float = 0.55,
    disable_post_join: bool = False,
) -> AssemblyConfig:
    return AssemblyConfig(
        run_id=run_id,
        input_reads=[Path("reads.fastq.gz")],
        threads=8,
        parameters=AssemblyParameters(
            purge_similarity=purge_similarity,
            disable_post_join=disable_post_join,
        ),
        reason_codes=["TEST_STAGE11"],
        risk_level="medium",
        retry_kind="NONE" if run_id == "baseline" else "PARAMETER_OPTIMIZATION",
        optimization_round=0 if run_id == "baseline" else 1,
    )


def _metrics(run_id: str, **updates: object) -> AssemblyMetrics:
    values: dict[str, object] = {
        "run_id": run_id,
        "assembly_size": 20_000_000,
        "assembly_size_ratio": 1.40,
        "contig_count": 50,
        "contig_n50": 1_000_000,
        "longest_contig": 3_000_000,
        "quast_misassemblies": 20,
        "busco_complete": 98.0,
        "busco_single": 86.0,
        "busco_duplicated": 12.0,
        "busco_fragmented": 0.5,
        "busco_missing": 1.5,
        "kmer_qv": 30.0,
        "kmer_completeness": 95.0,
        "mapped_read_fraction": 0.99,
        "coverage_cv": 0.30,
        "tool_failures": [],
    }
    values.update(updates)
    return AssemblyMetrics.model_validate(values)


def _retry_decision() -> RuleDecision:
    return RuleDecision(
        decision_id="D-STAGE11",
        rule_set_version="test",
        threshold_catalog_version="test",
        decision="RETRY",
        action="PROPOSE_STRONGER_PURGE",
        matched_rule_ids=["ASM_SIZE_TOO_LARGE_AND_DUPLICATED"],
        controlling_rule_ids=["ASM_SIZE_TOO_LARGE_AND_DUPLICATED"],
        reason_codes=["ASSEMBLY_SIZE_EXCESSIVE", "BUSCO_DUPLICATION_HIGH"],
        evidence={"assembly_size_ratio": 1.4, "busco_duplicated": 12.0},
        candidates=[],
        confidence=0.84,
        risk_level="medium_high",
        conflicts=[],
        human_readable_explanation="One bounded retry is justified.",
    )


def test_candidate_is_accepted_only_without_protected_regression() -> None:
    baseline = _metrics("baseline")
    candidate = _metrics(
        "candidate_r01_c01",
        assembly_size=15_200_000,
        assembly_size_ratio=1.05,
        contig_n50=1_200_000,
        quast_misassemblies=15,
        busco_complete=98.5,
        busco_single=96.5,
        busco_duplicated=2.0,
        kmer_qv=31.0,
        kmer_completeness=96.0,
        mapped_read_fraction=0.995,
        coverage_cv=0.20,
    )

    assessment = CandidateComparator().compare(
        _config("baseline"),
        baseline,
        _config("candidate_r01_c01", purge_similarity=0.5),
        candidate,
        metrics_source="candidate.json",
    )

    assert assessment.status == "ACCEPTED"
    assert assessment.hard_regressions == []
    assert "assembly_size_ratio" in assessment.improvements
    assert "contig_n50" in assessment.improvements


def test_n50_gain_never_overrides_core_quality_regression() -> None:
    baseline = _metrics("baseline")
    candidate = _metrics(
        "candidate_r01_c01",
        assembly_size_ratio=1.05,
        contig_n50=2_000_000,
        busco_complete=82.0,
        kmer_qv=12.0,
        kmer_completeness=45.0,
        mapped_read_fraction=0.75,
        coverage_cv=1.2,
        quast_misassemblies=50,
    )

    assessment = CandidateComparator().compare(
        _config("baseline"),
        baseline,
        _config("candidate_r01_c01", purge_similarity=0.5),
        candidate,
        metrics_source="synthetic.json",
        synthetic=True,
    )

    assert assessment.status == "REJECTED_REGRESSION"
    assert "N50_GAIN_CANNOT_OVERRIDE_CORE_QUALITY_REGRESSION" in assessment.conflicts
    assert "BUSCO_COMPLETE_DROP_GT_2PP" in assessment.hard_regressions
    assert "contig_n50" in assessment.improvements


def test_strictly_worse_candidate_is_dominated_by_baseline() -> None:
    baseline = _metrics("baseline")
    candidate = _metrics(
        "candidate_r01_c01",
        assembly_size_ratio=1.5,
        contig_n50=900_000,
        busco_complete=90.0,
        busco_duplicated=15.0,
        kmer_qv=20.0,
        kmer_completeness=85.0,
        mapped_read_fraction=0.90,
        coverage_cv=0.8,
        quast_misassemblies=30,
    )

    assessment = CandidateComparator().compare(
        _config("baseline"),
        baseline,
        _config("candidate_r01_c01", purge_similarity=0.5),
        candidate,
        metrics_source="candidate.json",
    )

    assert assessment.status == "DOMINATED"
    assert assessment.dominated_by == ["baseline"]


def test_retry_limit_stops_safely_when_no_candidate_is_acceptable() -> None:
    baseline = _metrics("baseline")
    candidate_metrics = _metrics("candidate_r01_c01")
    assessment = CandidateComparator().compare(
        _config("baseline"),
        baseline,
        _config("candidate_r01_c01", purge_similarity=0.5),
        candidate_metrics,
        metrics_source="candidate.json",
    )

    result = select_optimization_outcome(
        sample_id="sample",
        run_dir=Path("${RUN_DIR}"),
        baseline_config=_config("baseline"),
        baseline_metrics=baseline,
        baseline_metrics_source="baseline.json",
        decision=_retry_decision(),
        candidates=[assessment],
        optimization_round=1,
        max_retry_rounds=1,
        max_candidates_per_round=2,
        generated_at=FIXED_TIME,
    )

    assert assessment.status == "REJECTED_NO_GAIN"
    assert result.outcome == "STOP_RETRY_LIMIT"
    assert result.selected_run_id is None


def test_relative_improvement_below_absolute_acceptance_floor_is_rejected() -> None:
    baseline = _metrics("baseline", kmer_completeness=60.0)
    candidate = _metrics(
        "candidate_r01_c01",
        assembly_size_ratio=1.05,
        busco_duplicated=2.0,
        kmer_completeness=70.0,
        contig_n50=1_200_000,
    )

    assessment = CandidateComparator().compare(
        _config("baseline"),
        baseline,
        _config("candidate_r01_c01", purge_similarity=0.5),
        candidate,
        metrics_source="candidate.json",
    )

    assert "kmer_completeness" in assessment.improvements
    assert assessment.status == "REJECTED_NO_GAIN"
    assert "KMER_COMPLETENESS_BELOW_90" in assessment.acceptance_failures


def test_missing_core_metric_stops_automatic_selection() -> None:
    baseline = _metrics("baseline", kmer_qv=None)

    result = select_optimization_outcome(
        sample_id="sample",
        run_dir=Path("${RUN_DIR}"),
        baseline_config=_config("baseline"),
        baseline_metrics=baseline,
        baseline_metrics_source="baseline.json",
        decision=_retry_decision(),
        candidates=[],
        optimization_round=1,
        max_retry_rounds=1,
        max_candidates_per_round=2,
        generated_at=FIXED_TIME,
    )

    assert result.outcome == "STOP_INSUFFICIENT_METRICS"


def test_failed_candidate_is_retained_and_stops_as_execution_failure() -> None:
    candidate_config = _config("candidate_r01_c01", purge_similarity=0.5)
    failed = CandidateAssessment(
        run_id=candidate_config.run_id,
        status="FAILED",
        config=candidate_config,
        metrics=None,
        metrics_source="FAILED",
        parameter_differences=[],
        metric_differences=[],
        hard_regressions=["CANDIDATE_EXECUTION_FAILED"],
        tradeoffs=["candidate execution failed"],
    )

    result = select_optimization_outcome(
        sample_id="sample",
        run_dir=Path("${RUN_DIR}"),
        baseline_config=_config("baseline"),
        baseline_metrics=_metrics("baseline"),
        baseline_metrics_source="baseline.json",
        decision=_retry_decision(),
        candidates=[failed],
        optimization_round=1,
        max_retry_rounds=1,
        max_candidates_per_round=2,
        generated_at=FIXED_TIME,
    )

    assert result.outcome == "STOP_EXECUTION_FAILURE"
    assert result.retained_run_ids == ["baseline", "candidate_r01_c01"]


def test_synthetic_scenario_requires_explicit_disclaimer(tmp_path: Path) -> None:
    path = tmp_path / "scenario.json"
    scenario = {
        "scenario_id": "unsafe",
        "generated_at": FIXED_TIME.isoformat(),
        "synthetic": True,
        "disclaimer": "missing mandatory marker",
        "source_sample_id": "Candida_albicans",
        "source_run_dir": "${RUN_DIR}",
        "source_artifacts": {},
        "source_sha256": {},
        "baseline_metrics": _metrics("baseline").model_dump(mode="json"),
        "candidate_metrics": [_metrics("candidate_r01_c01").model_dump(mode="json")],
        "transformations": [],
    }
    path.write_text(json.dumps(scenario))

    with pytest.raises(RuleEvaluationError, match="disclaimer is missing"):
        load_stage11_synthetic_scenario(path)


def test_synthetic_scenario_hard_limits_candidate_count() -> None:
    data = {
        "scenario_id": "too-many",
        "generated_at": FIXED_TIME,
        "disclaimer": "SYNTHETIC_DO_NOT_USE_FOR_SCIENCE",
        "source_sample_id": "Candida_albicans",
        "source_run_dir": Path("${RUN_DIR}"),
        "source_artifacts": {},
        "source_sha256": {},
        "baseline_metrics": _metrics("baseline"),
        "candidate_metrics": [
            _metrics("candidate_r01_c01"),
            _metrics("candidate_r01_c02"),
            _metrics("candidate_r01_c03"),
        ],
        "transformations": [],
    }

    with pytest.raises(ValidationError):
        Stage11SyntheticScenario.model_validate(data)


def test_workflow_declares_generic_candidate_and_identical_post_qc_contract() -> None:
    workflow = (Path(__file__).resolve().parents[1] / "workflow/main.nf").read_text()
    candidate_block = workflow.split("workflow CANDIDATE_ONLY", maxsplit=1)[1].split(
        "workflow {", maxsplit=1
    )[0]

    assert "HIFIASM_BASELINE(assembly_input_ch)" in candidate_block
    for process in (
        "QUAST(quast_ch)",
        "BUSCO_POST_QC(busco_ch)",
        "MERQURY_POST_QC(merqury_ch)",
        "MAPPING_POST_QC(mapping_ch)",
        "ASSEMBLY_METRICS(combined_ch)",
    ):
        assert process in candidate_block
    assert "destination_name=" in workflow
    assert "source_name/${sample_id}.baseline" in workflow
    assert "${PARAMETER_ARGS[@]}" in workflow


def test_real_candidate_executor_builds_whitelisted_same_qc_workflow_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    execution_run = tmp_path / "stage7_attempt/workflow"
    reads = tmp_path / "reads.fastq.gz"
    reads.write_bytes(b"reads")
    config = {
        "sample_id": "sample",
        "hifi_reads": [str(reads)],
        "outdir": str(run_dir),
        "expected_genome_size": 10_000_000,
        "resources": {"max_threads": 8, "max_memory_gb": 32},
    }
    metadata = run_dir / "00_metadata"
    metadata.mkdir(parents=True)
    (metadata / "resolved_config.yaml").write_text(yaml.safe_dump(config))
    (metadata / "validation_receipt.json").write_text("{}\n")
    (metadata / "input_checksums.tsv").write_text("role\tpath\tsha256\tbytes\n")
    (metadata / "hifi_reads.list").write_text(str(reads) + "\n")
    raw = run_dir / "01_pre_qc/raw_metrics.json"
    raw.parent.mkdir(parents=True)
    raw.write_text("{}\n")
    meryl = run_dir / "01_pre_qc/kmer/read.meryl"
    meryl.mkdir(parents=True)
    (run_dir / "01_pre_qc/kmer/kmer_histogram.tsv").write_text("1\t1\n")
    bins = run_dir / "02_assembly/baseline/bins"
    bins.mkdir(parents=True)
    for suffix in ("ec.bin", "ovlp.source.bin", "ovlp.reverse.bin"):
        (bins / f"sample.baseline.{suffix}").write_bytes(suffix.encode())
    candidate = AssemblyConfig(
        run_id="candidate_r01_c01",
        input_reads=[reads],
        threads=8,
        parameters=AssemblyParameters(purge_similarity=0.5),
        reason_codes=["TEST_STAGE11"],
        risk_level="medium",
        retry_kind="PARAMETER_OPTIMIZATION",
        optimization_round=1,
    )
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> None:
        observed["command"] = command
        observed["kwargs"] = kwargs
        assert (
            execution_run / "00_metadata/candidate_r01_c01_parameter_contract/requested_config.json"
        ).is_file()
        assert not (execution_run / "02_assembly/candidate_r01_c01/metadata").exists()
        manifest = execution_run / "02_assembly/candidate_r01_c01/metadata/assembly_manifest.json"
        fasta = execution_run / "02_assembly/candidate_r01_c01/fasta/candidate_r01_c01.primary.fa"
        metrics = execution_run / "03_post_qc/candidate_r01_c01/assembly_metrics.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        fasta.parent.mkdir(parents=True, exist_ok=True)
        metrics.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}\n")
        (manifest.parent / "hifiasm_command.txt").write_text(
            "hifiasm -o sample.candidate_r01_c01 -t 8 -l 3 -s 0.5 reads.fastq.gz\n"
        )
        fasta.write_text(">contig\nACGT\n")
        metrics.write_text(_metrics("candidate_r01_c01").model_dump_json())

    monkeypatch.setattr(nextflow_executor, "_find_nextflow", lambda: "nextflow")
    monkeypatch.setattr(nextflow_executor, "verify_validation_receipt", lambda *args: None)
    monkeypatch.setattr(nextflow_executor, "verify_recorded_input_checksums", lambda *args: None)
    monkeypatch.setattr("hifi_agent.executors.nextflow.subprocess.run", fake_run)

    result = nextflow_executor.run_candidate_workflow(
        run_dir,
        candidate,
        execution_run_dir=execution_run,
    )
    command = observed["command"]

    assert isinstance(command, list)
    assert "CANDIDATE_ONLY" in command
    assert command[command.index("--assembly_run_id") + 1] == "candidate_r01_c01"
    assert command[command.index("--hifiasm_purge_similarity") + 1] == "0.5"
    assert "--hifiasm_hom_cov" not in command
    assert "--reference_genome" not in command
    assert "--busco_lineage" not in command
    assert command[command.index("-work-dir") + 1] == str(
        (execution_run / ".nextflow_work").resolve()
    )
    assert command[command.index("--outdir") + 1] == str(execution_run.resolve())
    assert result.outdir == execution_run.resolve()
    assert not (run_dir / "02_assembly/candidate_r01_c01").exists()
    reuse = execution_run / "00_metadata/candidate_r01_c01_bin_reuse.tsv"
    assert len(reuse.read_text().splitlines()) == 4
    contract = json.loads(
        (
            execution_run / "02_assembly/candidate_r01_c01/metadata/parameter_contract_check.json"
        ).read_text()
    )
    assert contract["status"] == "PASS"
