"""Portable acceptance tests for the V2 Stage 10 report."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hifi_agent.reporting.v2 import render_v2_report
from hifi_agent.reporting.v2_models import V2FinalReport
from hifi_agent.schemas.metrics import AssemblyMetrics

FIXED_TIME = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _fixture(tmp_path: Path) -> dict[str, Path]:
    run = tmp_path / "run"
    stage7 = tmp_path / "stage7"
    config = {
        "sample_id": "fixture",
        "hifi_reads": ["/private/reads.fastq"],
        "outdir": str(run),
        "resources": {"max_threads": 8, "max_memory_gb": 32},
    }
    path = run / "00_metadata/resolved_config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(config))
    (run / "00_metadata/input_checksums.tsv").write_text(
        f"role\tpath\tsha256\tbytes\nhifi_reads\t/private/reads.fastq\t{'a' * 64}\t100\n"
    )
    _json(
        run / "01_pre_qc/raw_metrics.json",
        {"sample_id": "fixture", "input_status": "PASS", "read_count": 10},
    )
    metrics = AssemblyMetrics(
        run_id="baseline",
        contig_n50=1_000_000,
        busco_complete=98.0,
        busco_duplicated=1.0,
        kmer_completeness=95.0,
        kmer_qv=30.0,
        mapped_read_fraction=0.99,
        coverage_cv=0.3,
        quast_misassemblies=20,
    )
    _json(
        run / "03_post_qc/baseline/assembly_metrics.json",
        metrics.model_dump(mode="json"),
    )
    command = run / "02_assembly/baseline/metadata/hifiasm_command.txt"
    command.parent.mkdir(parents=True)
    command.write_text("hifiasm -o fixture.baseline -t 8 /private/reads.fastq\n")

    attempts: list[Path] = []
    for attempt_index, status in ((1, "FAILED"), (2, "COMPLETED")):
        attempt = stage7 / f"02_assembly/round_01/candidate_01/attempt_{attempt_index:03d}"
        attempts.append(attempt)
        _json(
            attempt / "stage7_execution.json",
            {
                "schema_version": "2.0",
                "status": status,
                "attempt": {
                    "schema_version": "2.0",
                    "attempt_id": f"attempt_{attempt_index:03d}",
                    "attempt_index": attempt_index,
                    "candidate_index": 1,
                    "kind": "candidate",
                    "round_index": 1,
                    "run_id": "candidate_r01_c01",
                    "run_uuid": "abc",
                },
                "failure_category": "WORKFLOW" if status == "FAILED" else None,
                "error": "/private/workflow failed" if status == "FAILED" else None,
                "nextflow_command": (
                    []
                    if status == "FAILED"
                    else [
                        "/private/nextflow",
                        "--hifiasm_purge_level",
                        "3",
                        "--hifiasm_purge_similarity",
                        "0.55",
                        "--hifiasm_disable_post_join",
                        "true",
                    ]
                ),
                "started_at": "2026-07-29T10:00:00Z",
                "completed_at": "2026-07-29T10:10:00Z",
            },
        )
        _json(
            attempt / "artifact_inventory.json",
            {"entries": [{"relative_path": "artifact", "bytes": attempt_index * 100}]},
        )
    completed = attempts[1]
    lineage = {
        "status": "PASS",
        "requested_parameters": {"disable_post_join": True},
        "approved_parameters": {"disable_post_join": True},
        "rendered_parameters_with_defaults": {
            "purge_level": 3,
            "purge_similarity": 0.55,
            "hom_cov": None,
            "disable_post_join": True,
        },
        "realized_parameters_with_defaults": {
            "purge_level": 3,
            "purge_similarity": 0.55,
            "hom_cov": None,
            "disable_post_join": True,
        },
    }
    _json(completed / "parameter_lineage.json", lineage)
    candidate_metrics = metrics.model_copy(update={"run_id": "candidate_r01_c01"})
    _json(
        completed / "workflow/03_post_qc/candidate_r01_c01/assembly_metrics.json",
        candidate_metrics.model_dump(mode="json"),
    )
    trace = completed / "workflow/logs/trace.txt"
    trace.parent.mkdir(parents=True)
    trace.write_text(
        "status\trealtime\t%cpu\nCOMPLETED\t1m 30s\t200.0%\nCOMPLETED\t500ms\t100.0%\n"
    )
    proposal = tmp_path / "proposal.json"
    _json(
        proposal,
        {
            "decision_mode": "hybrid",
            "llm_status": "SUCCESS",
            "approved_candidates": [{"candidate_id": "disable_post_join"}],
            "rejected_proposals": [
                {
                    "proposal_id": "unsafe_shell",
                    "origin": "llm",
                    "reason_codes": ["PARAMETER_NOT_WHITELISTED"],
                }
            ],
        },
    )
    comparison = tmp_path / "comparison.json"
    _json(
        comparison,
        {
            "round_index": 1,
            "outcome": "STOP_PLATEAU",
            "policy_version": "2.0.0",
            "reason_codes": ["NO_METRIC_EXCEEDED_MATERIAL_THRESHOLD"],
        },
    )
    loop = tmp_path / "loop.json"
    _json(
        loop,
        {
            "terminal_outcome": "STOP_PLATEAU",
            "selected_run_id": None,
            "incumbent": {"run_id": "baseline"},
            "events": [
                {
                    "sequence": 1,
                    "round_index": 1,
                    "action": "STOP_PLATEAU",
                    "run_id": None,
                    "reason_codes": ["NO_METRIC_EXCEEDED_MATERIAL_THRESHOLD"],
                }
            ],
        },
    )
    llm = tmp_path / "llm.json"
    _json(
        llm,
        {
            "llm_status": "SUCCESS",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "response_id": "response",
            "prompt_sha256": "b" * 64,
            "proposal_output_sha256": "c" * 64,
            "raw_proposal_count": 1,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )
    index_path = tmp_path / "index.json"
    index_path.write_text('{"index": "fixture"}\n')
    return {
        "run": run,
        "stage7": stage7,
        "proposal": proposal,
        "comparison": comparison,
        "loop": loop,
        "llm": llm,
        "index": index_path,
    }


def _render(tmp_path: Path) -> tuple[dict[str, Path], V2FinalReport, Path]:
    paths = _fixture(tmp_path)
    output = tmp_path / "report"
    result = render_v2_report(
        paths["run"],
        output_dir=output,
        stage7_root=paths["stage7"],
        comparison_path=paths["comparison"],
        loop_state_path=paths["loop"],
        proposal_path=paths["proposal"],
        llm_receipt_path=paths["llm"],
        index_path=paths["index"],
        generated_at=FIXED_TIME,
    )
    return paths, V2FinalReport.model_validate_json(result.summary_json.read_text()), output


def test_report_alone_exposes_terminal_selection_and_stop_semantics(tmp_path: Path) -> None:
    _, report, output = _render(tmp_path)

    assert report.terminal_outcome == "STOP_PLATEAU"
    assert report.outcome_class == "STOPPED"
    assert report.optimization_succeeded is False
    assert report.optimization_selected_run_id is None
    assert report.final_run_id == "baseline"
    markdown = (output / "v2_final_report.md").read_text()
    assert "Outcome: **STOP_PLATEAU**" in markdown
    assert "Successful optimization: **false**" in markdown
    assert "Final recommended incumbent: `baseline`" in markdown


def test_report_lists_failed_completed_and_rejected_candidates(tmp_path: Path) -> None:
    _, report, output = _render(tmp_path)
    statuses = {(item.attempt_id, item.status) for item in report.runs}

    assert ("attempt_001", "FAILED") in statuses
    assert ("attempt_002", "COMPLETED") in statuses
    assert ("NOT_RUN", "REJECTED") in statuses
    with (output / "all_runs.tsv").open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert {row["status"] for row in rows} >= {"FAILED", "COMPLETED", "REJECTED"}


def test_parameter_table_matches_actual_argv_and_contract(tmp_path: Path) -> None:
    _, report, output = _render(tmp_path)
    completed = next(item for item in report.runs if item.attempt_id == "attempt_002")

    assert completed.parameter_contract_status == "PASS"
    assert completed.cpu_hours == pytest.approx((180.0 + 0.5) / 3600.0)
    assert completed.walltime_hours == pytest.approx(1 / 6)
    assert all(item.argv_matches_realized for item in completed.parameters)
    with (output / "all_parameters.tsv").open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    disable = next(
        row
        for row in rows
        if row["attempt_id"] == "attempt_002" and row["parameter"] == "disable_post_join"
    )
    assert disable["requested"] == disable["approved"] == disable["argv_value"] == "True"


def test_evidence_classes_llm_provenance_and_default_redaction(tmp_path: Path) -> None:
    paths, report, output = _render(tmp_path)

    assert {item.kind for item in report.evidence} == {
        "FACT",
        "DERIVED",
        "RULE_CONCLUSION",
        "LLM_TEXT",
    }
    assert report.llm.provider == "deepseek"
    assert report.llm.index_sha256 == hashlib.sha256(paths["index"].read_bytes()).hexdigest()
    combined = (output / "v2_final_report.json").read_text() + (
        output / "v2_final_report.md"
    ).read_text()
    assert str(tmp_path) not in combined
    assert "/private/" not in combined
    assert "[LLM TEXT — NOT FACT]" in combined


def test_stop_schema_cannot_be_relabelled_as_success(tmp_path: Path) -> None:
    _, report, _ = _render(tmp_path)
    payload = report.model_dump(mode="json")
    payload["outcome_class"] = "ACCEPTED"
    payload["optimization_succeeded"] = True

    with pytest.raises(ValidationError, match="STOP outcomes"):
        V2FinalReport.model_validate(payload)


def test_v1_history_and_failed_baseline_receive_compatibility_reports(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    candidate = paths["run"] / "03_post_qc/candidate_old/assembly_metrics.json"
    _json(candidate, {"run_id": "candidate_old", "contig_n50": 10})
    _json(
        paths["run"] / "05_agent/optimization/optimization_result.json",
        {"outcome": "STOP_METRIC_CONFLICT"},
    )

    outputs = render_v2_report(paths["run"], output_dir=tmp_path / "compat")
    report = V2FinalReport.model_validate_json(outputs.summary_json.read_text())

    assert report.compatibility_mode == "V1_COMPATIBILITY"
    assert report.terminal_outcome == "STOP_METRIC_CONFLICT"
    assert any(item.run_id == "candidate_old" for item in report.runs)
