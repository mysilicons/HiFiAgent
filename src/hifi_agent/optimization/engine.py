"""Selection policy for a bounded set of Stage 11 candidates."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from hifi_agent.agent.models import AssemblyConfig
from hifi_agent.optimization.comparator import CORE_AUTO_SELECTION_METRICS, dominates
from hifi_agent.optimization.models import (
    CandidateAssessment,
    OptimizationOutcome,
    OptimizationResult,
)
from hifi_agent.rules.models import RuleDecision
from hifi_agent.schemas.metrics import AssemblyMetrics


def select_optimization_outcome(
    *,
    sample_id: str,
    run_dir: Path,
    baseline_config: AssemblyConfig,
    baseline_metrics: AssemblyMetrics,
    baseline_metrics_source: str,
    decision: RuleDecision,
    candidates: list[CandidateAssessment],
    optimization_round: int,
    max_retry_rounds: int,
    max_candidates_per_round: int,
    generated_at: datetime | None = None,
    synthetic: bool = False,
    scenario_id: str | None = None,
    scenario_disclaimer: str | None = None,
    source_sha256: dict[str, str] | None = None,
) -> OptimizationResult:
    """Apply dominance, conflict, acceptance, retry, and stop conditions."""
    _apply_cross_candidate_dominance(candidates)
    missing_baseline = [
        metric
        for metric in CORE_AUTO_SELECTION_METRICS
        if getattr(baseline_metrics, metric) is None
    ]
    if missing_baseline:
        outcome: OptimizationOutcome = "STOP_INSUFFICIENT_METRICS"
        selected = None
        reason = "Baseline lacks mandatory comparison metrics; automatic selection is unsafe."
    elif decision.decision == "BASELINE" and not candidates:
        outcome = "BASELINE_RETAINED"
        selected = baseline_metrics.run_id
        reason = "Deterministic rules accepted the baseline; no retry was authorized."
    elif decision.decision == "STOP" and not candidates:
        outcome = "STOP_RULE_DECISION"
        selected = None
        reason = "Deterministic expert rules prohibited automatic parameter optimization."
    elif any(candidate.status == "NOT_RUN" for candidate in candidates):
        outcome = "STOP_CONFIRMATION_REQUIRED"
        selected = None
        reason = "At least one authorized candidate requires confirmation before execution."
    elif any(candidate.status == "FAILED" for candidate in candidates):
        outcome = "STOP_EXECUTION_FAILURE"
        selected = None
        reason = "Candidate execution or the common post-QC workflow failed."
    elif any(candidate.conflicts for candidate in candidates):
        outcome = "STOP_METRIC_CONFLICT"
        selected = None
        reason = (
            "Candidate metrics improve in one direction but regress in protected quality "
            "dimensions; automatic selection stopped."
        )
    else:
        accepted = [candidate for candidate in candidates if candidate.status == "ACCEPTED"]
        if len(accepted) == 1:
            outcome = "ACCEPTED_CANDIDATE"
            selected = accepted[0].run_id
            reason = "One non-dominated candidate improved evidence without protected regressions."
        elif len(accepted) > 1:
            outcome = "STOP_METRIC_CONFLICT"
            selected = None
            reason = "Multiple non-dominated candidates have unresolved tradeoffs."
        elif optimization_round < max_retry_rounds:
            outcome = "RETRY"
            selected = None
            reason = "No candidate was acceptable and one bounded retry round remains."
        else:
            outcome = "STOP_RETRY_LIMIT"
            selected = None
            reason = "No candidate was acceptable and the optimization-round limit was reached."

    tradeoffs = [
        f"{candidate.run_id}: {item}" for candidate in candidates for item in candidate.tradeoffs
    ]
    if not tradeoffs:
        tradeoffs.append("No candidate tradeoff was available.")
    return OptimizationResult(
        generated_at=generated_at or datetime.now(UTC),
        sample_id=sample_id,
        run_dir=str(run_dir),
        optimization_round=optimization_round,
        max_retry_rounds=max_retry_rounds,
        max_candidates_per_round=max_candidates_per_round,
        baseline_config=baseline_config,
        baseline_metrics=baseline_metrics,
        baseline_metrics_source=baseline_metrics_source,
        triggering_decision=decision.model_dump(mode="json"),
        candidates=candidates,
        outcome=outcome,
        selected_run_id=selected,
        selection_reason=reason,
        selection_tradeoffs=tradeoffs,
        retained_run_ids=[baseline_metrics.run_id, *[item.run_id for item in candidates]],
        synthetic=synthetic,
        scenario_id=scenario_id,
        scenario_disclaimer=scenario_disclaimer,
        source_sha256=source_sha256 or {},
    )


def _apply_cross_candidate_dominance(candidates: list[CandidateAssessment]) -> None:
    for candidate in candidates:
        if candidate.status in {"FAILED", "NOT_RUN"}:
            continue
        dominating = [
            other.run_id
            for other in candidates
            if other.run_id != candidate.run_id
            and other.status not in {"FAILED", "NOT_RUN"}
            and dominates(other, candidate)
        ]
        if dominating:
            candidate.status = "DOMINATED"
            candidate.dominated_by = sorted({*candidate.dominated_by, *dominating})
