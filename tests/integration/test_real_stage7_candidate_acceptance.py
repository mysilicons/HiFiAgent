"""Gated acceptance of the retained real Candida Stage 7 execution."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from hifi_agent.config import verify_recorded_input_checksums
from hifi_agent.executors.candidate import (
    ArtifactInventory,
    CacheCompatibilityReceipt,
    CandidateExecutionReceipt,
)
from hifi_agent.orchestration.models import AttemptManifest
from hifi_agent.rag.models import ApprovedCandidate
from hifi_agent.schemas.metrics import AssemblyMetrics

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUN = PROJECT_ROOT / "Data/Candida_albicans/hifiAgent"
DEFAULT_STAGE7_ROOT = PROJECT_ROOT / "results/v2_stage7_candida"
LIVE_DEEPSEEK_RECEIPT = PROJECT_ROOT / "benchmark/reports/v2_stage6_live_deepseek_acceptance.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _attempt(root: Path, attempt_id: str) -> Path:
    return root / f"02_assembly/round_01/candidate_01/{attempt_id}"


def test_real_candida_approved_candidate_and_homologous_post_qc() -> None:
    if os.environ.get("HIFI_AGENT_REAL_ACCEPTANCE") != "1":
        pytest.skip("set HIFI_AGENT_REAL_ACCEPTANCE=1 for retained real-data acceptance")
    root = Path(os.environ.get("HIFI_AGENT_STAGE7_ACCEPTANCE_ROOT", DEFAULT_STAGE7_ROOT))
    failed_dir = _attempt(root, "attempt_001")
    completed_dir = _attempt(root, "attempt_002")
    required = [
        SOURCE_RUN / "00_metadata/input_checksums.tsv",
        LIVE_DEEPSEEK_RECEIPT,
        failed_dir / "stage7_execution.json",
        completed_dir / "stage7_execution.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    assert not missing, f"retained Stage 7 acceptance artifact(s) missing: {missing}"

    # This re-hashes the genuine 9.69 GB HiFi input and reference against validation.
    verify_recorded_input_checksums(SOURCE_RUN / "00_metadata/input_checksums.tsv")

    approval = ApprovedCandidate.model_validate_json(
        (completed_dir / "approved_candidate.json").read_text()
    )
    live_deepseek = json.loads(LIVE_DEEPSEEK_RECEIPT.read_text())
    assert approval.candidate_id == "disable_post_join"
    assert approval.approved_parameters.disable_post_join is True
    assert approval.requested_parameters == approval.approved_parameters
    assert (
        approval.parameter_fingerprint
        == live_deepseek["approved_candidates"][0]["parameter_fingerprint"]
    )

    failed = CandidateExecutionReceipt.model_validate_json(
        (failed_dir / "stage7_execution.json").read_text()
    )
    completed = CandidateExecutionReceipt.model_validate_json(
        (completed_dir / "stage7_execution.json").read_text()
    )
    assert failed.status == "FAILED"
    assert failed.failure_category == "WORKFLOW"
    assert failed.attempt.attempt_id == "attempt_001"
    assert completed.status == "COMPLETED"
    assert completed.attempt.attempt_id == "attempt_002"
    assert completed.attempt.run_id == "candidate_r01_c01"
    assert completed.tool_failures == []
    assert completed.biological_quality_interpretation == "NOT_EVALUATED_IN_STAGE7"

    cache = CacheCompatibilityReceipt.model_validate_json(
        (completed_dir / "cache_compatibility.json").read_text()
    )
    assert cache.status == "PASS"
    assert cache.changed_parameters == ["disable_post_join"]
    assert cache.baseline_hifiasm_version == cache.runtime_hifiasm_version
    assert cache.baseline_hifiasm_version == "0.25.0-r726"
    baseline_bins = SOURCE_RUN / "02_assembly/baseline/bins"
    assert len(cache.bin_sha256) == 3
    for name, expected_sha in cache.bin_sha256.items():
        assert _sha256(baseline_bins / name) == expected_sha

    workflow = completed.workflow_run_dir
    assembly = workflow / "02_assembly/candidate_r01_c01"
    post_qc = workflow / "03_post_qc/candidate_r01_c01"
    lineage = json.loads((completed_dir / "parameter_lineage.json").read_text())
    contract = json.loads((assembly / "metadata/parameter_contract_check.json").read_text())
    binding = json.loads((completed_dir / "attempt_binding.json").read_text())
    homology = json.loads((completed_dir / "post_qc_homology.json").read_text())
    assert lineage["status"] == contract["status"] == "PASS"
    assert lineage["requested_parameters"] == lineage["approved_parameters"]
    assert (
        lineage["rendered_parameters_with_defaults"]
        == (lineage["realized_parameters_with_defaults"])
    )
    assert contract["differences"] == []
    assert binding["status"] == "PASS"
    assert binding["attempt"]["attempt_id"] == "attempt_002"
    assert binding["assembly_run_id"] == binding["post_qc_run_id"] == "candidate_r01_c01"
    assert homology == {
        "schema_version": "2.0",
        "status": "PASS",
        "attempt_id": "attempt_002",
        "baseline_run_id": "baseline",
        "candidate_run_id": "candidate_r01_c01",
        "differences": {},
        "candidate_tool_failures": [],
    }

    command = (assembly / "metadata/hifiasm_command.txt").read_text().split()
    assert command.count("-u0") == 1
    assert "--hom-cov" not in command
    assert command[command.index("-l") + 1] == "3"
    assert command[command.index("-s") + 1] == "0.55"
    reused = (assembly / "metadata/reused_bins.tsv").read_text().splitlines()
    assert len(reused) == 4
    assert all(line.endswith("\treused") for line in reused[1:])

    baseline_manifest = json.loads(
        (SOURCE_RUN / "02_assembly/baseline/metadata/assembly_manifest.json").read_text()
    )
    candidate_manifest = json.loads((assembly / "metadata/assembly_manifest.json").read_text())
    baseline_metrics = AssemblyMetrics.model_validate_json(
        (SOURCE_RUN / "03_post_qc/baseline/assembly_metrics.json").read_text()
    )
    candidate_metrics = AssemblyMetrics.model_validate_json(
        (post_qc / "assembly_metrics.json").read_text()
    )
    assert baseline_manifest["hifiasm_version"] == candidate_manifest["hifiasm_version"]
    assert candidate_manifest["reused_bin_count"] == 3
    assert candidate_manifest["cpu_seconds"] > 0
    assert candidate_manifest["real_time_seconds"] > 0
    assert candidate_manifest["peak_rss_gb"] > 0
    assert baseline_metrics.tool_versions == candidate_metrics.tool_versions
    assert candidate_metrics.tool_failures == []
    assert candidate_metrics.run_id == "candidate_r01_c01"

    inventory = ArtifactInventory.model_validate_json(
        (completed_dir / "artifact_inventory.json").read_text()
    )
    assert inventory.attempt.attempt_id == "attempt_002"
    relative_paths = {str(entry.relative_path) for entry in inventory.entries}
    for required_fragment in (
        "/gfa/",
        "/fasta/",
        "/bins/",
        "/logs/",
        "/quast/",
        "/busco/",
        "/merqury/",
        "/mapping/",
    ):
        assert any(required_fragment in path for path in relative_paths)
    assert any(path.endswith(".version.txt") for path in relative_paths)
    assert "logs/trace.txt" in relative_paths
    assert "logs/report.html" in relative_paths
    assert len(inventory.entries) > 9_000
    for entry in inventory.entries:
        artifact = workflow / entry.relative_path
        assert artifact.stat().st_size == entry.bytes
        assert _sha256(artifact) == entry.sha256

    # Failed attempt artifacts remain checksum-identical after retry attempt_002.
    failed_manifest = AttemptManifest.model_validate_json(
        (failed_dir / "artifact_manifest.json").read_text()
    )
    assert failed_manifest.status == "FAILED"
    failed_inventory = ArtifactInventory.model_validate_json(
        (failed_dir / "artifact_inventory.json").read_text()
    )
    failed_logs = [
        entry for entry in failed_inventory.entries if "/logs/hifiasm." in str(entry.relative_path)
    ]
    assert len(failed_logs) == 3
    for entry in failed_logs:
        artifact = failed.workflow_run_dir / entry.relative_path
        assert artifact.stat().st_size == entry.bytes
        assert _sha256(artifact) == entry.sha256
