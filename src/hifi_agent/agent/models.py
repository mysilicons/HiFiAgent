"""Validated schemas for the recoverable Stage 9 Agent controller."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hifi_agent.rules.models import RiskLevel, RuleDecision
from hifi_agent.schemas.metrics import AssemblyMetrics


class AgentState(StrEnum):
    """Explicit states in the bounded V1 Agent state machine."""

    INPUT_VALIDATION = "INPUT_VALIDATION"
    PRE_QC = "PRE_QC"
    QC_REVIEW = "QC_REVIEW"
    ASSEMBLY_BASELINE = "ASSEMBLY_BASELINE"
    POST_QC = "POST_QC"
    EVALUATE = "EVALUATE"
    PLAN_RETRY = "PLAN_RETRY"
    ASSEMBLY_CANDIDATE = "ASSEMBLY_CANDIDATE"
    ACCEPTED = "ACCEPTED"
    FAILED_INPUT = "FAILED_INPUT"
    STOP_LOW_QUALITY = "STOP_LOW_QUALITY"
    STOP_INSUFFICIENT_METADATA = "STOP_INSUFFICIENT_METADATA"
    STOP_UNCERTAIN = "STOP_UNCERTAIN"
    STOP_BUDGET_EXCEEDED = "STOP_BUDGET_EXCEEDED"
    FAILED_TOOL_EXECUTION = "FAILED_TOOL_EXECUTION"
    REPORT = "REPORT"


TerminalOutcome = Literal[
    "ACCEPTED",
    "FAILED_INPUT",
    "STOP_LOW_QUALITY",
    "STOP_INSUFFICIENT_METADATA",
    "STOP_UNCERTAIN",
    "STOP_BUDGET_EXCEEDED",
    "FAILED_TOOL_EXECUTION",
]
RetryKind = Literal["NONE", "TOOL_FAILURE", "PARAMETER_OPTIMIZATION"]

TERMINAL_STATES = frozenset(
    {
        AgentState.ACCEPTED,
        AgentState.FAILED_INPUT,
        AgentState.STOP_LOW_QUALITY,
        AgentState.STOP_INSUFFICIENT_METADATA,
        AgentState.STOP_UNCERTAIN,
        AgentState.STOP_BUDGET_EXCEEDED,
        AgentState.FAILED_TOOL_EXECUTION,
    }
)


class PreQcMetrics(BaseModel):
    """Stage 4/5 metrics required by the Agent's pre-QC gate."""

    model_config = ConfigDict(extra="allow")

    sample_id: str
    input_status: str
    read_count: int | None = None
    total_bases: int | None = None
    estimated_genome_size: int | None = None
    estimated_coverage: float | None = None
    warnings: list[str] = Field(default_factory=list)


class AssemblyParameters(BaseModel):
    """Complete, whitelisted hifiasm parameter set for one assembly run."""

    model_config = ConfigDict(extra="forbid")

    purge_level: int = Field(default=3, ge=0, le=3)
    purge_similarity: float = Field(default=0.55, ge=0.0, le=1.0)
    hom_cov: int | None = Field(default=None, ge=1)
    disable_post_join: bool = False


class AssemblyConfig(BaseModel):
    """Audited baseline or candidate assembly configuration."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    assembler: Literal["hifiasm"] = "hifiasm"
    input_reads: list[Path] = Field(min_length=1)
    threads: int = Field(ge=1)
    parameters: AssemblyParameters = Field(default_factory=AssemblyParameters)
    reason_codes: list[str] = Field(min_length=1)
    source_metrics: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    requires_user_confirmation: bool = False
    retry_kind: RetryKind = "NONE"
    optimization_round: int = Field(default=0, ge=0, le=3)

    def parameter_fingerprint(self) -> str:
        """Return a stable hash used to prevent duplicate parameter runs."""
        payload = json.dumps(
            self.parameters.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class AssemblyArtifact(BaseModel):
    """Files and resource usage produced by one completed assembly."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    manifest: Path
    primary_fasta: Path
    cpu_hours: float = Field(default=0.0, ge=0.0)
    walltime_hours: float = Field(default=0.0, ge=0.0)


