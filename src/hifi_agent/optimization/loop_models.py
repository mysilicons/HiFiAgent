"""Persistent schemas for the Stage 9 three-round optimization loop."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hifi_agent.optimization.round_models import ComparableRun, RoundComparison
from hifi_agent.rag.models import ApprovedCandidate
from hifi_agent.schemas.metrics import AssemblyMetrics

LoopAction = Literal["ACCEPT", "STOP", "RETRY"]
LoopPhase = Literal["DECIDE", "EXECUTE", "COMPARE", "TERMINAL"]
LoopTerminalOutcome = Literal[
    "ACCEPTED_BASELINE",
    "ACCEPTED_CURRENT_INCUMBENT",
    "STOP_RULE_DECISION",
    "STOP_PLATEAU",
    "STOP_CONFLICT",
    "STOP_INSUFFICIENT_METRICS",
    "STOP_EXECUTION_FAILURE",
    "STOP_BUDGET",
    "STOP_MAX_ROUNDS",
    "NO_UNIQUE_CANDIDATE",
]


class LoopDirective(BaseModel):
    """One deterministic, safety-approved instruction for the current incumbent."""

    model_config = ConfigDict(extra="forbid")

    action: LoopAction
    reason_codes: list[str] = Field(min_length=1)
    approved_candidates: list[ApprovedCandidate] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def validate_candidate_authority(self) -> LoopDirective:
        """Reject directives whose action and approved candidates disagree."""
        if self.action == "RETRY" and not self.approved_candidates:
            raise ValueError("RETRY directive requires at least one ApprovedCandidate")
        if self.action != "RETRY" and self.approved_candidates:
            raise ValueError("Only RETRY directives may carry ApprovedCandidate objects")
        return self


class LoopDecisionContext(BaseModel):
    """Path-free facts supplied to the round proposal provider."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    round_index: int = Field(ge=1, le=3)
    incumbent_run_id: str
    incumbent_metrics: AssemblyMetrics
    seen_parameter_fingerprints: list[str]
    remaining_cpu_hours: float = Field(ge=0.0)
    remaining_walltime_hours: float = Field(ge=0.0)


class LoopBudget(BaseModel):
    """Hard launch budget, persisted before every candidate."""

    model_config = ConfigDict(extra="forbid")

    max_cpu_hours: float = Field(ge=0.0)
    max_walltime_hours: float = Field(ge=0.0)
    estimated_candidate_cpu_hours: float = Field(gt=0.0)
    estimated_candidate_walltime_hours: float = Field(gt=0.0)
    consumed_cpu_hours: float = Field(default=0.0, ge=0.0)
    consumed_walltime_hours: float = Field(default=0.0, ge=0.0)
    candidates_started: int = Field(default=0, ge=0)
    accounted_attempts: list[str] = Field(default_factory=list)

    def exhausted_reason(self) -> str | None:
        """Return the first projected hard-budget violation, if any."""
        if self.consumed_cpu_hours + self.estimated_candidate_cpu_hours > self.max_cpu_hours:
            return "CPU_HOUR_BUDGET_EXCEEDED"
        if (
            self.consumed_walltime_hours + self.estimated_candidate_walltime_hours
            > self.max_walltime_hours
        ):
            return "WALLTIME_BUDGET_EXCEEDED"
        return None

    def account(self, result: ComparableRun) -> None:
        """Account a completed attempt exactly once by its run and attempt IDs."""
        key = f"{result.run_id}/{result.attempt_id}"
        if key in self.accounted_attempts:
            return
        self.consumed_cpu_hours += result.cpu_hours
        self.consumed_walltime_hours += result.walltime_hours
        self.accounted_attempts.append(key)


class LoopRoundRecord(BaseModel):
    """Completed round directive, executions, and comparison."""

    model_config = ConfigDict(extra="forbid")

    round_index: int = Field(ge=1, le=3)
    incumbent_before: str
    directive: LoopDirective
    candidate_results: list[ComparableRun] = Field(max_length=2)
    comparison: RoundComparison


class LoopEvent(BaseModel):
    """Auditable state transition for interruption and resume checks."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    timestamp: datetime
    phase_before: LoopPhase
    phase_after: LoopPhase
    action: str
    round_index: int = Field(ge=1, le=3)
    candidate_index: int | None = Field(default=None, ge=1, le=2)
    run_id: str | None = None
    reason_codes: list[str] = Field(min_length=1)


class OptimizationLoopState(BaseModel):
    """Atomic Stage 9 snapshot; sufficient to resume without returning to round 1."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    sample_id: str
    baseline_run_id: str
    baseline_parameter_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_metrics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    updated_at: datetime
    phase: LoopPhase = "DECIDE"
    round_index: int = Field(default=1, ge=1, le=3)
    max_rounds: Literal[1, 2, 3] = 3
    max_candidates_per_round: int = Field(default=1, ge=1, le=2)
    incumbent: ComparableRun
    seen_parameter_fingerprints: list[str]
    budget: LoopBudget
    active_directive: LoopDirective | None = None
    pending_candidates: list[ApprovedCandidate] = Field(default_factory=list, max_length=2)
    candidate_results: list[ComparableRun] = Field(default_factory=list, max_length=2)
    next_candidate_index: int = Field(default=1, ge=1, le=3)
    active_candidate_index: int | None = Field(default=None, ge=1, le=2)
    rounds: list[LoopRoundRecord] = Field(default_factory=list, max_length=3)
    terminal_outcome: LoopTerminalOutcome | None = None
    selected_run_id: str | None = None
    last_error: str | None = None
    events: list[LoopEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_terminal_state(self) -> OptimizationLoopState:
        """Keep the terminal phase and terminal outcome fields synchronized."""
        if self.phase == "TERMINAL" and self.terminal_outcome is None:
            raise ValueError("terminal loop state requires terminal_outcome")
        if self.phase != "TERMINAL" and self.terminal_outcome is not None:
            raise ValueError("non-terminal loop state cannot have terminal_outcome")
        return self
