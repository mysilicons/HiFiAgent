"""Baseline review, round comparison, and incumbent advancement for current."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from hifi_agent.decision.context import DecisionContextStore, build_decision_context
from hifi_agent.decision.models import DecisionContext, ProposalDecision
from hifi_agent.exceptions import AgentStateError
from hifi_agent.executors.models import AttemptCoordinate
from hifi_agent.orchestration.budget import BudgetLedger
from hifi_agent.orchestration.comparison import (
    BaselineReview,
    RoundComparator,
    RoundComparison,
)
from hifi_agent.orchestration.coordinator_support import (
    append_unique,
    attempt_config,
    attempt_manifest_ref,
    attempt_metrics,
    build_or_verify_qc,
    latest_attempt,
    load_proposal_decision,
    previous_round_outcomes,
    proposal_stop,
    required_attempt,
    write_or_load_round,
    write_or_verify_json,
)
from hifi_agent.orchestration.journal import StateStore
from hifi_agent.orchestration.manifests import (
    ManifestReference,
    ManifestStore,
    RoundRecord,
)
from hifi_agent.orchestration.runtime_config import RuntimeConfigResult
from hifi_agent.orchestration.runtime_models import RunIdentity, RunPhase, RunState
from hifi_agent.schemas.metrics import AssemblyMetrics


class ReportingTransition(Protocol):
    """Port back to the authoritative state machine's reporting transition."""

    def __call__(
        self,
        state: RunState,
        *,
        outcome: str,
        outcome_class: str,
        reason_codes: list[str],
        last_error: str | None = None,
        updates: dict[str, object] | None = None,
    ) -> RunState:
        """Enter REPORTING with one terminal contract."""


