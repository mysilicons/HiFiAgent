"""Schemas for Stage 8 incumbent-based round comparison."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hifi_agent.agent.models import AssemblyConfig
from hifi_agent.schemas.metrics import AssemblyMetrics

MetricResult = Literal["IMPROVED", "REGRESSED", "UNCHANGED", "UNAVAILABLE", "NOT_APPLICABLE"]
RoundCandidateStatus = Literal[
    "ELIGIBLE",
    "PLATEAU",
    "TRADEOFF",
    "HARD_REGRESSION",
    "ACCEPTANCE_FAILURE",
    "UNAVAILABLE",
    "INVALID_CONTRACT",
    "EXECUTION_FAILURE",
    "DOMINATED",
]
RoundOutcome = Literal[
    "INCUMBENT_UPDATED",
    "STOP_PLATEAU",
    "STOP_CONFLICT",
    "STOP_INSUFFICIENT_METRICS",
    "STOP_EXECUTION_FAILURE",
    "NO_UNIQUE_CANDIDATE",
]


class ComparableRun(BaseModel):
    """One attempt that may enter an incumbent comparison."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    attempt_id: str
    config: AssemblyConfig
    metrics: AssemblyMetrics | None
    metrics_path: Path
    parameter_contract_status: Literal["PASS", "FAIL", "MISSING"]
    execution_status: Literal["COMPLETED", "FAILED"]
    cpu_hours: float = Field(default=0.0, ge=0.0)
    walltime_hours: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_run_binding(self) -> ComparableRun:
        """Require configuration and metrics artifacts to belong to this run."""
        if self.config.run_id != self.run_id:
            raise ValueError("comparable config run ID mismatch")
        if self.metrics is not None and self.metrics.run_id != self.run_id:
            raise ValueError("comparable metrics run ID mismatch")
        return self


class RoundComparisonContext(BaseModel):
    """Scientific applicability flags fixed before comparison."""

    model_config = ConfigDict(extra="forbid")

    reference_available: bool
    genome_size_trusted: bool


class RoundMetricDifference(BaseModel):
    """Direction-aware incumbent/candidate metric result."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    direction: Literal["higher", "lower", "target_one"]
    incumbent_value: int | float | None
    candidate_value: int | float | None
    delta: int | float | None
    result: MetricResult
    material: bool = False
    protected: bool = False
    reason: str


class RoundParameterDifference(BaseModel):
    """One parameter delta from the current incumbent."""

    model_config = ConfigDict(extra="forbid")

    parameter: str
    incumbent_value: bool | int | float | None
    candidate_value: bool | int | float | None


class RoundCandidateAssessment(BaseModel):
    """Complete Stage 8 assessment for one candidate attempt."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    attempt_id: str
    status: RoundCandidateStatus
    parameter_differences: list[RoundParameterDifference]
    metric_differences: list[RoundMetricDifference]
    material_improvements: list[str] = Field(default_factory=list)
    material_regressions: list[str] = Field(default_factory=list)
    hard_regressions: list[str] = Field(default_factory=list)
    acceptance_failures: list[str] = Field(default_factory=list)
    unavailable_metrics: list[str] = Field(default_factory=list)
    dominated_by: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)


class RoundComparison(BaseModel):
    """Persistable selection result for one optimization round."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    policy_version: str
    generated_at: datetime
    round_index: int = Field(ge=1, le=3)
    incumbent_before: str
    incumbent_after: str
    context: RoundComparisonContext
    candidates: list[RoundCandidateAssessment] = Field(min_length=1, max_length=2)
    nondominated_run_ids: list[str]
    outcome: RoundOutcome
    selected_run_id: str | None = None
    reason_codes: list[str] = Field(min_length=1)
    comparison_json: Path | None = None
    comparison_tsv: Path | None = None
    parameter_diff_tsv: Path | None = None
    selection_tradeoffs_md: Path | None = None
