import json
import os
from pathlib import Path

import pytest

from hifi_agent.schemas.metrics import AssemblyMetrics

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_ACCEPTANCE = os.environ.get("HIFI_AGENT_REAL_ACCEPTANCE") == "1"

pytestmark = pytest.mark.skipif(
    not REAL_ACCEPTANCE,
    reason="set HIFI_AGENT_REAL_ACCEPTANCE=1 to verify retained real-data artifacts",
)


def test_real_hifiasm_bin_reuse_acceptance() -> None:
    root = PROJECT_ROOT / "results" / "Candida_albicans_phase6_bin_reuse"
    reused = root / "02_assembly" / "baseline" / "metadata" / "reused_bins.tsv"
    stderr = root / "02_assembly" / "baseline" / "logs" / "hifiasm.stderr"
    manifest = root / "02_assembly" / "baseline" / "metadata" / "assembly_manifest.json"

    reused_rows = reused.read_text().splitlines()[1:]
    assert sum(row.endswith("\treused") for row in reused_rows) >= 3
    assert "loaded corrected reads and overlaps from disk" in stderr.read_text()
    manifest_data = json.loads(manifest.read_text())
    assert manifest_data["reused_bin_count"] >= 3


def test_real_stage7_metrics_acceptance() -> None:
    metrics_path = (
        PROJECT_ROOT
        / "results"
        / "Candida_albicans_phase6"
        / "03_post_qc"
        / "baseline"
        / "assembly_metrics.json"
    )
    metrics = AssemblyMetrics.model_validate_json(metrics_path.read_text())

    assert metrics.tool_failures == []
    classified_fields = {
        name
        for name in AssemblyMetrics.model_fields
        if name
        not in {
            "schema_version",
            "run_id",
            "tool_failures",
            "metric_limitations",
            "metric_classes",
            "tool_versions",
            "tool_metadata",
            "source_files",
        }
    }
    assert set(metrics.metric_classes) == classified_fields
    assert "MAPPING_FILTERED_HIFI_READS" in metrics.metric_limitations
    assert metrics.mapping_retained_read_count is not None
    busco_metadata = metrics.tool_metadata["busco"]
    assert isinstance(busco_metadata, dict)
    assert busco_metadata["actual_lineage"] == "saccharomycetes_odb12"
    dataset = busco_metadata["dataset"]
    assert isinstance(dataset, dict)
    assert dataset["odb_version"] == 12
