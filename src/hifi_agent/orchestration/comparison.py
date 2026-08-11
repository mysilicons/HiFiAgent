"""Production multi-metric comparison with protected scientific regressions."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hifi_agent.exceptions import AgentStateError
from hifi_agent.orchestration.runtime_models import sha256_file
from hifi_agent.schemas.metrics import AssemblyMetrics

MetricDirection = Literal["higher", "lower", "target_one"]
MetricAssessment = Literal[
    "IMPROVED",
    "UNCHANGED",
    "REGRESSED",
    "HARD_REGRESSION",
    "NOT_APPLICABLE",
    "MISSING",
]


class MetricPolicy(BaseModel):
    """One immutable comparison rule loaded from the frozen current policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: MetricDirection
    material_delta: float = Field(ge=0.0)
    material_mode: Literal["absolute", "relative"] = "absolute"
    required: bool
    applicability: Literal["always", "reference", "trusted_genome_size"] = "always"
    hard_regression_delta: float | None = Field(default=None, ge=0.0)
    hard_regression_mode: Literal["absolute", "relative"] = "absolute"
    acceptance_min: float | None = None
    note: str


class ComparisonPolicy(BaseModel):
    """Frozen policy used for baseline acceptance and every candidate comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    policy_id: str
    metrics: dict[str, MetricPolicy]


class BaselineReview(BaseModel):
    """Deterministic decision on whether optimization should start."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    status: Literal["ACCEPTED", "OPTIMIZATION_REQUIRED", "INSUFFICIENT_EVIDENCE"]
    baseline_attempt_ref: Path
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checked_metric_ids: tuple[str, ...]
    missing_required_metric_ids: tuple[str, ...] = ()
    below_acceptance_metric_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("baseline_attempt_ref")
    @classmethod
    def safe_ref(cls, value: Path) -> Path:
        """Reject absolute or parent-traversing baseline references."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("baseline attempt reference must be run-relative")
        return value


class MetricComparison(BaseModel):
    """One candidate/incumbent metric comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    incumbent_value: float | int | None
    candidate_value: float | int | None
    direction: MetricDirection
    assessment: MetricAssessment
    oriented_delta: float | None = None
    material_threshold: float | None = None
    hard_regression_threshold: float | None = None
    reason_codes: tuple[str, ...] = Field(min_length=1)


class CandidateComparison(BaseModel):
    """Complete scientific comparison for one finalized candidate attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_index: int = Field(ge=1, le=2)
    candidate_attempt_ref: Path
    comparison_eligible: bool
    metrics: tuple[MetricComparison, ...]
    improved_metric_ids: tuple[str, ...] = ()
    regressed_metric_ids: tuple[str, ...] = ()
    hard_regression_metric_ids: tuple[str, ...] = ()
    missing_required_metric_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("candidate_attempt_ref")
    @classmethod
    def safe_ref(cls, value: Path) -> Path:
        """Reject absolute or parent-traversing candidate references."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("candidate attempt reference must be run-relative")
        return value


