"""Validated schemas for bounded Stage 11 closed-loop optimization."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hifi_agent.agent.models import AssemblyConfig
from hifi_agent.schemas.metrics import AssemblyMetrics

MetricDirection = Literal["target_one", "higher", "lower", "contextual_lower"]
MetricAssessment = Literal["IMPROVED", "REGRESSED", "UNCHANGED", "UNAVAILABLE"]
CandidateStatus = Literal[
    "ACCEPTED",
    "DOMINATED",
    "REJECTED_REGRESSION",
    "REJECTED_NO_GAIN",
    "NOT_RUN",
    "FAILED",
]
OptimizationOutcome = Literal[
    "ACCEPTED_CANDIDATE",
    "BASELINE_RETAINED",
    "RETRY",
    "STOP_RULE_DECISION",
    "STOP_METRIC_CONFLICT",
    "STOP_RETRY_LIMIT",
    "STOP_INSUFFICIENT_METRICS",
    "STOP_EXECUTION_FAILURE",
    "STOP_CONFIRMATION_REQUIRED",
]


class ParameterDifference(BaseModel):
    """One audited parameter delta from baseline to candidate."""

    model_config = ConfigDict(extra="forbid")

    parameter: str
    baseline_value: bool | int | float | None
    candidate_value: bool | int | float | None


class MetricDifference(BaseModel):
    """One direction-aware baseline/candidate metric comparison."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    direction: MetricDirection
    baseline_value: int | float | None
    candidate_value: int | float | None
    delta: int | float | None
    assessment: MetricAssessment
    material: bool = False
    note: str


class CandidateAssessment(BaseModel):
    """Safety and dominance assessment for one bounded candidate."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: CandidateStatus
    config: AssemblyConfig
    metrics: AssemblyMetrics | None
    metrics_source: str
    parameter_differences: list[ParameterDifference]
    metric_differences: list[MetricDifference]
    dominated_by: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    regressions: list[str] = Field(default_factory=list)
    hard_regressions: list[str] = Field(default_factory=list)
    acceptance_failures: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    synthetic: bool = False


class OptimizationResult(BaseModel):
    """Complete Stage 11 comparison, selection, and budget result."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    sample_id: str
    run_dir: str
    optimization_round: int = Field(ge=0, le=2)
    max_retry_rounds: int = Field(ge=0, le=2)
    max_candidates_per_round: int = Field(ge=1, le=2)
    baseline_config: AssemblyConfig
    baseline_metrics: AssemblyMetrics
    baseline_metrics_source: str
    triggering_decision: dict[str, object]
    candidates: list[CandidateAssessment] = Field(max_length=2)
    outcome: OptimizationOutcome
    selected_run_id: str | None = None
    selection_reason: str
    selection_tradeoffs: list[str]
    retained_run_ids: list[str]
    synthetic: bool = False
    scenario_id: str | None = None
    scenario_disclaimer: str | None = None
    source_sha256: dict[str, str] = Field(default_factory=dict)


class SyntheticMetricTransformation(BaseModel):
    """Auditable real-to-synthetic metric transformation."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    metric: str
    operation: Literal["set", "multiply", "copy"]
    source_value: int | float
    synthetic_value: int | float
    rationale: str


class Stage11SyntheticScenario(BaseModel):
    """Explicitly artificial Stage 11 loop derived from a genuine run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str
    generated_at: datetime
    synthetic: Literal[True] = True
    disclaimer: str
    source_sample_id: str
    source_run_dir: Path
    source_artifacts: dict[str, str]
    source_sha256: dict[str, str]
    baseline_metrics: AssemblyMetrics
    candidate_metrics: list[AssemblyMetrics] = Field(min_length=1, max_length=2)
    transformations: list[SyntheticMetricTransformation]
