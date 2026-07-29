"""Gated Stage 10/11 acceptance over genuine Candida and Drosophila data."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hifi_agent.benchmarking.v2 import run_v2_benchmark
from hifi_agent.reporting.v2 import render_v2_report
from hifi_agent.reporting.v2_models import V2FinalReport

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN = PROJECT_ROOT / "Data/Candida_albicans/hifiAgent"
STAGE7 = PROJECT_ROOT / "results/v2_stage7_candida"
STAGE89 = PROJECT_ROOT / "results/v2_stage8_stage9_candida"
OUTPUT = PROJECT_ROOT / "results/v2_stage10_stage11_acceptance"


def test_real_stage10_report_and_stage11_two_sample_benchmark() -> None:
    if os.environ.get("HIFI_AGENT_REAL_ACCEPTANCE") != "1":
        pytest.skip("set HIFI_AGENT_REAL_ACCEPTANCE=1 for retained Stage 10/11 acceptance")
    required = [
        RUN / "00_metadata/input_checksums.tsv",
        RUN / "03_post_qc/baseline/assembly_metrics.json",
        STAGE7 / "02_assembly/round_01/candidate_01/attempt_001/stage7_execution.json",
        STAGE7 / "02_assembly/round_01/candidate_01/attempt_002/parameter_lineage.json",
        STAGE89 / "stage8/round_01/round_comparison.json",
        STAGE89 / "stage9/optimization_loop_state.json",
        PROJECT_ROOT / "Data/Drosophila_melanogaster/Drosophila_melanogaster_HiFi.fastq",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    assert not missing, f"retained Stage 10/11 artifact(s) missing: {missing}"
    before = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in required}

    outputs = render_v2_report(
        RUN,
        output_dir=OUTPUT / "report",
        stage7_root=STAGE7,
        comparison_path=STAGE89 / "stage8/round_01/round_comparison.json",
        loop_state_path=STAGE89 / "stage9/optimization_loop_state.json",
        proposal_path=STAGE7 / "stage6_approval/proposal_decision.json",
        llm_receipt_path=PROJECT_ROOT / "benchmark/reports/v2_stage6_live_deepseek_acceptance.json",
        index_path=PROJECT_ROOT / "knowledge/index.json",
    )
    report = V2FinalReport.model_validate_json(outputs.summary_json.read_text())
    live_receipt = json.loads(
        (PROJECT_ROOT / "benchmark/reports/v2_stage6_live_deepseek_acceptance.json").read_text()
    )
    assert live_receipt["provider"] == "deepseek"
    assert live_receipt["llm_status"] == "SUCCESS"
    assert live_receipt["usage"] == {
        "prompt_tokens": 5855,
        "completion_tokens": 2115,
        "total_tokens": 7970,
    }
    assert live_receipt["raw_proposal_count"] == 0
    assert live_receipt["sensitive_payload_checks"] == {
        "fastq_or_reference_sequence_sent": False,
        "absolute_workspace_path_present": False,
        "api_key_present": False,
        "environment_variable_present": False,
    }
    assert report.terminal_outcome == "STOP_PLATEAU"
    assert report.outcome_class == "STOPPED"
    assert report.optimization_succeeded is False
    assert report.optimization_selected_run_id is None
    assert report.final_run_id == "baseline"
    assert report.final_assembly_path == "${RUN_DIR}/02_assembly/baseline/fasta/baseline.primary.fa"
    assert report.llm.provider == "deepseek"
    assert report.llm.model == "deepseek-v4-pro"
    assert report.llm.response_id == "e7377a3b-312e-417a-9f2a-472f77feb665"
    assert report.llm.index_sha256 == (
        "cdd442ce8fa0321e66cea9aa3bc42b79786c16b6ba9a2eddb22830f152c03bbe"
    )
    attempts = {(item.attempt_id, item.status): item for item in report.runs}
    assert ("attempt_001", "FAILED") in attempts
    completed = attempts[("attempt_002", "COMPLETED")]
    assert completed.parameter_contract_status == "PASS"
    assert all(item.argv_matches_realized for item in completed.parameters)
    assert completed.cpu_hours > 0
    assert completed.walltime_hours > 0
    combined = outputs.summary_json.read_text() + outputs.markdown.read_text()
    assert "/data/gw" not in combined
    assert "/home/gw" not in combined

    benchmark = run_v2_benchmark(
        OUTPUT / "benchmark",
        stage10_report_path=outputs.summary_json,
        verify_full_checksums=True,
    )
    assert benchmark.result == "PASS"
    assert all(item.checksum_status == "FULL_PASS" for item in benchmark.dataset_audits)
    drosophila = next(
        item for item in benchmark.dataset_audits if item.sample_id == "Drosophila_melanogaster"
    )
    assert drosophila.accession == "SRR33554835"
    assert drosophila.bytes == 34_915_862_206
    assert drosophila.read_count == 2_430_495
    assert drosophila.total_bases == 17_357_574_041
    assert all(item.passed for item in benchmark.safety_scenarios)
    assert [item.group_id for item in benchmark.ablations] == ["A", "B", "C", "D"]
    assert benchmark.ablations[-1].metrics.llm_call_count == 1
    assert benchmark.ablations[-1].metrics.material_improvement_rate == 0.0
    assert benchmark.ablations[-1].metrics.plateau_stop_accuracy == 1.0

    after = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in required}
    assert after == before
