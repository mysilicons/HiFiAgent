"""Stage 10 cross-stage V2 report collection and rendering."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import yaml

from hifi_agent.agent.models import AssemblyParameters
from hifi_agent.exceptions import InputValidationError
from hifi_agent.reporting.v2_models import (
    OutcomeClass,
    ParameterContractStatus,
    Scalar,
    V2EvidenceBlock,
    V2FinalReport,
    V2InputRecord,
    V2LLMRecord,
    V2ParameterLineage,
    V2RunRecord,
)

PARAMETER_FLAGS = {
    "purge_level": "--hifiasm_purge_level",
    "purge_similarity": "--hifiasm_purge_similarity",
    "hom_cov": "--hifiasm_hom_cov",
    "disable_post_join": "--hifiasm_disable_post_join",
}
METRIC_NAMES = (
    "assembly_size",
    "assembly_size_ratio",
    "contig_count",
    "contig_n50",
    "longest_contig",
    "quast_misassemblies",
    "busco_complete",
    "busco_duplicated",
    "kmer_completeness",
    "kmer_qv",
    "mapped_read_fraction",
    "coverage_cv",
)


@dataclass(frozen=True)
class V2ReportOutputs:
    """Paths produced by one Stage 10 V2 report render."""

    output_dir: Path
    markdown: Path
    summary_json: Path
    all_runs_tsv: Path
    all_parameters_tsv: Path


def render_v2_report(
    run_dir: Path,
    *,
    output_dir: Path,
    stage7_root: Path | None = None,
    comparison_path: Path | None = None,
    loop_state_path: Path | None = None,
    proposal_path: Path | None = None,
    llm_receipt_path: Path | None = None,
    index_path: Path | None = None,
    redact_paths: bool = True,
    generated_at: datetime | None = None,
) -> V2ReportOutputs:
    """Collect Stage 0-9 evidence and write the complete Stage 10 report."""
    roots = _Roots(
        run_dir=run_dir.resolve(),
        stage7_root=stage7_root.resolve() if stage7_root else None,
        comparison_path=comparison_path.resolve() if comparison_path else None,
        loop_state_path=loop_state_path.resolve() if loop_state_path else None,
        proposal_path=proposal_path.resolve() if proposal_path else None,
        llm_receipt_path=llm_receipt_path.resolve() if llm_receipt_path else None,
        index_path=index_path.resolve() if index_path else None,
    )
    report = _collect(roots, redact_paths=redact_paths, generated_at=generated_at)
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    summary = destination / "v2_final_report.json"
    markdown = destination / "v2_final_report.md"
    runs_tsv = destination / "all_runs.tsv"
    parameters_tsv = destination / "all_parameters.tsv"
    summary.write_text(report.model_dump_json(indent=2) + "\n")
    markdown.write_text(_markdown(report))
    _write_runs(report, runs_tsv)
    _write_parameters(report, parameters_tsv)
    return V2ReportOutputs(destination, markdown, summary, runs_tsv, parameters_tsv)


@dataclass(frozen=True)
class _Roots:
    run_dir: Path
    stage7_root: Path | None
    comparison_path: Path | None
    loop_state_path: Path | None
    proposal_path: Path | None
    llm_receipt_path: Path | None
    index_path: Path | None


def _collect(
    roots: _Roots,
    *,
    redact_paths: bool,
    generated_at: datetime | None,
) -> V2FinalReport:
    config_path = roots.run_dir / "00_metadata/resolved_config.yaml"
    metrics_path = roots.run_dir / "03_post_qc/baseline/assembly_metrics.json"
    if not config_path.is_file():
        raise InputValidationError(f"V2 report resolved config missing: {config_path}")
    config = _yaml(config_path)
    sample_id = str(config["sample_id"])
    baseline_metrics = _json(metrics_path) if metrics_path.is_file() else {}
    baseline_parameters = AssemblyParameters().model_dump(mode="json")
    inputs = _inputs(roots.run_dir, roots, redact_paths)
    runs = [
        _baseline_run(
            roots,
            baseline_parameters,
            baseline_metrics,
            redact_paths=redact_paths,
        )
    ]
    if roots.stage7_root is not None:
        runs.extend(_stage7_runs(roots, redact_paths=redact_paths))
    else:
        runs.extend(_v1_candidate_runs(roots, redact_paths=redact_paths))

    proposal = _json(roots.proposal_path) if roots.proposal_path else {}
    receipt = _json(roots.llm_receipt_path) if roots.llm_receipt_path else {}
    rejected = cast(list[dict[str, object]], proposal.get("rejected_proposals", []))
    runs.extend(_rejected_runs(rejected))
    loop = _json(roots.loop_state_path) if roots.loop_state_path else {}
    comparison = _json(roots.comparison_path) if roots.comparison_path else {}
    terminal = str(loop.get("terminal_outcome") or _v1_outcome(roots.run_dir))
    selected_run = cast(str | None, loop.get("selected_run_id"))
    incumbent_run = cast(dict[str, object], loop.get("incumbent", {})).get("run_id")
    final_run = selected_run
    if final_run is None and (terminal.startswith("ACCEPTED_") or terminal == "STOP_PLATEAU"):
        final_run = str(incumbent_run) if incumbent_run is not None else None
    outcome_class = _outcome_class(terminal)
    final_path = _final_path(roots, final_run, outcome_class)
    llm = _llm_record(proposal, receipt, roots.index_path)
    evidence = [
        V2EvidenceBlock(
            evidence_id="input_and_metric_facts",
            kind="FACT",
            source=_display(metrics_path, roots, redact_paths),
            content={"baseline_metrics": baseline_metrics, "input_count": len(inputs)},
        ),
        V2EvidenceBlock(
            evidence_id="comparison_derivation",
            kind="DERIVED",
            source=_display(roots.comparison_path, roots, redact_paths),
            content={
                "outcome": comparison.get("outcome"),
                "policy_version": comparison.get("policy_version"),
            },
        ),
        V2EvidenceBlock(
            evidence_id="rule_conclusion",
            kind="RULE_CONCLUSION",
            source=_display(roots.proposal_path, roots, redact_paths),
            content={
                "decision_mode": proposal.get("decision_mode", "NOT_RECORDED"),
                "terminal_status": proposal.get("terminal_status"),
                "approved_candidate_ids": [
                    item.get("candidate_id")
                    for item in cast(
                        list[dict[str, object]],
                        proposal.get("approved_candidates", []),
                    )
                ],
            },
        ),
        V2EvidenceBlock(
            evidence_id="llm_provenance_not_fact",
            kind="LLM_TEXT",
            source=_display(roots.llm_receipt_path, roots, redact_paths),
            content={
                "status": llm.status,
                "provider": llm.provider,
                "model": llm.model,
                "raw_proposal_count": llm.raw_proposal_count,
                "note": "LLM output is untrusted proposal text and never a measured fact.",
            },
        ),
    ]
    timeline = _timeline(loop, comparison)
    limitations = [
        "LLM text is isolated from measured facts and deterministic conclusions.",
        "A STOP outcome is a safe terminal decision, not a successful optimization.",
    ]
    if roots.stage7_root is None:
        limitations.append("V1 compatibility mode has no immutable V2 attempt lineage.")
    if not baseline_metrics:
        limitations.append("Baseline post-QC metrics are unavailable.")
    events = cast(list[dict[str, object]], loop.get("events", []))
    report = V2FinalReport(
        generated_at=generated_at or datetime.now(UTC),
        sample_id=sample_id,
        compatibility_mode="V2" if roots.stage7_root else "V1_COMPATIBILITY",
        paths_redacted=redact_paths,
        terminal_outcome=terminal,
        outcome_class=outcome_class,
        optimization_succeeded=outcome_class == "ACCEPTED",
        optimization_selected_run_id=selected_run,
        final_run_id=final_run,
        final_assembly_path=final_path,
        stop_reason_codes=cast(list[str], events[-1].get("reason_codes", [])) if events else [],
        inputs=inputs,
        pre_qc=_json(roots.run_dir / "01_pre_qc/raw_metrics.json"),
        baseline_parameters=baseline_parameters,
        baseline_metrics=_metrics(baseline_metrics),
        decision_mode=str(proposal.get("decision_mode", "V1_NOT_RECORDED")),
        llm=llm,
        approved_candidates=cast(list[dict[str, object]], proposal.get("approved_candidates", [])),
        rejected_proposals=rejected,
        runs=runs,
        incumbent_timeline=timeline,
        tools_and_provenance=_provenance(roots, redact_paths),
        limitations=limitations,
        review_recommendations=_recommendations(terminal),
        evidence=evidence,
    )
    if not redact_paths:
        return report
    sanitized = _sanitize(report.model_dump(mode="json"), roots)
    return V2FinalReport.model_validate(sanitized)


def _baseline_run(
    roots: _Roots,
    parameters: dict[str, Scalar],
    metrics: dict[str, object],
    *,
    redact_paths: bool,
) -> V2RunRecord:
    command_path = roots.run_dir / "02_assembly/baseline/metadata/hifiasm_command.txt"
    command = shlex.split(command_path.read_text().strip()) if command_path.is_file() else []
    return V2RunRecord(
        run_id="baseline",
        attempt_id="baseline",
        round_index=0,
        kind="baseline",
        status="COMPLETED" if metrics else "FAILED",
        parameter_contract_status="NOT_APPLICABLE",
        parameters=[
            V2ParameterLineage(
                parameter=name,
                requested=value,
                approved=value,
                rendered=value,
                realized=value,
                argv_value=_baseline_argv_value(command, name),
                contract_status="NOT_APPLICABLE",
                argv_matches_realized=None,
            )
            for name, value in parameters.items()
        ],
        metrics=_metrics(metrics),
        command=[_redact_token(item, roots) if redact_paths else item for item in command],
        source=_display(command_path, roots, redact_paths),
    )


def _stage7_runs(roots: _Roots, *, redact_paths: bool) -> list[V2RunRecord]:
    assert roots.stage7_root is not None
    records: list[V2RunRecord] = []
    for receipt_path in sorted(
        roots.stage7_root.glob("02_assembly/round_*/candidate_*/attempt_*/stage7_execution.json")
    ):
        receipt = _json(receipt_path)
        attempt = cast(dict[str, object], receipt["attempt"])
        lineage_path = receipt_path.parent / "parameter_lineage.json"
        lineage = _json(lineage_path) if lineage_path.is_file() else {}
        command = cast(list[str], receipt.get("nextflow_command", []))
        argv = _nextflow_parameters(command)
        parameter_rows = _lineage_rows(lineage, argv)
        metrics_path = (
            receipt_path.parent / f"workflow/03_post_qc/{attempt['run_id']}/assembly_metrics.json"
        )
        inventory = _json(receipt_path.parent / "artifact_inventory.json")
        entries = cast(list[dict[str, object]], inventory.get("entries", []))
        records.append(
            V2RunRecord(
                run_id=str(attempt["run_id"]),
                attempt_id=str(attempt["attempt_id"]),
                round_index=int(cast(int, attempt["round_index"])),
                candidate_index=int(cast(int, attempt["candidate_index"])),
                kind="candidate",
                status="COMPLETED" if receipt["status"] == "COMPLETED" else "FAILED",
                failure_category=cast(str | None, receipt.get("failure_category")),
                error=_redact_optional(cast(str | None, receipt.get("error")), roots)
                if redact_paths
                else cast(str | None, receipt.get("error")),
                parameter_contract_status=_contract_status(
                    lineage.get("status", "MISSING")
                    if receipt["status"] == "COMPLETED"
                    else "MISSING"
                ),
                parameters=parameter_rows,
                metrics=_metrics(_json(metrics_path)) if metrics_path.is_file() else {},
                command=[_redact_token(item, roots) if redact_paths else item for item in command],
                cpu_hours=_trace_cpu_hours(receipt_path.parent),
                walltime_hours=_receipt_walltime_hours(receipt),
                disk_bytes=sum(int(cast(int, item.get("bytes", 0))) for item in entries),
                source=_display(receipt_path, roots, redact_paths),
            )
        )
    return records


def _v1_candidate_runs(roots: _Roots, *, redact_paths: bool) -> list[V2RunRecord]:
    records: list[V2RunRecord] = []
    for path in sorted((roots.run_dir / "03_post_qc").glob("candidate*/assembly_metrics.json")):
        run_id = path.parent.name
        records.append(
            V2RunRecord(
                run_id=run_id,
                attempt_id="v1_unversioned",
                round_index=1,
                candidate_index=1,
                kind="candidate",
                status="COMPLETED",
                parameter_contract_status="MISSING",
                metrics=_metrics(_json(path)),
                source=_display(path, roots, redact_paths),
            )
        )
    return records


def _rejected_runs(items: list[dict[str, object]]) -> list[V2RunRecord]:
    return [
        V2RunRecord(
            run_id=str(item.get("proposal_id", item.get("candidate_id", f"rejected_{index}"))),
            attempt_id="NOT_RUN",
            round_index=0,
            kind="rejected_proposal",
            status="REJECTED",
            reason_codes=cast(list[str], item.get("reason_codes", [])),
            parameter_contract_status="NOT_APPLICABLE",
            source="proposal_decision.json",
        )
        for index, item in enumerate(items, start=1)
    ]


def _lineage_rows(
    lineage: dict[str, object],
    argv: dict[str, Scalar],
) -> list[V2ParameterLineage]:
    if not lineage:
        return []
    requested = cast(dict[str, Scalar], lineage["requested_parameters"])
    approved = cast(dict[str, Scalar], lineage["approved_parameters"])
    rendered = cast(dict[str, Scalar], lineage["rendered_parameters_with_defaults"])
    realized = cast(dict[str, Scalar], lineage["realized_parameters_with_defaults"])
    status = cast(str, lineage["status"])
    rows: list[V2ParameterLineage] = []
    for name in PARAMETER_FLAGS:
        argv_value = argv.get(name)
        realized_value = realized.get(name)
        rows.append(
            V2ParameterLineage(
                parameter=name,
                requested=requested.get(name),
                approved=approved.get(name),
                rendered=rendered.get(name),
                realized=realized_value,
                argv_value=argv_value,
                contract_status=_contract_status(status),
                argv_matches_realized=argv_value == realized_value,
            )
        )
    return rows


def _nextflow_parameters(command: list[str]) -> dict[str, Scalar]:
    observed: dict[str, Scalar] = {}
    for name, flag in PARAMETER_FLAGS.items():
        if flag not in command:
            observed[name] = None
            continue
        value = command[command.index(flag) + 1]
        if name in {"purge_level", "hom_cov"}:
            observed[name] = int(value)
        elif name == "purge_similarity":
            observed[name] = float(value)
        else:
            observed[name] = value.lower() == "true"
    return observed


def _baseline_argv_value(command: list[str], parameter: str) -> Scalar:
    flags = {
        "purge_level": "-l",
        "purge_similarity": "-s",
        "hom_cov": "--hom-cov",
        "disable_post_join": "-u0",
    }
    flag = flags[parameter]
    if parameter == "disable_post_join":
        return flag in command
    if flag not in command:
        return None
    value = command[command.index(flag) + 1]
    return int(value) if parameter in {"purge_level", "hom_cov"} else float(value)


def _inputs(run_dir: Path, roots: _Roots, redact_paths: bool) -> list[V2InputRecord]:
    path = run_dir / "00_metadata/input_checksums.tsv"
    if not path.is_file():
        return []
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return [
        V2InputRecord(
            role=row["role"],
            path=_redact_text(row["path"], roots) if redact_paths else row["path"],
            sha256=row["sha256"],
            bytes=int(row["bytes"]),
        )
        for row in rows
    ]


def _llm_record(
    proposal: dict[str, object],
    receipt: dict[str, object],
    index_path: Path | None,
) -> V2LLMRecord:
    usage = cast(dict[str, object], receipt.get("usage", {}))
    return V2LLMRecord(
        status=str(receipt.get("llm_status", proposal.get("llm_status", "NOT_RECORDED"))),
        provider=cast(str | None, receipt.get("provider", proposal.get("provider"))),
        model=cast(str | None, receipt.get("model", proposal.get("model"))),
        response_id=cast(str | None, receipt.get("response_id")),
        index_sha256=(
            cast(str | None, proposal.get("index_sha256"))
            or (_sha256(index_path) if index_path and index_path.is_file() else None)
        ),
        prompt_sha256=cast(str | None, receipt.get("prompt_sha256", proposal.get("prompt_sha256"))),
        proposal_output_sha256=cast(str | None, receipt.get("proposal_output_sha256")),
        prompt_tokens=int(cast(int, usage.get("prompt_tokens", 0))),
        completion_tokens=int(cast(int, usage.get("completion_tokens", 0))),
        total_tokens=int(cast(int, usage.get("total_tokens", 0))),
        raw_proposal_count=int(cast(int, receipt.get("raw_proposal_count", 0))),
        rejected_proposal_count=len(
            cast(list[dict[str, object]], proposal.get("rejected_proposals", []))
        ),
    )


def _timeline(loop: dict[str, object], comparison: dict[str, object]) -> list[dict[str, object]]:
    if loop:
        return [
            {
                "sequence": event["sequence"],
                "round_index": event["round_index"],
                "action": event["action"],
                "run_id": event.get("run_id"),
                "reason_codes": event["reason_codes"],
            }
            for event in cast(list[dict[str, object]], loop.get("events", []))
        ]
    if comparison:
        return [
            {
                "sequence": 1,
                "round_index": comparison.get("round_index"),
                "action": comparison.get("outcome"),
                "run_id": comparison.get("selected_run_id"),
                "reason_codes": comparison.get("reason_codes", []),
            }
        ]
    return []


def _provenance(roots: _Roots, redact_paths: bool) -> list[dict[str, object]]:
    paths = {
        "resolved_config": roots.run_dir / "00_metadata/resolved_config.yaml",
        "input_checksums": roots.run_dir / "00_metadata/input_checksums.tsv",
        "pre_qc": roots.run_dir / "01_pre_qc/raw_metrics.json",
        "baseline_metrics": roots.run_dir / "03_post_qc/baseline/assembly_metrics.json",
        "proposal": roots.proposal_path,
        "comparison": roots.comparison_path,
        "loop_state": roots.loop_state_path,
        "llm_receipt": roots.llm_receipt_path,
        "knowledge_index": roots.index_path,
    }
    return [
        {
            "artifact_id": name,
            "path": _display(path, roots, redact_paths),
            "available": path is not None and path.is_file(),
        }
        for name, path in paths.items()
    ]


def _final_path(
    roots: _Roots,
    final_run: str | None,
    outcome_class: str,
) -> str | None:
    if outcome_class not in {"ACCEPTED", "STOPPED"} or final_run is None:
        return None
    path: Path | None
    if final_run == "baseline":
        path = roots.run_dir / "02_assembly/baseline/fasta/baseline.primary.fa"
    elif roots.stage7_root is not None:
        matches = list(
            roots.stage7_root.glob(
                f"02_assembly/round_*/candidate_*/attempt_*/workflow/02_assembly/"
                f"{final_run}/fasta/{final_run}.primary.fa"
            )
        )
        candidate_path: Path | None = matches[-1] if matches else None
        path = candidate_path
    else:
        path = roots.run_dir / f"02_assembly/{final_run}/fasta/{final_run}.primary.fa"
    return _display(path, roots, True) if path is not None else None


def _v1_outcome(run_dir: Path) -> str:
    path = run_dir / "05_agent/optimization/optimization_result.json"
    if path.is_file():
        return str(_json(path).get("outcome", "INCOMPLETE"))
    return "INCOMPLETE"


def _outcome_class(outcome: str) -> OutcomeClass:
    if outcome.startswith("ACCEPT"):
        return "ACCEPTED"
    if outcome.startswith("STOP"):
        return "STOPPED"
    if outcome.startswith("FAIL"):
        return "FAILED"
    return "INCOMPLETE"


def _metrics(payload: dict[str, object]) -> dict[str, Scalar]:
    return {name: cast(Scalar, payload.get(name)) for name in METRIC_NAMES}


def _trace_cpu_hours(attempt_dir: Path) -> float:
    path = attempt_dir / "workflow/logs/trace.txt"
    if not path.is_file():
        return 0.0
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return (
        sum(
            _duration_seconds(row["realtime"]) * float(row["%cpu"].rstrip("%")) / 100.0
            for row in rows
            if row["status"] == "COMPLETED"
        )
        / 3600.0
    )


def _receipt_walltime_hours(receipt: dict[str, object]) -> float:
    started = receipt.get("started_at")
    completed = receipt.get("completed_at")
    if not isinstance(started, str) or not isinstance(completed, str):
        return 0.0
    left = datetime.fromisoformat(started.replace("Z", "+00:00"))
    right = datetime.fromisoformat(completed.replace("Z", "+00:00"))
    return (right - left).total_seconds() / 3600.0


def _duration_seconds(value: str) -> float:
    total = 0.0
    for number, unit in re.findall(r"([0-9]+(?:\.[0-9]+)?)(ms|h|m|s)", value):
        amount = float(number)
        total += (
            amount / 1000.0
            if unit == "ms"
            else amount * 60.0
            if unit == "m"
            else amount * 3600.0
            if unit == "h"
            else amount
        )
    return total


def _recommendations(outcome: str) -> list[str]:
    if outcome == "STOP_PLATEAU":
        return [
            "Retain the current incumbent.",
            "Do not spend another optimization round without new evidence.",
        ]
    if outcome.startswith("STOP_"):
        return ["Review the stop reason and unresolved evidence before any new execution."]
    if outcome.startswith("ACCEPT"):
        return ["Use the selected assembly and preserve its complete provenance."]
    return ["Complete missing workflow evidence before selecting an assembly."]


def _markdown(report: V2FinalReport) -> str:
    labels = {
        "FACT": "[FACT]",
        "DERIVED": "[DERIVED]",
        "RULE_CONCLUSION": "[RULE CONCLUSION]",
        "LLM_TEXT": "[LLM TEXT — NOT FACT]",
    }
    lines = [
        f"# HiFi Agent V2 final report — {report.sample_id}",
        "",
        "## 1. Execution summary and terminal state",
        "",
        f"- Outcome: **{report.terminal_outcome}**",
        f"- Outcome class: **{report.outcome_class}**",
        f"- Successful optimization: **{str(report.optimization_succeeded).lower()}**",
        f"- Optimization-selected candidate: `{report.optimization_selected_run_id or 'NONE'}`",
        f"- Final recommended incumbent: `{report.final_run_id or 'NONE'}`",
        f"- Final assembly: `{report.final_assembly_path or 'NONE'}`",
        f"- Stop reasons: {', '.join(report.stop_reason_codes) or 'NONE'}",
        "",
        "## 2. Inputs and checksums",
        "",
        *[
            f"- `{item.role}`: `{item.path}`; `{item.sha256}`; {item.bytes} bytes"
            for item in report.inputs
        ],
        "",
        "## 3. Pre-QC and confidence",
        "",
        f"```json\n{json.dumps(report.pre_qc, indent=2, sort_keys=True)}\n```",
        "",
        "## 4. Baseline parameters and quality",
        "",
        f"Parameters: `{json.dumps(report.baseline_parameters, sort_keys=True)}`",
        f"Metrics: `{json.dumps(report.baseline_metrics, sort_keys=True)}`",
        "",
        "## 5. Decision mode and LLM state",
        "",
        f"- Decision mode: `{report.decision_mode}`",
        f"- LLM: `{report.llm.status}`; provider `{report.llm.provider}`; "
        f"model `{report.llm.model}`",
        f"- Index hash: `{report.llm.index_sha256}`; prompt hash: `{report.llm.prompt_sha256}`",
        "",
        "## 6. Per-round RAG, rules, and LLM proposals",
        "",
        *[
            f"- {labels[item.kind]} `{item.evidence_id}` from `{item.source}`: "
            f"`{json.dumps(item.content, sort_keys=True)}`"
            for item in report.evidence
        ],
        "",
        "## 7. Candidate requested, approved, rendered, and realized parameters",
        "",
        "See `all_parameters.tsv`; rejected proposals: "
        f"{len(report.rejected_proposals)}; approved candidates: "
        f"{len(report.approved_candidates)}.",
        "",
        "## 8. All assembly metrics",
        "",
        "See `all_runs.tsv`. Every candidate attempt and rejected proposal is retained.",
        "",
        "## 9. Incumbent timeline",
        "",
        f"```json\n{json.dumps(report.incumbent_timeline, indent=2, sort_keys=True)}\n```",
        "",
        "## 10. Stop, round, risk, and budget reason",
        "",
        f"`{report.terminal_outcome}` with `{', '.join(report.stop_reason_codes) or 'NONE'}`.",
        "",
        "## 11. Final recommended assembly",
        "",
        f"`{report.final_assembly_path or 'No candidate selected; retain incumbent evidence.'}`",
        "",
        "## 12. Tool, command, resource, and provenance",
        "",
        f"```json\n{json.dumps(report.tools_and_provenance, indent=2, sort_keys=True)}\n```",
        "",
        "## 13. Limitations, uncertainty, and human review",
        "",
        *[f"- {item}" for item in report.limitations],
        *[f"- Recommendation: {item}" for item in report.review_recommendations],
        "",
    ]
    return "\n".join(lines)


def _write_runs(report: V2FinalReport, path: Path) -> None:
    fields = [
        "run_id",
        "attempt_id",
        "round_index",
        "candidate_index",
        "kind",
        "status",
        "failure_category",
        "parameter_contract_status",
        "cpu_hours",
        "walltime_hours",
        "disk_bytes",
        "metrics",
        "reason_codes",
        "source",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for item in report.runs:
            row = item.model_dump(mode="json")
            row["metrics"] = json.dumps(row["metrics"], sort_keys=True)
            row["reason_codes"] = ",".join(row["reason_codes"])
            writer.writerow({name: row.get(name, "") for name in fields})


def _write_parameters(report: V2FinalReport, path: Path) -> None:
    fields = [
        "run_id",
        "attempt_id",
        "parameter",
        "requested",
        "approved",
        "rendered",
        "realized",
        "argv_value",
        "contract_status",
        "argv_matches_realized",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for run in report.runs:
            for parameter in run.parameters:
                writer.writerow(
                    {
                        "run_id": run.run_id,
                        "attempt_id": run.attempt_id,
                        **parameter.model_dump(mode="json"),
                    }
                )


def _display(path: Path | None, roots: _Roots, redact: bool) -> str:
    if path is None:
        return "NOT_AVAILABLE"
    return _redact_text(str(path), roots) if redact else str(path)


def _redact_token(value: str, roots: _Roots) -> str:
    return _redact_text(value, roots)


def _redact_text(value: str, roots: _Roots) -> str:
    replacements = [
        (roots.stage7_root, "${STAGE7_ROOT}"),
        (roots.run_dir, "${RUN_DIR}"),
        (Path(__file__).resolve().parents[3], "${PROJECT_ROOT}"),
        (Path("/home/gw"), "${HOME}"),
        (Path("/data/gw"), "${DATA_ROOT}"),
    ]
    output = value
    for root, marker in replacements:
        if root is not None:
            output = output.replace(str(root), marker)
    output = re.sub(
        r"(?<![A-Za-z0-9_$:}])/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+",
        "${ABS_PATH}",
        output,
    )
    return output


def _redact_optional(value: str | None, roots: _Roots) -> str | None:
    return _redact_text(value, roots) if value is not None else None


def _contract_status(value: object) -> ParameterContractStatus:
    observed = str(value)
    if observed not in {"PASS", "FAIL", "MISSING", "NOT_APPLICABLE"}:
        return "MISSING"
    return cast(ParameterContractStatus, observed)


def _sanitize(value: object, roots: _Roots) -> object:
    if isinstance(value, str):
        return _redact_text(value, roots)
    if isinstance(value, list):
        return [_sanitize(item, roots) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item, roots) for key, item in value.items()}
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path | None) -> dict[str, object]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise InputValidationError(f"Expected JSON object: {path}")
    return cast(dict[str, object], payload)


def _yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        raise InputValidationError(f"Expected YAML mapping: {path}")
    return cast(dict[str, object], payload)
