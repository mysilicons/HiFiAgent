"""Manifest-driven current terminal report generation with consistent JSON/Markdown/TSV facts."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from hifi_agent.decision.models import ProposalDecision
from hifi_agent.exceptions import AgentStateError
from hifi_agent.executors.hifiasm_contract import RealizedParameters, RenderedArgv
from hifi_agent.executors.models import ArtifactInventory
from hifi_agent.orchestration.budget import BudgetLedger
from hifi_agent.orchestration.manifests import (
    AssemblyAttemptRecord,
    HistoryManifest,
    ManifestStore,
    RoundRecord,
)
from hifi_agent.orchestration.runtime_models import RunState, sha256_file
from hifi_agent.orchestration.verifier import VerificationReport
from hifi_agent.reporting.models import (
    AttemptSummary,
    FinalSummary,
    LLMActivitySummary,
    ProposalSummary,
    RoundSummary,
    process_exit_code_for_terminal,
)
from hifi_agent.schemas.assembly import AssemblyConfig
from hifi_agent.schemas.metrics import AssemblyMetrics


@dataclass(frozen=True)
class ReportBundle:
    """Canonical current report paths returned to the coordinator."""

    markdown: Path
    summary: Path
    runs_tsv: Path
    parameters_tsv: Path
    provenance_tsv: Path
    verification: Path

    def paths(self) -> tuple[Path, ...]:
        """Return the fixed canonical report path order."""
        return (
            self.markdown,
            self.summary,
            self.runs_tsv,
            self.parameters_tsv,
            self.provenance_tsv,
            self.verification,
        )


class ReportService:
    """Generate all terminal reports only from immutable current control artifacts."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.report_dir = self.run_dir / "06_report"
        self.bundle = ReportBundle(
            markdown=self.report_dir / "final_report.md",
            summary=self.report_dir / "final_summary.json",
            runs_tsv=self.report_dir / "all_runs.tsv",
            parameters_tsv=self.report_dir / "all_parameters.tsv",
            provenance_tsv=self.report_dir / "provenance.tsv",
            verification=self.report_dir / "verification_report.json",
        )

    def generate(
        self,
        state: RunState,
        *,
        verification_status: Literal["PENDING", "PASS", "WARNING", "FAIL"] = "PENDING",
    ) -> FinalSummary:
        """Regenerate deterministic report views without changing any source fact."""
        if state.terminal_outcome is None or state.outcome_class is None:
            raise AgentStateError("Terminal reporting requires an outcome and outcome class")
        history = ManifestStore(self.run_dir).verify()
        attempts = tuple(
            self._attempt(reference.relative_path) for reference in history.attempt_refs
        )
        rounds = tuple(self._round(reference.relative_path) for reference in history.round_refs)
        decisions = self._proposal_decisions()
        proposals = self._proposals(decisions, attempts)
        budget = BudgetLedger(self.run_dir).snapshot()
        incumbent_chain = _incumbent_chain(state.baseline_run_ref, rounds)
        reasons = tuple(state.terminal_reason_codes)
        summary = FinalSummary(
            generated_at=(
                state.last_event.timestamp if state.last_event else state.identity.created_at
            ),
            run_uuid=state.identity.run_uuid,
            sample_id=state.identity.sample_id,
            package_version=state.identity.package_version,
            code_commit=state.identity.code_commit,
            terminal_outcome=state.terminal_outcome,
            outcome_class=state.outcome_class,
            process_exit_code=process_exit_code_for_terminal(
                state.terminal_outcome,
                state.outcome_class,
            ),
            selected_run_ref=state.incumbent_run_ref,
            baseline_run_ref=state.baseline_run_ref,
            incumbent_chain=incumbent_chain,
            attempts=attempts,
            rounds=rounds,
            proposals=proposals,
            llm_activity=self._llm_activity(decisions),
            budget_limits={item.value: value for item, value in budget.limits.items()},
            budget_reserved={item.value: value for item, value in budget.reserved.items()},
            budget_committed={item.value: value for item, value in budget.committed.items()},
            budget_remaining={item.value: value for item, value in budget.balance.items()},
            stop_reason_codes=reasons or (state.terminal_outcome,),
            scientific_limitations=(
                "The selected assembly is supported only within the evaluated candidates.",
                "No claim of global parameter optimality is made.",
            ),
            verification_status=verification_status,
        )
        self.report_dir.mkdir(parents=True, exist_ok=True)
        _atomic_text(self.bundle.summary, summary.model_dump_json(indent=2) + "\n")
        _atomic_text(self.bundle.markdown, _render_markdown(summary))
        _atomic_tsv(self.bundle.runs_tsv, _runs_rows(summary))
        _atomic_tsv(self.bundle.parameters_tsv, _parameter_rows(summary))
        _atomic_tsv(self.bundle.provenance_tsv, self._provenance_rows(history))
        return summary

    def write_verification(self, report: VerificationReport) -> Path:
        """Persist the coordinator's deep verification result as the sixth report artifact."""
        _atomic_text(self.bundle.verification, report.model_dump_json(indent=2) + "\n")
        return self.bundle.verification

    def _attempt(self, relative_manifest: Path) -> AttemptSummary:
        path = self.run_dir / relative_manifest
        try:
            record = AssemblyAttemptRecord.model_validate_json(path.read_text())
            if (
                record.requested_config_ref is None
                or record.approved_config_ref is None
                or record.rendered_config_ref is None
            ):
                raise AgentStateError(
                    "Attempt report references lack requested/approved/rendered config"
                )
            requested_payload = json.loads(
                (self.run_dir / record.requested_config_ref.relative_path).read_text()
            )
            requested = requested_payload.get("requested")
            if not isinstance(requested, dict):
                raise AgentStateError("Attempt requested config is not a JSON object")
            approved = AssemblyConfig.model_validate_json(
                (self.run_dir / record.approved_config_ref.relative_path).read_text()
            )
            rendered = RenderedArgv.model_validate_json(
                (self.run_dir / record.rendered_config_ref.relative_path).read_text()
            )
            realized = (
                RealizedParameters.model_validate_json(
                    (self.run_dir / record.realized_config_ref.relative_path).read_text()
                )
                if record.realized_config_ref is not None
                else None
            )
            metrics = _attempt_metrics(self.run_dir, record)
        except (OSError, ValidationError, ValueError) as exc:
            raise AgentStateError(
                f"Cannot collect current attempt report facts: {path}: {exc}"
            ) from exc
        return AttemptSummary(
            attempt_id=record.attempt_id,
            attempt_ref=relative_manifest,
            round_index=record.round_index,
            candidate_index=record.candidate_index,
            status=record.status,
            comparison_eligible=record.comparison_eligible,
            requested_config=requested,
            approved_parameters=approved.parameters.model_dump(mode="python"),
            rendered_argv=rendered.argv,
            realized_parameters=(
                realized.parameters.model_dump(mode="python") if realized is not None else None
            ),
            metrics=_report_metrics(metrics),
            resource_usage=record.resource_usage.model_dump(mode="python"),
            error=record.error,
            reason_codes=tuple(record.ineligible_reason_codes),
        )

    def _proposals(
        self,
        decisions: tuple[tuple[int, ProposalDecision], ...],
        attempts: tuple[AttemptSummary, ...],
    ) -> tuple[ProposalSummary, ...]:
        summaries: list[ProposalSummary] = []
        for round_index, decision in decisions:
            for candidate_index, proposal in enumerate(decision.approved, start=1):
                executed = tuple(
                    item.attempt_ref
                    for item in attempts
                    if item.round_index == round_index and item.candidate_index == candidate_index
                )
                summaries.append(
                    ProposalSummary(
                        round_index=round_index,
                        proposal_id=proposal.proposal_id,
                        disposition="APPROVED",
                        candidate_index=candidate_index,
                        origin=proposal.origin,
                        requested_changes={
                            str(name): value for name, value in proposal.approved_diff.items()
                        },
                        approved_diff={
                            str(name): value for name, value in proposal.approved_diff.items()
                        },
                        parameter_fingerprint=proposal.parameter_fingerprint,
                        source_ids=proposal.source_ids,
                        metric_ids=proposal.metric_ids,
                        reason_codes=proposal.reason_codes,
                        executed_attempt_refs=executed,
                    )
                )
            for rejection in decision.rejected:
                summaries.append(
                    ProposalSummary(
                        round_index=round_index,
                        proposal_id=rejection.proposal.proposal_id,
                        disposition="REJECTED",
                        origin=rejection.proposal.origin,
                        requested_changes=dict(rejection.proposal.changes),
                        approved_diff=None,
                        parameter_fingerprint=None,
                        source_ids=rejection.proposal.source_ids,
                        metric_ids=rejection.proposal.metric_ids,
                        reason_codes=rejection.reason_codes,
                    )
                )
        return tuple(summaries)

    def _proposal_decisions(self) -> tuple[tuple[int, ProposalDecision], ...]:
        decisions: list[tuple[int, ProposalDecision]] = []
        for path in sorted((self.run_dir / "04_decisions").glob("round_*/proposal_decision.json")):
            try:
                round_index = int(path.parent.name.removeprefix("round_"))
                decision = ProposalDecision.model_validate_json(path.read_text())
            except (OSError, ValueError, ValidationError) as exc:
                raise AgentStateError(
                    f"Cannot collect current proposal report facts: {path}: {exc}"
                ) from exc
            decisions.append((round_index, decision))
        return tuple(decisions)

    def _round(self, relative_manifest: Path) -> RoundSummary:
        try:
            record = RoundRecord.model_validate_json((self.run_dir / relative_manifest).read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"Cannot collect current round report facts: {exc}") from exc
        return RoundSummary(
            round_index=record.round_index,
            round_ref=relative_manifest,
            incumbent_before_ref=(
                record.incumbent_before_ref.relative_path
                if record.incumbent_before_ref is not None
                else None
            ),
            incumbent_after_ref=(
                record.incumbent_after_ref.relative_path
                if record.incumbent_after_ref is not None
                else None
            ),
            outcome=record.round_outcome,
            stop_reason_codes=tuple(record.stop_reason_codes),
            comparison_ref=(
                record.comparison_ref.relative_path if record.comparison_ref is not None else None
            ),
            approved_candidate_count=len(record.approved_candidate_refs),
            rejected_candidate_count=len(record.rejected_candidate_refs),
            attempt_count=len(record.attempt_refs),
        )

    def _llm_activity(
        self,
        decisions: tuple[tuple[int, ProposalDecision], ...],
    ) -> tuple[LLMActivitySummary, ...]:
        activity: list[LLMActivitySummary] = []
        for round_index, decision in decisions:
            receipt = decision.llm_receipt
            activity.append(
                LLMActivitySummary(
                    round_index=round_index,
                    status=receipt.status,
                    provider=receipt.provider,
                    model=receipt.model,
                    call_id=receipt.call_id,
                    prompt_sha256=receipt.prompt_sha256,
                    output_sha256=receipt.output_sha256,
                    failure_reason=receipt.failure_reason,
                )
            )
        return tuple(activity)

    def _provenance_rows(self, history: HistoryManifest) -> list[list[str]]:
        references = [*history.attempt_refs, *history.round_refs]
        rows = [["role", "relative_path", "sha256"]]
        for reference in references:
            role = (
                "attempt_manifest"
                if reference.relative_path.name == "attempt_manifest.json"
                else "round_manifest"
            )
            rows.append([role, str(reference.relative_path), reference.sha256])
        for role, relative in (
            ("run_identity", Path("00_metadata/run_identity.json")),
            ("effective_config", Path("00_metadata/effective_config.json")),
            ("environment_manifest", Path("00_metadata/environment_manifest.json")),
            ("event_trace", Path("05_agent/event_trace.jsonl")),
            ("budget_ledger", Path("05_agent/budget_ledger.jsonl")),
        ):
            path = self.run_dir / relative
            rows.append([role, str(relative), sha256_file(path)])
        return rows


