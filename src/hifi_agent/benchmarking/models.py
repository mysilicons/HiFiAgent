"""Validated schemas for the public Stage 13 benchmark artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hifi_agent.rules.context import RuleContext


class BenchmarkScenario(BaseModel):
    """One immutable benchmark input and its expert-reviewed expected outcome."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    title: str
    data_kind: Literal["public_real", "real_derived_perturbation", "synthetic_fixture"]
    category: str
    context: RuleContext
    expected_decision: Literal["BASELINE", "STOP", "RETRY"]
    expected_action: str
    expected_parameters: list[dict[str, bool | int | float]] = Field(default_factory=list)
    expected_rule_id: str | None = None
    construction: str
    limitation: str | None = None


class ScenarioResult(BaseModel):
    """Observed deterministic result for one scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    data_kind: str
    expected_decision: str
    observed_decision: str
    expected_action: str
    observed_action: str
    controlling_rule_ids: list[str]
    candidate_parameters: list[dict[str, bool | int | float]]
    candidate_count: int = Field(ge=0)
    parameter_legality: bool
    nonexistent_parameters: list[str]
    evidence_count: int = Field(ge=0)
    repeat_consistent: bool
    passed: bool
    failure_reason: str | None = None


class MethodComparison(BaseModel):
    """Comparable outcome for one required Stage 13 method."""

    model_config = ConfigDict(extra="forbid")

    method_id: Literal["A", "B", "C", "D"]
    method: str
    decision_source: str
    action: str
    candidate_count: int = Field(ge=0)
    changes_rule_decision: bool | None
    cited_source_count: int = Field(ge=0)
    safety_status: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    interpretation: str


class AblationResult(BaseModel):
    """One controlled removal or unsafe comparator and its observed effect."""

    model_config = ConfigDict(extra="forbid")

    ablation_id: str
    full_system_outcome: str
    ablated_outcome: str
    safety_regression: bool
    conclusion: str


class AgentMetrics(BaseModel):
    """Aggregate safety and efficiency metrics required by the project plan."""

    model_config = ConfigDict(extra="forbid")

    scenario_count: int = Field(ge=1)
    pass_rate: float = Field(ge=0.0, le=1.0)
    parameter_legality_rate: float = Field(ge=0.0, le=1.0)
    nonexistent_parameter_rate: float = Field(ge=0.0, le=1.0)
    rule_decision_accuracy: float = Field(ge=0.0, le=1.0)
    erroneous_retry_rate: float = Field(ge=0.0, le=1.0)
    unnecessary_retry_rate: float = Field(ge=0.0, le=1.0)
    correct_stop_rate: float = Field(ge=0.0, le=1.0)
    evidence_citation_accuracy: float = Field(ge=0.0, le=1.0)
    repeat_consistency_rate: float = Field(ge=0.0, le=1.0)
    average_candidates_per_scenario: float = Field(ge=0.0)
    measured_extra_compute_cpu_hours: float | None = Field(default=None, ge=0.0)
    extra_compute_note: str


class BenchmarkReport(BaseModel):
    """Machine-readable public benchmark report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    benchmark_version: Literal["1.0.0"] = "1.0.0"
    generated_at: datetime
    project_version: str
    real_data_accessions: list[str]
    online_metadata_status: str
    scenarios: list[ScenarioResult]
    method_comparison: list[MethodComparison]
    ablations: list[AblationResult]
    metrics: AgentMetrics
    acceptance_passed: bool
    limitations: list[str]
