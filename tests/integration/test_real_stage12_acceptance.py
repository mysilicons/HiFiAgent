import hashlib
import json
import os
from pathlib import Path

import pytest

from hifi_agent.reporting.renderer import render_final_report
from hifi_agent.reporting.synthetic import synthesize_candida_quality_regression

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = PROJECT_ROOT / "results" / "Candida_albicans_phase6"
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


def test_real_candida_stage12_report_is_complete_traceable_and_redacted(
    tmp_path: Path,
) -> None:
    outputs = render_final_report(RUN_DIR, output_dir=tmp_path / "real-report")
    summary_text = outputs.summary_json.read_text()
    summary = json.loads(summary_text)
    markdown = outputs.markdown.read_text()

    assert summary["sample_id"] == "Candida_albicans"
    assert summary["report_status"] == "WARNING"
    assert summary["final_selection"] == "NONE"
    assert summary["paths_redacted"] is True
    assert "/data/gw" not in summary_text
    assert "/data/gw" not in markdown
    assert len(summary["figures"]) == 10
    assert all((outputs.output_dir / figure).is_file() for figure in summary["figures"])
    for section in range(1, 15):
        assert f"## {section}." in markdown
    assert any(
        module["module"] == "stage11_optimization" and module["status"] == "WARNING"
        for module in summary["modules"]
    )
    records = [
        *summary["pre_qc_metrics"].values(),
        *summary["filtering_metrics"].values(),
        *summary["assembly_runs"][0]["metrics"].values(),
    ]
    for record in records:
        assert record["source_file"]
        assert record["json_pointer"].startswith("/")
    assert summary["filtering_metrics"]["filtered_low_quality_read_count"]["value"] == 0


def test_real_candida_derived_anomaly_rejects_n50_only_improvement(
    tmp_path: Path,
) -> None:
    scenario_path = tmp_path / "candida_anomaly.json"
    scenario = synthesize_candida_quality_regression(RUN_DIR, scenario_path)
    outputs = render_final_report(
        RUN_DIR,
        output_dir=tmp_path / "synthetic-report",
        scenario_path=scenario_path,
    )
    summary = json.loads(outputs.summary_json.read_text())
    runs = {run["run_id"]: run for run in summary["assembly_runs"]}
    baseline = runs["baseline"]["metrics"]
    candidate = runs["synthetic_candidate_n50_trap"]["metrics"]

    source_paths = {
        "resolved_config.yaml": RUN_DIR / "00_metadata/resolved_config.yaml",
        "assembly_metrics.json": RUN_DIR / "03_post_qc/baseline/assembly_metrics.json",
        "agent_state.json": RUN_DIR / "05_agent/agent_state.json",
    }
    assert scenario.source_sha256 == {name: _sha256(path) for name, path in source_paths.items()}
    assert candidate["contig_n50"]["value"] > baseline["contig_n50"]["value"]
    assert candidate["busco_complete"]["value"] < baseline["busco_complete"]["value"]
    assert candidate["kmer_qv"]["value"] < baseline["kmer_qv"]["value"]
    assert candidate["kmer_completeness"]["value"] < baseline["kmer_completeness"]["value"]
    assert candidate["mapped_read_fraction"]["value"] < baseline["mapped_read_fraction"]["value"]
    assert candidate["quast_misassemblies"]["value"] > baseline["quast_misassemblies"]["value"]
    assert sum(
        candidate[name]["value"]
        for name in (
            "busco_single",
            "busco_duplicated",
            "busco_fragmented",
            "busco_missing",
        )
    ) == pytest.approx(100.0)
    assert summary["final_selection"] == "NO_AUTOMATIC_SELECTION"
    assert summary["parameter_changes"]
    stage12_changes = [
        change
        for change in summary["parameter_changes"]
        if change["run_id"] == "synthetic_candidate_n50_trap"
    ]
    assert stage12_changes
    for change in stage12_changes:
        assert change["reason_codes"]
        assert change["evidence"]
        assert change["risk_level"]
        assert change["result"] == "REJECTED_SYNTHETIC_QUALITY_REGRESSION"
    scenario_text = scenario_path.read_text()
    assert "SYNTHETIC_DO_NOT_USE_FOR_SCIENCE" in scenario_text
    assert "/data/gw" not in scenario_text
    assert "SYNTHETIC SCENARIO — NOT A SCIENTIFIC RESULT" in outputs.markdown.read_text()