def _attempt_metrics(run_dir: Path, record: AssemblyAttemptRecord) -> AssemblyMetrics | None:
    if not record.comparison_eligible or record.artifacts_inventory_ref is None:
        return None
    inventory = ArtifactInventory.model_validate_json(
        (run_dir / record.artifacts_inventory_ref.relative_path).read_text()
    )
    matches = [
        entry
        for entry in inventory.entries
        if entry.relative_path == Path("post_qc/assembly_metrics.json")
    ]
    if len(matches) != 1:
        raise AgentStateError("Eligible attempt inventory lacks exactly one metrics artifact")
    attempt_root = run_dir / "02_assembly" / record.relative_directory()
    return AssemblyMetrics.model_validate_json(
        (attempt_root / matches[0].relative_path).read_text()
    )


def _report_metrics(metrics: AssemblyMetrics | None) -> dict[str, bool | int | float | str | None]:
    if metrics is None:
        return {}
    excluded = {
        "schema_id",
        "tool_failures",
        "metric_limitations",
        "metric_classes",
        "tool_versions",
        "tool_metadata",
        "source_files",
    }
    return {
        key: value
        for key, value in metrics.model_dump(mode="python").items()
        if key not in excluded and isinstance(value, bool | int | float | str | type(None))
    }


def _incumbent_chain(
    baseline_ref: Path | None,
    rounds: tuple[RoundSummary, ...],
) -> tuple[Path, ...]:
    chain = [baseline_ref] if baseline_ref is not None else []
    for round_summary in sorted(rounds, key=lambda item: item.round_index):
        after = round_summary.incumbent_after_ref
        if after is not None and (not chain or after != chain[-1]):
            chain.append(after)
    return tuple(chain)


