"""Stage 8 incumbent-based comparison, Pareto selection, and audit artifacts."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from hifi_agent.optimization.policy import (
    ComparisonMetricPolicy,
    ComparisonPolicy,
    load_comparison_policy,
)
from hifi_agent.optimization.round_models import (
    ComparableRun,
    MetricResult,
    RoundCandidateAssessment,
    RoundCandidateStatus,
    RoundComparison,
    RoundComparisonContext,
    RoundMetricDifference,
    RoundOutcome,
    RoundParameterDifference,
)


class RoundComparator:
    """Compare up to two candidates against any current incumbent."""

    def __init__(self, policy: ComparisonPolicy | None = None) -> None:
        self.policy = policy or load_comparison_policy()

    def compare_round(
        self,
        *,
        round_index: int,
        incumbent: ComparableRun,
        candidates: list[ComparableRun],
        context: RoundComparisonContext,
        output_dir: Path | None = None,
        generated_at: datetime | None = None,
    ) -> RoundComparison:
        """Classify, apply Pareto dominance, select, and optionally persist one round."""
        if not 1 <= len(candidates) <= 2:
            raise ValueError("Stage 8 comparison requires one or two candidates")
        assessments = [
            self._assess(incumbent=incumbent, candidate=item, context=context)
            for item in candidates
        ]
        self._apply_candidate_dominance(assessments)
        comparison = self._select(
            round_index=round_index,
            incumbent=incumbent,
            assessments=assessments,
            context=context,
            generated_at=generated_at or datetime.now(UTC),
        )
        if output_dir is not None:
            _write_round_artifacts(comparison, output_dir)
        return comparison

    def _assess(
        self,
        *,
        incumbent: ComparableRun,
        candidate: ComparableRun,
        context: RoundComparisonContext,
    ) -> RoundCandidateAssessment:
        parameters = _parameter_differences(incumbent, candidate)
        if candidate.execution_status != "COMPLETED" or candidate.metrics is None:
            return RoundCandidateAssessment(
                run_id=candidate.run_id,
                attempt_id=candidate.attempt_id,
                status="EXECUTION_FAILURE",
                parameter_differences=parameters,
                metric_differences=[],
                tradeoffs=["candidate execution or post-QC did not complete"],
            )
        if candidate.parameter_contract_status != "PASS":
            return RoundCandidateAssessment(
                run_id=candidate.run_id,
                attempt_id=candidate.attempt_id,
                status="INVALID_CONTRACT",
                parameter_differences=parameters,
                metric_differences=[],
                tradeoffs=[
                    "candidate excluded because requested/approved/rendered/realized "
                    "parameter contract did not pass"
                ],
            )
        if incumbent.metrics is None:
            raise ValueError("Completed incumbent requires assembly metrics")

        differences = [
            _metric_difference(
                metric,
                spec,
                incumbent.metrics,
                candidate.metrics,
                context,
            )
            for metric, spec in self.policy.metrics.items()
        ]
        material_improvements = [
            item.metric for item in differences if item.result == "IMPROVED" and item.material
        ]
        material_regressions = [
            item.metric for item in differences if item.result == "REGRESSED" and item.material
        ]
        unavailable = [
            item.metric
            for item in differences
            if item.result == "UNAVAILABLE" and self.policy.metrics[item.metric].required
        ]
        hard = [
            item.metric for item in differences if item.protected and item.result == "REGRESSED"
        ]
        acceptance = _acceptance_failures(
            incumbent.metrics,
            candidate.metrics,
            self.policy,
        )

        if unavailable:
            status: RoundCandidateStatus = "UNAVAILABLE"
        elif hard:
            status = "HARD_REGRESSION"
        elif acceptance:
            status = "ACCEPTANCE_FAILURE"
        elif material_improvements and material_regressions:
            status = "TRADEOFF"
        elif material_improvements:
            status = "ELIGIBLE"
        elif material_regressions:
            status = "DOMINATED"
        else:
            status = "PLATEAU"
        tradeoffs = [
            f"{item.metric}: {item.result} ({item.incumbent_value} -> {item.candidate_value})"
            for item in differences
            if item.result not in {"UNCHANGED", "NOT_APPLICABLE", "UNAVAILABLE"}
        ]
        tradeoffs.extend(f"hard regression: {metric}" for metric in hard)
        tradeoffs.extend(f"acceptance failure: {code}" for code in acceptance)
        if unavailable:
            tradeoffs.append(f"unavailable core metrics: {', '.join(sorted(unavailable))}")
        return RoundCandidateAssessment(
            run_id=candidate.run_id,
            attempt_id=candidate.attempt_id,
            status=status,
            parameter_differences=parameters,
            metric_differences=differences,
            material_improvements=material_improvements,
            material_regressions=material_regressions,
            hard_regressions=hard,
            acceptance_failures=acceptance,
            unavailable_metrics=unavailable,
            tradeoffs=tradeoffs,
        )

    def _apply_candidate_dominance(
        self,
        assessments: list[RoundCandidateAssessment],
    ) -> None:
        comparable_statuses = {"ELIGIBLE", "PLATEAU", "TRADEOFF", "DOMINATED"}
        for candidate in assessments:
            if candidate.status not in comparable_statuses:
                continue
            dominating = [
                other.run_id
                for other in assessments
                if other.run_id != candidate.run_id
                and other.status in comparable_statuses
                and _dominates(other, candidate, self.policy)
            ]
            if dominating:
                candidate.status = "DOMINATED"
                candidate.dominated_by = sorted(dominating)

    def _select(
        self,
        *,
        round_index: int,
        incumbent: ComparableRun,
        assessments: list[RoundCandidateAssessment],
        context: RoundComparisonContext,
        generated_at: datetime,
    ) -> RoundComparison:
        if any(item.status == "EXECUTION_FAILURE" for item in assessments):
            outcome: RoundOutcome = "STOP_EXECUTION_FAILURE"
            reason_codes = ["CANDIDATE_EXECUTION_OR_POST_QC_FAILED"]
            nondominated: list[RoundCandidateAssessment] = []
        elif any(item.status == "UNAVAILABLE" for item in assessments):
            outcome = "STOP_INSUFFICIENT_METRICS"
            reason_codes = ["CORE_COMPARISON_METRICS_UNAVAILABLE"]
            nondominated = []
        else:
            nondominated = [
                item
                for item in assessments
                if item.status in {"ELIGIBLE", "PLATEAU", "TRADEOFF"} and not item.dominated_by
            ]
            eligible = [item for item in nondominated if item.status == "ELIGIBLE"]
            if len(nondominated) == 1 and len(eligible) == 1:
                outcome = "INCUMBENT_UPDATED"
                reason_codes = ["UNIQUE_NONDOMINATED_MATERIAL_IMPROVEMENT"]
            elif nondominated and all(item.status == "PLATEAU" for item in nondominated):
                outcome = "STOP_PLATEAU"
                reason_codes = ["NO_METRIC_EXCEEDED_MATERIAL_THRESHOLD"]
            elif len(nondominated) > 1:
                outcome = "STOP_CONFLICT"
                reason_codes = ["MULTIPLE_NONDOMINATED_TRADEOFFS"]
            elif any(item.status == "TRADEOFF" for item in nondominated):
                outcome = "STOP_CONFLICT"
                reason_codes = ["UNRESOLVED_MATERIAL_TRADEOFF"]
            elif all(item.status == "PLATEAU" for item in assessments):
                outcome = "STOP_PLATEAU"
                reason_codes = ["NO_METRIC_EXCEEDED_MATERIAL_THRESHOLD"]
            else:
                outcome = "NO_UNIQUE_CANDIDATE"
                reason_codes = ["NO_SAFE_MATERIAL_IMPROVEMENT"]

        selected = (
            nondominated[0].run_id
            if outcome == "INCUMBENT_UPDATED" and len(nondominated) == 1
            else None
        )
        return RoundComparison(
            policy_version=self.policy.policy_version,
            generated_at=generated_at,
            round_index=round_index,
            incumbent_before=incumbent.run_id,
            incumbent_after=selected or incumbent.run_id,
            context=context,
            candidates=assessments,
            nondominated_run_ids=[item.run_id for item in nondominated],
            outcome=outcome,
            selected_run_id=selected,
            reason_codes=reason_codes,
        )


def _metric_difference(
    metric: str,
    spec: ComparisonMetricPolicy,
    incumbent: object,
    candidate: object,
    context: RoundComparisonContext,
) -> RoundMetricDifference:
    incumbent_value = getattr(incumbent, metric)
    candidate_value = getattr(candidate, metric)
    if spec.applicability == "reference" and not context.reference_available:
        return _unavailable_difference(
            metric,
            spec,
            incumbent_value,
            candidate_value,
            "NOT_APPLICABLE",
            "reference-free evaluation excludes reference-based structural error",
        )
    if spec.applicability == "trusted_genome_size" and not context.genome_size_trusted:
        return _unavailable_difference(
            metric,
            spec,
            incumbent_value,
            candidate_value,
            "NOT_APPLICABLE",
            "untrusted genome size excludes assembly-size ratio from automatic selection",
        )
    if incumbent_value is None or candidate_value is None:
        return _unavailable_difference(
            metric,
            spec,
            incumbent_value,
            candidate_value,
            "UNAVAILABLE",
            "metric missing from incumbent or candidate",
        )
    left = float(incumbent_value)
    right = float(candidate_value)
    relation = _relation(right, left, spec.direction)
    result: MetricResult = (
        "IMPROVED" if relation > 0 else "REGRESSED" if relation < 0 else "UNCHANGED"
    )
    material = _threshold_crossed(left, right, spec.material_delta, spec.material_mode)
    protected = (
        result == "REGRESSED"
        and spec.hard_regression_delta is not None
        and _regression_amount(left, right, spec.direction, spec.hard_regression_mode)
        > spec.hard_regression_delta
    )
    return RoundMetricDifference(
        metric=metric,
        direction=spec.direction,
        incumbent_value=incumbent_value,
        candidate_value=candidate_value,
        delta=right - left,
        result=result,
        material=material,
        protected=protected,
        reason=spec.note,
    )


def _unavailable_difference(
    metric: str,
    spec: ComparisonMetricPolicy,
    incumbent_value: int | float | None,
    candidate_value: int | float | None,
    result: MetricResult,
    reason: str,
) -> RoundMetricDifference:
    return RoundMetricDifference(
        metric=metric,
        direction=spec.direction,
        incumbent_value=incumbent_value,
        candidate_value=candidate_value,
        delta=None,
        result=result,
        reason=reason,
    )


def _relation(candidate: float, incumbent: float, direction: str) -> int:
    if direction == "target_one":
        candidate_distance = abs(candidate - 1.0)
        incumbent_distance = abs(incumbent - 1.0)
        return (candidate_distance < incumbent_distance) - (candidate_distance > incumbent_distance)
    if direction == "higher":
        return (candidate > incumbent) - (candidate < incumbent)
    return (candidate < incumbent) - (candidate > incumbent)


def _threshold_crossed(
    incumbent: float,
    candidate: float,
    threshold: float,
    mode: str,
) -> bool:
    if mode == "relative":
        return abs(candidate - incumbent) / max(abs(incumbent), 1.0) >= threshold
    return abs(candidate - incumbent) >= threshold


def _regression_amount(
    incumbent: float,
    candidate: float,
    direction: str,
    mode: str,
) -> float:
    if direction == "higher":
        raw = incumbent - candidate
    elif direction == "lower":
        raw = candidate - incumbent
    else:
        raw = abs(candidate - 1.0) - abs(incumbent - 1.0)
    if mode == "relative":
        return raw / max(abs(incumbent), 1.0)
    return raw


def _acceptance_failures(
    incumbent: object,
    candidate: object,
    policy: ComparisonPolicy,
) -> list[str]:
    failures: list[str] = []
    for metric, spec in policy.metrics.items():
        incumbent_value = getattr(incumbent, metric)
        value = getattr(candidate, metric)
        if value is None:
            continue
        changed = incumbent_value is None or value != incumbent_value
        if changed and spec.acceptance_min is not None and value < spec.acceptance_min:
            failures.append(f"{metric.upper()}_BELOW_ACCEPTANCE_MIN")
        if changed and spec.acceptance_max is not None and value > spec.acceptance_max:
            failures.append(f"{metric.upper()}_ABOVE_ACCEPTANCE_MAX")
    return failures


def _parameter_differences(
    incumbent: ComparableRun,
    candidate: ComparableRun,
) -> list[RoundParameterDifference]:
    incumbent_values = incumbent.config.parameters.model_dump(mode="json")
    candidate_values = candidate.config.parameters.model_dump(mode="json")
    return [
        RoundParameterDifference(
            parameter=name,
            incumbent_value=incumbent_values[name],
            candidate_value=value,
        )
        for name, value in candidate_values.items()
        if incumbent_values[name] != value
    ]


def _dominates(
    first: RoundCandidateAssessment,
    second: RoundCandidateAssessment,
    policy: ComparisonPolicy,
) -> bool:
    first_metrics = {item.metric: item for item in first.metric_differences}
    second_metrics = {item.metric: item for item in second.metric_differences}
    no_worse = True
    better = False
    for metric, spec in policy.metrics.items():
        left = first_metrics[metric]
        right = second_metrics[metric]
        if (
            left.result in {"UNAVAILABLE", "NOT_APPLICABLE"}
            or right.result in {"UNAVAILABLE", "NOT_APPLICABLE"}
            or left.candidate_value is None
            or right.candidate_value is None
        ):
            continue
        relation = _relation(
            float(left.candidate_value),
            float(right.candidate_value),
            spec.direction,
        )
        if relation < 0:
            no_worse = False
            break
        if relation > 0:
            better = True
    return no_worse and better


def _write_round_artifacts(comparison: RoundComparison, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "round_comparison.json"
    tsv_path = output_dir / "round_comparison.tsv"
    parameters_path = output_dir / "parameter_diff.tsv"
    tradeoffs_path = output_dir / "selection_tradeoffs.md"
    comparison.comparison_json = json_path
    comparison.comparison_tsv = tsv_path
    comparison.parameter_diff_tsv = parameters_path
    comparison.selection_tradeoffs_md = tradeoffs_path
    json_path.write_text(comparison.model_dump_json(indent=2) + "\n")
    _write_comparison_tsv(comparison, tsv_path)
    _write_parameter_tsv(comparison, parameters_path)
    _write_tradeoffs(comparison, tradeoffs_path)


def _write_comparison_tsv(comparison: RoundComparison, path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            [
                "run_id",
                "attempt_id",
                "status",
                "metric",
                "incumbent_value",
                "candidate_value",
                "result",
                "material",
                "protected",
            ]
        )
        for candidate in comparison.candidates:
            for metric in candidate.metric_differences:
                writer.writerow(
                    [
                        candidate.run_id,
                        candidate.attempt_id,
                        candidate.status,
                        metric.metric,
                        _cell(metric.incumbent_value),
                        _cell(metric.candidate_value),
                        metric.result,
                        str(metric.material).lower(),
                        str(metric.protected).lower(),
                    ]
                )


def _write_parameter_tsv(comparison: RoundComparison, path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["run_id", "parameter", "incumbent_value", "candidate_value"])
        for candidate in comparison.candidates:
            for parameter in candidate.parameter_differences:
                writer.writerow(
                    [
                        candidate.run_id,
                        parameter.parameter,
                        _cell(parameter.incumbent_value),
                        _cell(parameter.candidate_value),
                    ]
                )


def _write_tradeoffs(comparison: RoundComparison, path: Path) -> None:
    lines = [
        f"# Round {comparison.round_index} selection tradeoffs",
        "",
        f"- Policy: `{comparison.policy_version}`",
        f"- Incumbent before: `{comparison.incumbent_before}`",
        f"- Outcome: **{comparison.outcome}**",
        f"- Incumbent after: `{comparison.incumbent_after}`",
        f"- Reason codes: {', '.join(comparison.reason_codes)}",
        "",
    ]
    for candidate in comparison.candidates:
        lines.extend(
            [
                f"## {candidate.run_id} / {candidate.attempt_id}",
                "",
                f"- Status: **{candidate.status}**",
                f"- Dominated by: {', '.join(candidate.dominated_by) or 'none'}",
                *[f"- {item}" for item in candidate.tradeoffs],
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n")


def _cell(value: object) -> object:
    return "" if value is None else value
