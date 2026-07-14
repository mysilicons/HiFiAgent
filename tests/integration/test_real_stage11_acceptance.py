import csv
import hashlib
import json
import os
from pathlib import Path

import pytest

from hifi_agent.optimization.runner import run_stage11_optimization
from hifi_agent.optimization.synthetic import synthesize_candida_stage11_scenario
from hifi_agent.reporting.renderer import render_final_report

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = PROJECT_ROOT / "results/Candida_albicans_phase6"
REAL_ACCEPTANCE = os.environ.get("HIFI_AGENT_REAL_ACCEPTANCE") == "1"

pytestmark = pytest.mark.skipif(
    not REAL_ACCEPTANCE,
    reason="set HIFI_AGENT_REAL_ACCEPTANCE=1 to verify retained real-data artifacts",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_real_candida_stage11_generates_one_legal_bounded_candidate(
    tmp_path: Path,
) -> None:
    scenario_path = tmp_path / "stage11_candida.json"
    scenario = synthesize_candida_stage11_scenario(RUN_DIR, scenario_path)
    output = tmp_path / "optimization"
    result = run_stage11_optimization(
        RUN_DIR,
        scenario_path=scenario_path,
        output_dir=output,
    )

    assert result.triggering_decision["decision"] == "RETRY"
    assert result.triggering_decision["action"] == "PROPOSE_STRONGER_PURGE"
    assert result.optimization_round == result.max_retry_rounds == 1
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.run_id == "candidate_r01_c01"
    assert candidate.config.parameters.purge_similarity == 0.5
    assert set(candidate.config.parameters.model_dump()) == {
        "purge_level",
        "purge_similarity",
        "hom_cov",
        "disable_post_join",
    }
    assert candidate.config.retry_kind == "PARAMETER_OPTIMIZATION"
    source_paths = {
        "resolved_config.yaml": RUN_DIR / "00_metadata/resolved_config.yaml",
        "assembly_metrics.json": RUN_DIR / "03_post_qc/baseline/assembly_metrics.json",
        "agent_state.json": RUN_DIR / "05_agent/agent_state.json",
    }
    assert scenario.source_sha256 == {name: _sha256(path) for name, path in source_paths.items()}
    assert (output / "candidate_configs/candidate_r01_c01.json").is_file()
    assert result.retained_run_ids == ["baseline", "candidate_r01_c01"]


def test_real_candida_stage11_rejects_n50_trap_and_outputs_auditable_tables(
    tmp_path: Path,
) -> None:
    scenario_path = tmp_path / "stage11_candida.json"
    synthesize_candida_stage11_scenario(RUN_DIR, scenario_path)
    output = tmp_path / "optimization"
    result = run_stage11_optimization(
        RUN_DIR,
        scenario_path=scenario_path,
        output_dir=output,
    )
    candidate = result.candidates[0]
    differences = {item.metric: item for item in candidate.metric_differences}

    assert differences["contig_n50"].assessment == "IMPROVED"
    for metric in (
        "busco_complete",
        "kmer_qv",
        "kmer_completeness",
        "mapped_read_fraction",
        "coverage_cv",
        "quast_misassemblies",
    ):
        assert differences[metric].assessment == "REGRESSED"
    assert candidate.status == "REJECTED_REGRESSION"
    assert "N50_GAIN_CANNOT_OVERRIDE_CORE_QUALITY_REGRESSION" in candidate.conflicts
    assert result.outcome == "STOP_METRIC_CONFLICT"
    assert result.selected_run_id is None
    assert "limit was reached" not in result.selection_reason

    with (output / "comparison.tsv").open(newline="") as handle:
        comparison = next(csv.DictReader(handle, delimiter="\t"))
    assert comparison["parameter_diff"]
    assert comparison["contig_n50_assessment"] == "IMPROVED"
    assert comparison["busco_complete_assessment"] == "REGRESSED"
    with (output / "parameter_diff.tsv").open(newline="") as handle:
        parameter = next(csv.DictReader(handle, delimiter="\t"))
    assert parameter["parameter"] == "purge_similarity"
    assert parameter["baseline_value"] == "0.55"
    assert parameter["candidate_value"] == "0.5"
    assert parameter["reason_codes"]
    assert parameter["risk_level"] == "medium_high"
    assert parameter["result"] == "REJECTED_REGRESSION"

    tradeoffs = (output / "selection_tradeoffs.md").read_text()
    assert "SYNTHETIC SCENARIO — NOT A SCIENTIFIC RESULT" in tradeoffs
    assert "N50 is never allowed" in tradeoffs
    persisted = (output / "optimization_result.json").read_text()
    assert "/data/gw" not in persisted
    assert "/home/" not in persisted
    assert json.loads(persisted)["outcome"] == "STOP_METRIC_CONFLICT"


def test_real_candida_final_report_separates_real_and_synthetic_baselines(
    tmp_path: Path,
) -> None:
    scenario_path = tmp_path / "stage11_candida.json"
    synthesize_candida_stage11_scenario(RUN_DIR, scenario_path)
    run_stage11_optimization(
        RUN_DIR,
        scenario_path=scenario_path,
        output_dir=RUN_DIR / "05_agent/optimization",
    )
    outputs = render_final_report(RUN_DIR, output_dir=tmp_path / "final-report")
    summary = json.loads(outputs.summary_json.read_text())
    runs = {run["run_id"]: run for run in summary["assembly_runs"]}

    assert runs["baseline"]["kind"] == "baseline"
    assert runs["baseline"]["metrics"]["busco_duplicated"]["value"] == 0.8
    assert runs["stage11_synthetic_baseline"]["kind"] == "synthetic_baseline"
    assert runs["stage11_synthetic_baseline"]["metrics"]["busco_duplicated"]["value"] == 12.0
    assert runs["candidate_r01_c01"]["kind"] == "synthetic_candidate"
    report = outputs.markdown.read_text()
    assert "Stage 11 triggering decision (synthetic scenario)" in report
    assert "Stage 11 outcome: **STOP_METRIC_CONFLICT**" in report
    assert "Selection costs and tradeoffs" in report