def _render_markdown(summary: FinalSummary) -> str:
    lines = [
        "# HiFi Agent Final Report",
        "",
        f"- Sample: `{summary.sample_id}`",
        f"- Run UUID: `{summary.run_uuid}`",
        f"- Outcome: `{summary.terminal_outcome}`",
        f"- Outcome class: `{summary.outcome_class}`",
        f"- Selected run: `{summary.selected_run_ref or 'NOT_AVAILABLE'}`",
        f"- Verification: `{summary.verification_status}`",
        "",
        "## Incumbent evolution",
        "",
    ]
    lines.extend(
        f"{index}. `{reference}`" for index, reference in enumerate(summary.incumbent_chain)
    )
    lines.extend(["", "## Rounds", ""])
    if summary.rounds:
        lines.extend(
            f"- Round {item.round_index}: `{item.outcome}` "
            f"({', '.join(item.stop_reason_codes) or 'NONE'})"
            for item in summary.rounds
        )
    else:
        lines.append("- NOT_AVAILABLE")
    lines.extend(["", "## Candidate proposals", ""])
    if summary.proposals:
        for proposal in summary.proposals:
            execution = (
                ", ".join(str(item) for item in proposal.executed_attempt_refs) or "NOT_EXECUTED"
            )
            lines.append(
                f"- Round {proposal.round_index} `{proposal.proposal_id}`: "
                f"`{proposal.disposition}`; execution `{execution}`; reasons "
                f"`{','.join(proposal.reason_codes)}`"
            )
    else:
        lines.append("- No optimization proposal was produced.")
    lines.extend(["", "## Requested, approved, rendered, and realized parameters", ""])
    for attempt in summary.attempts:
        lines.extend(
            [
                f"### `{attempt.attempt_id}`",
                "",
                f"- Requested: `{_compact_json(attempt.requested_config)}`",
                f"- Approved: `{_compact_json(attempt.approved_parameters)}`",
                f"- Rendered argv: `{_compact_json(attempt.rendered_argv)}`",
                f"- Realized: `{_compact_json(attempt.realized_parameters)}`",
                "",
            ]
        )
    lines.extend(["", "## LLM activity and limits", ""])
    if summary.llm_activity:
        lines.extend(
            f"- Round {item.round_index}: `{item.status}`; "
            f"provider `{item.provider or 'NOT_CALLED'}`"
            for item in summary.llm_activity
        )
    else:
        lines.append("- LLM was not called and had no execution authority.")
    lines.extend(["", "## Budget reservations and actual consumption", ""])
    lines.extend(
        f"- {key} reserved: {value}" for key, value in sorted(summary.budget_reserved.items())
    )
    lines.extend(
        f"- {key} committed: {value}" for key, value in sorted(summary.budget_committed.items())
    )
    lines.extend(["", "## Scientific limitations", ""])
    lines.extend(f"- {item}" for item in summary.scientific_limitations)
    return "\n".join(lines) + "\n"


