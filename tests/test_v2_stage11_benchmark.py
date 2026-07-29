"""Portable acceptance tests for the V2 Stage 11 benchmark."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import yaml

from hifi_agent.benchmarking.v2 import run_v2_benchmark
from hifi_agent.reporting.v2_models import (
    V2FinalReport,
    V2LLMRecord,
    V2ParameterLineage,
    V2RunRecord,
)

FIXED_TIME = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _fastq(path: Path, accession: str, sequence: str) -> dict[str, object]:
    path.write_text(
        f"@{accession}.1 1 length={len(sequence)}\n{sequence}\n+\n{'I' * len(sequence)}\n"
    )
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "read_count": 1,
        "total_bases": len(sequence),
    }


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    first = tmp_path / "candida.fastq"
    second = tmp_path / "drosophila.fastq"
    first_stats = _fastq(first, "SRR23724250", "ACGT")
    second_stats = _fastq(second, "SRR33554835", "ACGTACGT")
    manifest = {
        "schema_version": "2.0",
        "samples": [
            {
                "sample_id": "Candida_albicans",
                "species": "Candida albicans",
                "accession": "SRR23724250",
                "fastq": str(first),
                **first_stats,
                "genome_size_class": "small",
                "genome_size_basis": "fixture",
                "role": "full_candidate_and_closed_loop",
            },
            {
                "sample_id": "Drosophila_melanogaster",
                "species": "Drosophila melanogaster",
                "accession": "SRR33554835",
                "fastq": str(second),
                **second_stats,
                "genome_size_class": "medium",
                "genome_size_basis": "fixture",
                "role": "independent_real_input_and_scale_acceptance",
            },
        ],
    }
    manifest_path = tmp_path / "samples.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest))
    report = V2FinalReport(
        generated_at=FIXED_TIME,
        sample_id="Candida_albicans",
        compatibility_mode="V2",
        paths_redacted=True,
        terminal_outcome="STOP_PLATEAU",
        outcome_class="STOPPED",
        optimization_succeeded=False,
        optimization_selected_run_id=None,
        final_run_id=None,
        final_assembly_path=None,
        stop_reason_codes=["NO_METRIC_EXCEEDED_MATERIAL_THRESHOLD"],
        inputs=[],
        pre_qc={},
        baseline_parameters={},
        baseline_metrics={},
        decision_mode="hybrid",
        llm=V2LLMRecord(
            status="SUCCESS",
            provider="deepseek",
            model="deepseek-v4-pro",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            raw_proposal_count=0,
        ),
        approved_candidates=[],
        rejected_proposals=[],
        runs=[
            V2RunRecord(
                run_id="baseline",
                attempt_id="baseline",
                round_index=0,
                kind="baseline",
                status="COMPLETED",
                parameter_contract_status="NOT_APPLICABLE",
                source="baseline",
            ),
            V2RunRecord(
                run_id="candidate_r01_c01",
                attempt_id="attempt_001",
                round_index=1,
                candidate_index=1,
                kind="candidate",
                status="FAILED",
                parameter_contract_status="MISSING",
                cpu_hours=1.0,
                walltime_hours=0.5,
                disk_bytes=100,
                source="failed",
            ),
            V2RunRecord(
                run_id="candidate_r01_c01",
                attempt_id="attempt_002",
                round_index=1,
                candidate_index=1,
                kind="candidate",
                status="COMPLETED",
                parameter_contract_status="PASS",
                parameters=[
                    V2ParameterLineage(
                        parameter="disable_post_join",
                        requested=True,
                        approved=True,
                        rendered=True,
                        realized=True,
                        argv_value=True,
                        contract_status="PASS",
                        argv_matches_realized=True,
                    )
                ],
                cpu_hours=2.0,
                walltime_hours=1.0,
                disk_bytes=200,
                source="completed",
            ),
        ],
        incumbent_timeline=[],
        tools_and_provenance=[],
        limitations=[],
        review_recommendations=[],
        evidence=[],
    )
    report_path = tmp_path / "report.json"
    report_path.write_text(report.model_dump_json())
    return manifest_path, report_path


def test_benchmark_runs_all_safety_cases_and_required_ablation_groups(tmp_path: Path) -> None:
    manifest, stage10 = _inputs(tmp_path)
    report = run_v2_benchmark(
        tmp_path / "output",
        stage10_report_path=stage10,
        sample_manifest_path=manifest,
        verify_full_checksums=True,
        generated_at=FIXED_TIME,
    )

    assert report.result == "PASS"
    assert len(report.safety_scenarios) == 5
    assert all(item.passed for item in report.safety_scenarios)
    assert [item.group_id for item in report.ablations] == ["A", "B", "C", "D"]
    assert [
        (item.rules, item.rag, item.llm_proposals, item.multi_round) for item in report.ablations
    ] == [
        (False, False, False, False),
        (True, False, False, True),
        (True, True, False, True),
        (True, True, True, True),
    ]


def test_benchmark_records_real_costs_llm_usage_and_plateau_truth(tmp_path: Path) -> None:
    manifest, stage10 = _inputs(tmp_path)
    report = run_v2_benchmark(
        tmp_path / "output",
        stage10_report_path=stage10,
        sample_manifest_path=manifest,
        verify_full_checksums=True,
    )
    hybrid = report.ablations[-1].metrics

    assert hybrid.incremental_cpu_hours == 3.0
    assert hybrid.incremental_walltime_hours == 1.5
    assert hybrid.incremental_disk_bytes == 300
    assert hybrid.average_assembly_count == 3.0
    assert hybrid.llm_call_count == 1
    assert hybrid.llm_prompt_tokens == 100
    assert hybrid.llm_completion_tokens == 20
    assert hybrid.material_improvement_rate == 0.0
    assert hybrid.plateau_stop_accuracy == 1.0
    assert report.real_candida_terminal_outcome == "STOP_PLATEAU"


def test_two_distinct_fastqs_are_fully_verified_and_outputs_are_complete(
    tmp_path: Path,
) -> None:
    manifest, stage10 = _inputs(tmp_path)
    output = tmp_path / "output"
    report = run_v2_benchmark(
        output,
        stage10_report_path=stage10,
        sample_manifest_path=manifest,
        verify_full_checksums=True,
    )

    assert {item.accession for item in report.dataset_audits} == {
        "SRR23724250",
        "SRR33554835",
    }
    assert all(item.checksum_status == "FULL_PASS" for item in report.dataset_audits)
    assert all(item.fastq_header_verified for item in report.dataset_audits)
    assert (output / "v2_benchmark.json").is_file()
    assert (output / "v2_ablation.tsv").is_file()
    assert (output / "v2_scenarios.tsv").is_file()
    assert "hybrid V2" in (output / "v2_benchmark.md").read_text()


def test_portable_mode_never_claims_checksum_was_executed(tmp_path: Path) -> None:
    manifest, stage10 = _inputs(tmp_path)

    report = run_v2_benchmark(
        tmp_path / "output",
        stage10_report_path=stage10,
        sample_manifest_path=manifest,
        verify_full_checksums=False,
    )

    assert report.result == "PASS"
    assert all(item.checksum_status == "NOT_RUN" for item in report.dataset_audits)
    assert not any(item.checksum_verified for item in report.dataset_audits)


def test_full_checksum_tamper_fails_acceptance(tmp_path: Path) -> None:
    manifest, stage10 = _inputs(tmp_path)
    payload = yaml.safe_load(manifest.read_text())
    payload["samples"][1]["sha256"] = "0" * 64
    manifest.write_text(yaml.safe_dump(payload))

    report = run_v2_benchmark(
        tmp_path / "output",
        stage10_report_path=stage10,
        sample_manifest_path=manifest,
        verify_full_checksums=True,
    )

    assert report.result == "FAIL"
    assert report.dataset_audits[1].checksum_status == "FAIL"