class CoordinatorRounds:
    """Own scientific round artifacts while the coordinator owns phase ordering."""

    def __init__(
        self,
        *,
        transition_to_reporting: ReportingTransition,
        fault: Callable[[str, RunState], None],
    ) -> None:
        self.transition_to_reporting = transition_to_reporting
        self.fault = fault

    def review_baseline(
        self,
        state: RunState,
        *,
        runtime: RuntimeConfigResult,
        comparator: RoundComparator,
        manifests: ManifestStore,
    ) -> RunState:
        """Freeze baseline review and either stop or start round one."""
        run_dir = state.identity.run_dir
        baseline = required_attempt(run_dir, state.baseline_run_ref)
        review_path = run_dir / "04_decisions/round_00/baseline_review.json"
        if review_path.exists():
            review = BaselineReview.model_validate_json(review_path.read_text())
        else:
            review = comparator.review_baseline(
                attempt_metrics(run_dir, baseline),
                baseline_attempt_ref=attempt_manifest_ref(run_dir, baseline),
                reference_available=runtime.effective.sample.reference_genome is not None,
                trusted_genome_size=runtime.effective.sample.expected_genome_size is not None,
            )
            write_or_verify_json(review_path, review.model_dump(mode="json"))
        optimization = runtime.effective.optimization
        if not optimization.enabled:
            outcome = "ACCEPTED_BASELINE"
            round_outcome = "OPTIMIZATION_DISABLED"
            reasons = ["OPTIMIZATION_DISABLED_BY_CONFIG"]
        elif review.status == "ACCEPTED" and optimization.minimum_candidate_runs == 0:
            outcome = "ACCEPTED_BASELINE"
            round_outcome = "BASELINE_ACCEPTED"
            reasons = list(review.reason_codes)
        elif review.status == "INSUFFICIENT_EVIDENCE":
            outcome = "STOP_INSUFFICIENT_EVIDENCE"
            round_outcome = "BASELINE_INSUFFICIENT_EVIDENCE"
            reasons = list(review.reason_codes)
        elif optimization.max_rounds == 0:
            outcome = "STOP_MAX_ROUNDS"
            round_outcome = "NO_OPTIMIZATION_ROUNDS_CONFIGURED"
            reasons = ["MAX_ROUNDS_ZERO"]
        else:
            outcome = None
            if review.status == "ACCEPTED":
                round_outcome = "CONTROLLED_CANDIDATE_REQUIRED"
                reasons = ["MINIMUM_CANDIDATE_EVIDENCE_REQUIRED"]
            else:
                round_outcome = "OPTIMIZATION_REQUIRED"
                reasons = list(review.reason_codes)
        baseline_ref = attempt_manifest_ref(run_dir, baseline)
        round_path = write_or_load_round(
            run_dir,
            manifests,
            RoundRecord(
                round_id="round_00",
                round_index=0,
                incumbent_before_ref=ManifestReference.from_path(run_dir, run_dir / baseline_ref),
                attempt_refs=[ManifestReference.from_path(run_dir, run_dir / baseline_ref)],
                comparison_ref=ManifestReference.from_path(run_dir, review_path),
                incumbent_after_ref=ManifestReference.from_path(run_dir, run_dir / baseline_ref),
                round_outcome=round_outcome,
                stop_reason_codes=reasons,
                created_at=baseline.started_at,
                completed_at=datetime.now(UTC),
            ),
        )
        completed = append_unique(state.completed_round_refs, round_path.relative_to(run_dir))
        if outcome is not None:
            return self.transition_to_reporting(
                state,
                outcome=outcome,
                outcome_class="SCIENTIFIC",
                reason_codes=reasons,
                updates={"completed_round_refs": completed},
            )
        return StateStore(run_dir).transition(
            state,
            RunPhase.ROUND_CONTEXT,
            action="START_OPTIMIZATION_ROUND",
            reason_codes=reasons,
            updates={
                "round_index": 1,
                "candidate_index": None,
                "completed_round_refs": completed,
                "latest_decision_ref": review_path.relative_to(run_dir),
            },
        )

    def round_context(
        self,
        state: RunState,
        runtime: RuntimeConfigResult,
        identity: RunIdentity,
        comparator: RoundComparator,
        budget: BudgetLedger,
    ) -> DecisionContext:
        """Build the immutable context from the current incumbent, never baseline fallback."""
        run_dir = identity.run_dir
        path = run_dir / "04_decisions" / f"round_{state.round_index:02d}" / "decision_context.json"
        if path.exists():
            return DecisionContext.model_validate_json(path.read_text())
        incumbent = required_attempt(run_dir, state.incumbent_run_ref)
        config = attempt_config(run_dir, incumbent)
        metrics = attempt_metrics(run_dir, incumbent)
        qc = build_or_verify_qc(
            path.parent / "incumbent_qc_feature_bundle.json",
            run_dir,
            incumbent,
            runtime.effective.sample,
        )
        context = build_decision_context(
            run_uuid=identity.run_uuid,
            read_technology="pacbio_hifi",
            sample_facts={
                "sample_id": runtime.effective.sample.sample_id,
                "expected_genome_size": runtime.effective.sample.expected_genome_size,
                "reference_available": runtime.effective.sample.reference_genome is not None,
                "independent_kmer_reads": bool(runtime.effective.sample.kmer_reads),
                "minimum_candidate_runs": runtime.effective.optimization.minimum_candidate_runs,
            },
            qc_feature_bundle=qc,
            incumbent_attempt_manifest=run_dir / cast(Path, state.incumbent_run_ref),
            incumbent_attempt_ref=cast(Path, state.incumbent_run_ref),
            incumbent_config=config,
            incumbent_metrics=metrics,
            incumbent_metric_source_sha256=qc.source_sha256,
            round_index=state.round_index,
            seen_parameter_fingerprints=tuple(state.seen_parameter_fingerprints),
            comparison_policy_id=comparator.policy.policy_id,
            comparison_policy_sha256=comparator.policy_sha256,
            budget=budget.snapshot(),
            previous_round_outcomes=previous_round_outcomes(run_dir, state.completed_round_refs),
        )
        DecisionContextStore(run_dir).write(context)
        return context

    def compare_round(
        self,
        state: RunState,
        *,
        runtime: RuntimeConfigResult,
        comparator: RoundComparator,
        manifests: ManifestStore,
    ) -> RunState:
        """Compare all finalized candidates and freeze the incumbent transition."""
        run_dir = state.identity.run_dir
        decision = load_proposal_decision(run_dir, state.round_index)
        if not decision.approved:
            outcome, outcome_class, reasons = proposal_stop(decision)
            stop_path = (
                run_dir / "04_decisions" / f"round_{state.round_index:02d}" / "round_stop.json"
            )
            write_or_verify_json(
                stop_path,
                {
                    "schema_id": "hifi-agent",
                    "terminal_outcome": outcome,
                    "outcome_class": outcome_class,
                    "reason_codes": reasons,
                },
            )
            round_path = self.round_manifest(
                state,
                decision,
                manifests=manifests,
                comparison_path=stop_path,
                incumbent_after=cast(Path, state.incumbent_run_ref),
                round_outcome=outcome,
                reasons=reasons,
            )
            completed = append_unique(state.completed_round_refs, round_path.relative_to(run_dir))
            return self.transition_to_reporting(
                state,
                outcome=outcome,
                outcome_class=outcome_class,
                reason_codes=reasons,
                updates={"completed_round_refs": completed},
            )
        comparison_path = (
            run_dir / "04_decisions" / f"round_{state.round_index:02d}" / "comparison.json"
        )
        if comparison_path.exists():
            comparison = RoundComparison.model_validate_json(comparison_path.read_text())
        else:
            candidates: list[tuple[int, Path, AssemblyMetrics]] = []
            failed: list[tuple[int, Path, tuple[str, ...]]] = []
            for index in range(1, len(decision.approved) + 1):
                coordinate = AttemptCoordinate(
                    round_index=state.round_index,
                    candidate_index=index,
                )
                record = latest_attempt(run_dir, coordinate)
                if record is None:
                    raise AgentStateError("Round comparison found no finalized candidate attempt")
                reference = attempt_manifest_ref(run_dir, record)
                if record.comparison_eligible:
                    candidates.append((index, reference, attempt_metrics(run_dir, record)))
                else:
                    failed.append((index, reference, tuple(record.ineligible_reason_codes)))
            incumbent = required_attempt(run_dir, state.incumbent_run_ref)
            self.fault("before_round_comparison", state)
            comparison = comparator.compare(
                round_index=state.round_index,
                incumbent_attempt_ref=cast(Path, state.incumbent_run_ref),
                incumbent_metrics=attempt_metrics(run_dir, incumbent),
                candidates=tuple(candidates),
                failed_candidates=tuple(failed),
                reference_available=runtime.effective.sample.reference_genome is not None,
                trusted_genome_size=runtime.effective.sample.expected_genome_size is not None,
            )
            write_or_verify_json(comparison_path, comparison.model_dump(mode="json"))
            self.fault("after_round_comparison", state)
        incumbent_after = comparison.selected_attempt_ref or cast(Path, state.incumbent_run_ref)
        round_path = self.round_manifest(
            state,
            decision,
            manifests=manifests,
            comparison_path=comparison_path,
            incumbent_after=incumbent_after,
            round_outcome=comparison.outcome,
            reasons=list(comparison.reason_codes),
        )
        completed = append_unique(state.completed_round_refs, round_path.relative_to(run_dir))
        return StateStore(run_dir).transition(
            state,
            RunPhase.INCUMBENT_UPDATE,
            action="COMMIT_ROUND_COMPARISON",
            reason_codes=list(comparison.reason_codes),
            updates={
                "incumbent_run_ref": incumbent_after,
                "completed_round_refs": completed,
                "latest_decision_ref": comparison_path.relative_to(run_dir),
            },
        )

    def round_manifest(
        self,
        state: RunState,
        decision: ProposalDecision,
        *,
        manifests: ManifestStore,
        comparison_path: Path,
        incumbent_after: Path,
        round_outcome: str,
        reasons: list[str],
    ) -> Path:
        """Bind all round decision and attempt evidence into one immutable manifest."""
        run_dir = state.identity.run_dir
        round_dir = run_dir / "04_decisions" / f"round_{state.round_index:02d}"
        attempts = sorted(
            (run_dir / "02_assembly" / f"round_{state.round_index:02d}").glob(
                "candidate_*/attempt_*/attempt_manifest.json"
            )
        )
        context_path = round_dir / "decision_context.json"
        rule_path = round_dir / "rule_directive.json"
        retrieval_path = round_dir / "retrieval_trace.json"
        proposal_path = round_dir / "proposal_decision.json"
        receipt_path = round_dir / "llm_call_receipt.json"
        raw_response_path = round_dir / "proposals/raw_llm_response.json"
        created_at = DecisionContext.model_validate_json(context_path.read_text()).created_at
        return write_or_load_round(
            run_dir,
            manifests,
            RoundRecord(
                round_id=f"round_{state.round_index:02d}",
                round_index=state.round_index,
                incumbent_before_ref=ManifestReference.from_path(
                    run_dir, run_dir / cast(Path, state.incumbent_run_ref)
                ),
                decision_context_ref=ManifestReference.from_path(run_dir, context_path),
                rule_decision_ref=ManifestReference.from_path(run_dir, rule_path),
                retrieval_trace_ref=(
                    ManifestReference.from_path(run_dir, retrieval_path)
                    if retrieval_path.exists()
                    else None
                ),
                proposal_decision_ref=ManifestReference.from_path(run_dir, proposal_path),
                llm_call_receipt_ref=(
                    ManifestReference.from_path(run_dir, receipt_path)
                    if receipt_path.exists()
                    else None
                ),
                llm_raw_response_ref=(
                    ManifestReference.from_path(run_dir, raw_response_path)
                    if raw_response_path.exists()
                    else None
                ),
                raw_candidate_refs=[
                    ManifestReference.from_path(run_dir, run_dir / reference)
                    for reference in decision.raw_proposal_refs
                ],
                approved_candidate_refs=[
                    ManifestReference.from_path(run_dir, run_dir / reference)
                    for reference in decision.approved_proposal_refs
                ],
                rejected_candidate_refs=[
                    ManifestReference.from_path(run_dir, run_dir / reference)
                    for reference in decision.rejected_proposal_refs
                ],
                attempt_refs=[ManifestReference.from_path(run_dir, path) for path in attempts],
                comparison_ref=ManifestReference.from_path(run_dir, comparison_path),
                incumbent_after_ref=ManifestReference.from_path(run_dir, run_dir / incumbent_after),
                round_outcome=round_outcome,
                stop_reason_codes=reasons,
                created_at=created_at,
                completed_at=datetime.now(UTC),
            ),
        )

    def after_incumbent_update(
        self,
        state: RunState,
        runtime: RuntimeConfigResult,
    ) -> RunState:
        """Advance an accepted incumbent or stop on the comparison outcome."""
        run_dir = state.identity.run_dir
        comparison = RoundComparison.model_validate_json(
            (
                run_dir / "04_decisions" / f"round_{state.round_index:02d}" / "comparison.json"
            ).read_text()
        )
        if comparison.outcome == "ACCEPT_CANDIDATE":
            if state.round_index >= runtime.effective.optimization.max_rounds:
                return self.transition_to_reporting(
                    state,
                    outcome="STOP_MAX_ROUNDS",
                    outcome_class="SCIENTIFIC",
                    reason_codes=["CONFIGURED_MAX_ROUNDS_COMPLETED"],
                )
            return StateStore(run_dir).transition(
                state,
                RunPhase.ROUND_CONTEXT,
                action="ADVANCE_CURRENT_INCUMBENT",
                reason_codes=["CANDIDATE_ACCEPTED_AS_NEW_INCUMBENT"],
                updates={
                    "round_index": state.round_index + 1,
                    "candidate_index": None,
                    "latest_decision_ref": None,
                },
            )
        outcomes = {
            "KEEP_INCUMBENT": (
                "STOP_PLATEAU",
                "SCIENTIFIC",
                ["PLATEAU_AFTER_NON_IMPROVING_ROUND"],
            ),
            "HUMAN_REVIEW": (
                "STOP_HUMAN_REVIEW",
                "ACTION_REQUIRED",
                list(comparison.reason_codes),
            ),
            "INSUFFICIENT_EVIDENCE": (
                "STOP_INSUFFICIENT_EVIDENCE",
                "SCIENTIFIC",
                list(comparison.reason_codes),
            ),
        }
        outcome, outcome_class, reasons = outcomes.get(
            comparison.outcome,
            ("FAILED_TOOL", "FAILED", list(comparison.reason_codes)),
        )
        return self.transition_to_reporting(
            state,
            outcome=outcome,
            outcome_class=outcome_class,
            reason_codes=reasons,
        )