def _runs_rows(summary: FinalSummary) -> list[list[str]]:
    rows = [
        [
            "attempt_id",
            "attempt_ref",
            "round_index",
            "candidate_index",
            "status",
            "comparison_eligible",
            "selected",
            "metrics_json",
            "error",
        ]
    ]
    for item in summary.attempts:
        rows.append(
            [
                item.attempt_id,
                str(item.attempt_ref),
                str(item.round_index),
                "" if item.candidate_index is None else str(item.candidate_index),
                item.status,
                str(item.comparison_eligible).lower(),
                str(item.attempt_ref == summary.selected_run_ref).lower(),
                json.dumps(item.metrics, sort_keys=True, separators=(",", ":")),
                item.error or "",
            ]
        )
    return rows


def _parameter_rows(summary: FinalSummary) -> list[list[str]]:
    rows = [
        [
            "attempt_id",
            "parameter",
            "requested",
            "approved",
            "rendered_argv_json",
            "realized",
        ]
    ]
    for item in summary.attempts:
        requested_parameters = item.requested_config.get("parameters")
        requested = (
            requested_parameters
            if isinstance(requested_parameters, dict)
            else item.requested_config
        )
        for name in sorted(item.approved_parameters):
            realized = item.realized_parameters or {}
            rows.append(
                [
                    item.attempt_id,
                    name,
                    _cell(requested.get(name, "NOT_REQUESTED")),
                    _cell(item.approved_parameters[name]),
                    json.dumps(item.rendered_argv, separators=(",", ":")),
                    _cell(realized.get(name, "NOT_AVAILABLE")),
                ]
            )
    return rows


def _cell(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _compact_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)


def _atomic_tsv(path: Path, rows: list[list[str]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