class RoundComparison(BaseModel):
    """Immutable round decision used to update the single incumbent chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    round_index: int = Field(ge=1, le=3)
    incumbent_before_ref: Path
    policy_id: str
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal[
        "ACCEPT_CANDIDATE",
        "KEEP_INCUMBENT",
        "HUMAN_REVIEW",
        "INSUFFICIENT_EVIDENCE",
        "ALL_CANDIDATES_FAILED",
    ]
    selected_attempt_ref: Path | None = None
    candidates: tuple[CandidateComparison, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("incumbent_before_ref", "selected_attempt_ref")
    @classmethod
    def safe_ref(cls, value: Path | None) -> Path | None:
        """Reject comparison references outside the current run root."""
        if value is not None and (value.is_absolute() or ".." in value.parts):
            raise ValueError("comparison references must be run-relative")
        return value


def load_comparison_policy(path: Path) -> ComparisonPolicy:
    """Load the immutable production comparison policy."""
    try:
        payload = yaml.safe_load(path.read_text())
        return ComparisonPolicy.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise AgentStateError(f"current comparison policy is invalid: {exc}") from exc


class RoundComparator:
    """Apply protected regressions, material deltas, and Pareto conflict handling."""

    def __init__(self, policy_path: Path) -> None:
        self.policy_path = policy_path.resolve()
        self.policy = load_comparison_policy(self.policy_path)
        self.policy_sha256 = sha256_file(self.policy_path)

    def review_baseline(
        self,
        metrics: AssemblyMetrics,
        *,
        baseline_attempt_ref: Path,
        reference_available: bool,
        trusted_genome_size: bool,
    ) -> BaselineReview:
        """Accept only complete baselines that satisfy every declared acceptance floor."""
        checked: list[str] = []
        missing: list[str] = []
        below: list[str] = []
        for metric_id, specification in self.policy.metrics.items():
            if not _applicable(
                specification,
                reference_available=reference_available,
                trusted_genome_size=trusted_genome_size,
            ):
                continue
            value = _numeric(getattr(metrics, metric_id, None))
            if specification.required:
                checked.append(metric_id)
                if value is None:
                    missing.append(metric_id)
                    continue
            if specification.acceptance_min is not None and (
                value is None or value < specification.acceptance_min
            ):
                below.append(metric_id)
        status: Literal["ACCEPTED", "OPTIMIZATION_REQUIRED", "INSUFFICIENT_EVIDENCE"]
        if missing:
            status = "INSUFFICIENT_EVIDENCE"
            reasons = ("BASELINE_REQUIRED_METRICS_MISSING",)
        elif below:
            status = "OPTIMIZATION_REQUIRED"
            reasons = ("BASELINE_ACCEPTANCE_FLOOR_NOT_MET",)
        else:
            status = "ACCEPTED"
            reasons = ("BASELINE_QUALITY_FLOORS_MET",)
        return BaselineReview(
            status=status,
            baseline_attempt_ref=baseline_attempt_ref,
            policy_sha256=self.policy_sha256,
            checked_metric_ids=tuple(checked),
            missing_required_metric_ids=tuple(sorted(missing)),
            below_acceptance_metric_ids=tuple(sorted(below)),
            reason_codes=reasons,
        )

    def compare(
        self,
        *,
        round_index: int,
        incumbent_attempt_ref: Path,
        incumbent_metrics: AssemblyMetrics,
        candidates: tuple[tuple[int, Path, AssemblyMetrics], ...],
        failed_candidates: tuple[tuple[int, Path, tuple[str, ...]], ...] = (),
        reference_available: bool,
        trusted_genome_size: bool,
    ) -> RoundComparison:
        """Select one unique protected improvement or stop without unsafe ranking."""
        assessed = [
            self._compare_candidate(
                candidate_index=index,
                candidate_attempt_ref=reference,
                incumbent=incumbent_metrics,
                candidate=metrics,
                reference_available=reference_available,
                trusted_genome_size=trusted_genome_size,
            )
            for index, reference, metrics in candidates
        ]
        assessed.extend(
            CandidateComparison(
                candidate_index=index,
                candidate_attempt_ref=reference,
                comparison_eligible=False,
                metrics=(),
                reason_codes=reason_codes or ("CANDIDATE_EXECUTION_FAILED",),
            )
            for index, reference, reason_codes in failed_candidates
        )
        assessed.sort(key=lambda item: item.candidate_index)
        if not candidates:
            return self._round(
                round_index,
                incumbent_attempt_ref,
                "ALL_CANDIDATES_FAILED",
                tuple(assessed),
                None,
                ("ALL_CANDIDATE_ATTEMPTS_INELIGIBLE",),
            )
        if any(item.missing_required_metric_ids for item in assessed):
            return self._round(
                round_index,
                incumbent_attempt_ref,
                "INSUFFICIENT_EVIDENCE",
                tuple(assessed),
                None,
                ("COMPARISON_REQUIRED_METRICS_MISSING",),
            )
        viable = [
            item
            for item in assessed
            if item.comparison_eligible
            and item.improved_metric_ids
            and not item.regressed_metric_ids
            and not item.hard_regression_metric_ids
        ]
        if not viable:
            return self._round(
                round_index,
                incumbent_attempt_ref,
                "KEEP_INCUMBENT",
                tuple(assessed),
                incumbent_attempt_ref,
                ("NO_PROTECTED_MATERIAL_IMPROVEMENT",),
            )
        if len(viable) == 1:
            return self._round(
                round_index,
                incumbent_attempt_ref,
                "ACCEPT_CANDIDATE",
                tuple(assessed),
                viable[0].candidate_attempt_ref,
                ("UNIQUE_PROTECTED_IMPROVEMENT",),
            )
        dominant = [
            candidate
            for candidate in viable
            if all(
                candidate is other
                or _dominates(
                    _metrics_for_ref(candidates, candidate.candidate_attempt_ref),
                    _metrics_for_ref(candidates, other.candidate_attempt_ref),
                    self.policy,
                    reference_available=reference_available,
                    trusted_genome_size=trusted_genome_size,
                )
                for other in viable
            )
        ]
        if len(dominant) == 1:
            return self._round(
                round_index,
                incumbent_attempt_ref,
                "ACCEPT_CANDIDATE",
                tuple(assessed),
                dominant[0].candidate_attempt_ref,
                ("UNIQUE_PARETO_DOMINANT_CANDIDATE",),
            )
        return self._round(
            round_index,
            incumbent_attempt_ref,
            "HUMAN_REVIEW",
            tuple(assessed),
            None,
            ("PARETO_METRIC_CONFLICT",),
        )

    def _compare_candidate(
        self,
        *,
        candidate_index: int,
        candidate_attempt_ref: Path,
        incumbent: AssemblyMetrics,
        candidate: AssemblyMetrics,
        reference_available: bool,
        trusted_genome_size: bool,
    ) -> CandidateComparison:
        comparisons: list[MetricComparison] = []
        improved: list[str] = []
        regressed: list[str] = []
        hard: list[str] = []
        missing: list[str] = []
        for metric_id, specification in self.policy.metrics.items():
            result = _compare_metric(
                metric_id,
                specification,
                incumbent=_numeric(getattr(incumbent, metric_id, None)),
                candidate=_numeric(getattr(candidate, metric_id, None)),
                reference_available=reference_available,
                trusted_genome_size=trusted_genome_size,
            )
            comparisons.append(result)
            if result.assessment == "IMPROVED":
                improved.append(metric_id)
            elif result.assessment == "REGRESSED":
                regressed.append(metric_id)
            elif result.assessment == "HARD_REGRESSION":
                hard.append(metric_id)
            elif result.assessment == "MISSING" and specification.required:
                missing.append(metric_id)
        reasons: list[str] = []
        if hard:
            reasons.append("PROTECTED_HARD_REGRESSION")
        if missing:
            reasons.append("REQUIRED_COMPARISON_EVIDENCE_MISSING")
        if regressed:
            reasons.append("MATERIAL_METRIC_REGRESSION")
        if improved:
            reasons.append("MATERIAL_METRIC_IMPROVEMENT")
        if not reasons:
            reasons.append("NO_MATERIAL_CHANGE")
        return CandidateComparison(
            candidate_index=candidate_index,
            candidate_attempt_ref=candidate_attempt_ref,
            comparison_eligible=not missing,
            metrics=tuple(comparisons),
            improved_metric_ids=tuple(improved),
            regressed_metric_ids=tuple(regressed),
            hard_regression_metric_ids=tuple(hard),
            missing_required_metric_ids=tuple(missing),
            reason_codes=tuple(reasons),
        )

    def _round(
        self,
        round_index: int,
        incumbent_ref: Path,
        outcome: str,
        candidates: tuple[CandidateComparison, ...],
        selected_ref: Path | None,
        reasons: tuple[str, ...],
    ) -> RoundComparison:
        return RoundComparison(
            round_index=round_index,
            incumbent_before_ref=incumbent_ref,
            policy_id=self.policy.policy_id,
            policy_sha256=self.policy_sha256,
            outcome=cast(
                Literal[
                    "ACCEPT_CANDIDATE",
                    "KEEP_INCUMBENT",
                    "HUMAN_REVIEW",
                    "INSUFFICIENT_EVIDENCE",
                    "ALL_CANDIDATES_FAILED",
                ],
                outcome,
            ),
            selected_attempt_ref=selected_ref,
            candidates=candidates,
            reason_codes=reasons,
        )


def _compare_metric(
    metric_id: str,
    policy: MetricPolicy,
    *,
    incumbent: float | None,
    candidate: float | None,
    reference_available: bool,
    trusted_genome_size: bool,
) -> MetricComparison:
    if not _applicable(
        policy,
        reference_available=reference_available,
        trusted_genome_size=trusted_genome_size,
    ):
        return MetricComparison(
            metric_id=metric_id,
            incumbent_value=incumbent,
            candidate_value=candidate,
            direction=policy.direction,
            assessment="NOT_APPLICABLE",
            reason_codes=("METRIC_NOT_APPLICABLE",),
        )
    if incumbent is None or candidate is None:
        return MetricComparison(
            metric_id=metric_id,
            incumbent_value=incumbent,
            candidate_value=candidate,
            direction=policy.direction,
            assessment="MISSING",
            reason_codes=("METRIC_VALUE_MISSING",),
        )
    oriented = _oriented_delta(policy.direction, incumbent, candidate)
    material = _threshold(policy.material_delta, policy.material_mode, incumbent)
    hard_threshold = (
        _threshold(policy.hard_regression_delta, policy.hard_regression_mode, incumbent)
        if policy.hard_regression_delta is not None
        else None
    )
    if hard_threshold is not None and oriented <= -hard_threshold:
        assessment: MetricAssessment = "HARD_REGRESSION"
        reasons = ("HARD_REGRESSION_THRESHOLD_REACHED",)
    elif oriented >= material:
        assessment = "IMPROVED"
        reasons = ("MATERIAL_IMPROVEMENT",)
    elif oriented <= -material:
        assessment = "REGRESSED"
        reasons = ("MATERIAL_REGRESSION",)
    else:
        assessment = "UNCHANGED"
        reasons = ("BELOW_MATERIAL_DELTA",)
    return MetricComparison(
        metric_id=metric_id,
        incumbent_value=incumbent,
        candidate_value=candidate,
        direction=policy.direction,
        assessment=assessment,
        oriented_delta=oriented,
        material_threshold=material,
        hard_regression_threshold=hard_threshold,
        reason_codes=reasons,
    )


def _applicable(
    policy: MetricPolicy,
    *,
    reference_available: bool,
    trusted_genome_size: bool,
) -> bool:
    return (
        policy.applicability == "always"
        or (policy.applicability == "reference" and reference_available)
        or (policy.applicability == "trusted_genome_size" and trusted_genome_size)
    )


def _oriented_delta(direction: MetricDirection, incumbent: float, candidate: float) -> float:
    if direction == "higher":
        return candidate - incumbent
    if direction == "lower":
        return incumbent - candidate
    return abs(incumbent - 1.0) - abs(candidate - 1.0)


def _threshold(value: float, mode: Literal["absolute", "relative"], incumbent: float) -> float:
    if mode == "relative":
        return abs(incumbent) * value
    return value


def _numeric(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _metrics_for_ref(
    candidates: tuple[tuple[int, Path, AssemblyMetrics], ...],
    reference: Path,
) -> AssemblyMetrics:
    return next(metrics for _index, path, metrics in candidates if path == reference)


def _dominates(
    left: AssemblyMetrics,
    right: AssemblyMetrics,
    policy: ComparisonPolicy,
    *,
    reference_available: bool,
    trusted_genome_size: bool,
) -> bool:
    materially_better = False
    for metric_id, specification in policy.metrics.items():
        if not _applicable(
            specification,
            reference_available=reference_available,
            trusted_genome_size=trusted_genome_size,
        ):
            continue
        left_value = _numeric(getattr(left, metric_id, None))
        right_value = _numeric(getattr(right, metric_id, None))
        if left_value is None or right_value is None:
            continue
        delta = _oriented_delta(specification.direction, right_value, left_value)
        threshold = _threshold(
            specification.material_delta,
            specification.material_mode,
            right_value,
        )
        if delta <= -threshold:
            return False
        materially_better = materially_better or delta >= threshold
    return materially_better