class BudgetLedger(BaseModel):
    """Hard retry, candidate, CPU-hour, and walltime accounting."""

    model_config = ConfigDict(extra="forbid")

    max_retry_rounds: int = Field(ge=0, le=2)
    max_candidates_per_round: int = Field(ge=1, le=2)
    max_tool_retries: int = Field(ge=0, le=3)
    max_cpu_hours: float = Field(ge=0.0)
    max_walltime_hours: float = Field(ge=0.0)
    consumed_cpu_hours: float = Field(default=0.0, ge=0.0)
    consumed_walltime_hours: float = Field(default=0.0, ge=0.0)
    optimization_rounds_started: int = Field(default=0, ge=0)
    candidates_started_by_round: dict[str, int] = Field(default_factory=dict)
    tool_retry_counts: dict[str, int] = Field(default_factory=dict)
    accounted_run_ids: list[str] = Field(default_factory=list)

    def exhausted_reason(
        self, *, estimated_cpu: float = 0.0, estimated_wall: float = 0.0
    ) -> str | None:
        """Return the first compute budget that would be exceeded by a launch."""
        if self.consumed_cpu_hours >= self.max_cpu_hours:
            return "CPU_HOUR_BUDGET_EXCEEDED"
        if self.consumed_walltime_hours >= self.max_walltime_hours:
            return "WALLTIME_BUDGET_EXCEEDED"
        if self.consumed_cpu_hours + estimated_cpu > self.max_cpu_hours:
            return "CPU_HOUR_BUDGET_EXCEEDED"
        if self.consumed_walltime_hours + estimated_wall > self.max_walltime_hours:
            return "WALLTIME_BUDGET_EXCEEDED"
        return None

    def account(self, artifact: AssemblyArtifact) -> None:
        """Account one successful assembly exactly once."""
        if artifact.run_id in self.accounted_run_ids:
            return
        self.consumed_cpu_hours += artifact.cpu_hours
        self.consumed_walltime_hours += artifact.walltime_hours
        self.accounted_run_ids.append(artifact.run_id)


class TransitionEvent(BaseModel):
    """One append-only state transition written to decision_trace.jsonl."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    sequence: int = Field(ge=1)
    timestamp: datetime
    state_before: AgentState | None
    state_after: AgentState
    action: str
    reason_codes: list[str] = Field(min_length=1)
    evidence: dict[str, bool | int | float | str | None] = Field(default_factory=dict)
    retry_kind: RetryKind = "NONE"
    run_id: str | None = None
    parameter_fingerprint: str | None = None


class AgentRunState(BaseModel):
    """Complete recoverable snapshot of one Agent execution."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    sample_id: str
    run_dir: Path
    config_path: Path
    state: AgentState = AgentState.INPUT_VALIDATION
    transition_sequence: int = 0
    terminal_outcome: TerminalOutcome | None = None
    budget: BudgetLedger
    pre_qc_metrics: PreQcMetrics | None = None
    baseline_config: AssemblyConfig | None = None
    active_config: AssemblyConfig | None = None
    active_artifact: AssemblyArtifact | None = None
    active_metrics: AssemblyMetrics | None = None
    active_metrics_path: Path | None = None
    latest_decision: RuleDecision | None = None
    pending_candidates: list[AssemblyConfig] = Field(default_factory=list)
    started_parameter_fingerprints: list[str] = Field(default_factory=list)
    completed_run_ids: list[str] = Field(default_factory=list)
    last_error: str | None = None
    report_path: Path | None = None
    last_event: TransitionEvent | None = None

    @model_validator(mode="after")
    def validate_terminal_outcome(self) -> AgentRunState:
        """Keep terminal outcome and terminal/report states coherent."""
        if self.state in TERMINAL_STATES and self.terminal_outcome != self.state.value:
            raise ValueError("terminal state requires matching terminal_outcome")
        if self.state == AgentState.REPORT and self.terminal_outcome is None:
            raise ValueError("REPORT requires a retained terminal_outcome")
        return self
