import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hifi_agent.benchmarking.models import BenchmarkScenario
from hifi_agent.benchmarking.runner import run_benchmark
from hifi_agent.benchmarking.scenarios import stage13_scenarios
from hifi_agent.parsers.gfa import gfa_segments_to_fasta
from hifi_agent.rules.context import RuleContext

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_RUN = PROJECT_ROOT / "results" / "Candida_albicans_phase6"


def test_stage13_registry_covers_all_required_boundary_categories() -> None:
    scenarios = stage13_scenarios()
    ids = {item.scenario_id for item in scenarios}

    assert len(scenarios) >= 9
    assert {
        "normal_hifi_metrics",
        "low_coverage_downsample",
        "oversized_duplicated_assembly",
        "hom_cov_peak_conflict",
        "inbred_sample",
        "high_n50_structural_error",
        "evaluation_tool_failure",
        "multi_metric_conflict",
        "insufficient_evidence",
    } <= ids
    assert any(item.expected_decision == "BASELINE" for item in scenarios)
    assert any(item.expected_decision == "RETRY" for item in scenarios)
    assert any(item.expected_decision == "STOP" for item in scenarios)


def test_fixture_benchmark_is_repeatable_and_has_no_nonexistent_parameters(
    tmp_path: Path,
) -> None:
    first = run_benchmark(tmp_path / "first", real_run_dir=None, require_real_data=False)
    second = run_benchmark(tmp_path / "second", real_run_dir=None, require_real_data=False)

    assert first.acceptance_passed
    assert first.metrics.pass_rate == 1.0
    assert first.metrics.nonexistent_parameter_rate == 0.0
    assert first.metrics.repeat_consistency_rate == 1.0
    assert first.metrics.correct_stop_rate == 1.0
    assert first.metrics.erroneous_retry_rate == 0.0
    assert [item.model_dump() for item in first.scenarios] == [
        item.model_dump() for item in second.scenarios
    ]


def test_benchmark_writes_machine_and_human_readable_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "benchmark"

    run_benchmark(output, real_run_dir=None, require_real_data=False)

    payload = json.loads((output / "v1_benchmark.json").read_text())
    assert payload["benchmark_version"] == "1.0.0"
    assert (output / "v1_scenarios.tsv").read_text().startswith("scenario_id\t")
    assert (output / "v1_ablation.tsv").read_text().startswith("ablation_id\t")
    assert "Rules + RAG/LLM" in (output / "v1_benchmark.md").read_text()


def test_scenario_schema_rejects_unreviewed_fields() -> None:
    scenario = stage13_scenarios()[0].model_dump()
    scenario["unreviewed_parameter"] = "unsafe"

    with pytest.raises(ValidationError, match="Extra inputs"):
        BenchmarkScenario.model_validate(scenario)


def test_small_gfa_to_fasta_integration(tmp_path: Path) -> None:
    gfa = tmp_path / "tiny.gfa"
    fasta = tmp_path / "tiny.fa"
    gfa.write_text("H\tVN:Z:1.0\nS\tctg1\tACGT\tLN:i:4\nS\tctg2\tTTAA\tLN:i:4\n")

    count = gfa_segments_to_fasta(gfa, fasta)

    assert count == 2
    assert fasta.read_text() == ">ctg1\nACGT\n>ctg2\nTTAA\n"


def test_small_gfa_rejects_missing_sequences(tmp_path: Path) -> None:
    gfa = tmp_path / "bad.gfa"
    gfa.write_text("S\tctg1\t*\tLN:i:4\n")

    with pytest.raises(ValueError, match="Invalid literal GFA"):
        gfa_segments_to_fasta(gfa, tmp_path / "bad.fa")


@pytest.mark.skipif(
    not (REAL_RUN / "04_decisions" / "baseline" / "rag_comparison.json").is_file(),
    reason="retained real Candida acceptance artifacts are not available",
)
def test_real_candida_public_benchmark_passes(tmp_path: Path) -> None:
    report = run_benchmark(tmp_path, real_run_dir=REAL_RUN)

    assert report.acceptance_passed
    real = next(item for item in report.scenarios if item.data_kind == "public_real")
    assert real.scenario_id == "candida_albicans_srr23724250"
    assert real.passed
    assert report.real_data_accessions == ["SRR23724250", "CP128823.1"]
    assert report.metrics.evidence_citation_accuracy == 1.0


def test_rule_context_rejects_wrong_metric_types() -> None:
    with pytest.raises(ValidationError):
        RuleContext.model_validate({"estimated_coverage": "thirty"})
