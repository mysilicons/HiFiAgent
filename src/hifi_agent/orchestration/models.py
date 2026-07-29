"""Typed V2 identities, immutable-history records, and controller state."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hifi_agent.agent.models import AssemblyConfig
from hifi_agent.rules.models import RuleDecision


class RunIdentity(BaseModel):
    """Stable identity for one V2 sample run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    run_uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    sample_id: str
    created_at: datetime
    run_dir: Path
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AttemptIdentity(BaseModel):
    """Stable biological-run and tool-attempt identity."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    run_uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    kind: Literal["baseline", "candidate"]
    round_index: int = Field(ge=0, le=3)
    candidate_index: int | None = Field(default=None, ge=1, le=2)
    attempt_index: int = Field(ge=1)
    run_id: str = Field(pattern=r"^(baseline|candidate_r0[1-3]_c0[1-2])$")
    attempt_id: str = Field(pattern=r"^attempt_[0-9]{3,}$")

    @model_validator(mode="after")
    def validate_coordinates(self) -> AttemptIdentity:
        """Keep baseline and candidate coordinates coherent."""
        if self.kind == "baseline":
            if (
                self.round_index != 0
                or self.candidate_index is not None
                or self.run_id != "baseline"
            ):
                raise ValueError("baseline identity must use round 0 without a candidate index")
        elif (
            self.round_index == 0
            or self.candidate_index is None
            or self.run_id != candidate_run_id(self.round_index, self.candidate_index)
        ):
            raise ValueError("candidate identity does not match its round/candidate coordinates")
        if self.attempt_id != attempt_id(self.attempt_index):
            raise ValueError("attempt_id does not match attempt_index")
        return self

    def relative_directory(self) -> Path:
        """Return the immutable V2 assembly-history directory."""
        if self.kind == "baseline":
            return Path("baseline") / self.attempt_id
        assert self.candidate_index is not None
        return (
            Path(round_id(self.round_index)) / candidate_id(self.candidate_index) / self.attempt_id
        )


class ArtifactRecord(BaseModel):
    """Checksum-bound reference to one real artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    role: str
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)


class AttemptManifest(BaseModel):
    """Immutable manifest for one completed or failed attempt."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    identity: AttemptIdentity
    status: Literal["COMPLETED", "FAILED"]
    created_at: datetime
    completed_at: datetime
    parameter_fingerprint: str | None = None
    artifacts: list[ArtifactRecord]
    error: str | None = None


class RoundRecord(BaseModel):
    """Persisted V2 decision and attempt summary for one round."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    round_index: int = Field(ge=0, le=3)
    incumbent_before: str
    candidate_run_ids: list[str] = Field(max_length=2)
    attempt_ids: list[str]
    outcome: str
    incumbent_after: str | None = None
    stop_reason: str | None = None


class HistoryManifest(BaseModel):
    """Index of immutable attempts belonging to one V2 run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    run_identity: RunIdentity
    updated_at: datetime
    attempts: list[AttemptIdentity]
    rounds: list[RoundRecord] = Field(default_factory=list)


class AssemblyState(StrEnum):
    """Stage 3 baseline and first-candidate orchestration states."""

    INPUT_VALIDATION = "INPUT_VALIDATION"
    BASELINE_EXECUTION = "BASELINE_EXECUTION"
    BASELINE_EVALUATION = "BASELINE_EVALUATION"
    CANDIDATE_EXECUTION = "CANDIDATE_EXECUTION"
    REPORT = "REPORT"


class AssemblyEvent(BaseModel):
    """One append-only V2 controller transition."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    sequence: int = Field(ge=1)
    timestamp: datetime
    state_before: AssemblyState | None
    state_after: AssemblyState
    action: str
    reason_codes: list[str] = Field(min_length=1)
    run_id: str | None = None
    attempt_id: str | None = None


class AssemblyRunState(BaseModel):
    """Recoverable snapshot for the unified Stage 3 command."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    identity: RunIdentity
    config_path: Path
    state: AssemblyState = AssemblyState.INPUT_VALIDATION
    transition_sequence: int = 0
    last_event: AssemblyEvent | None = None
    baseline_attempt: AttemptIdentity | None = None
    candidate_attempt: AttemptIdentity | None = None
    candidate_config: AssemblyConfig | None = None
    latest_decision: RuleDecision | None = None
    tool_retry_counts: dict[str, int] = Field(default_factory=dict)
    terminal_outcome: str | None = None
    report_path: Path | None = None
    last_error: str | None = None


def round_id(round_index: int) -> str:
    """Return a stable round identifier."""
    if not 1 <= round_index <= 3:
        raise ValueError("optimization round must be between 1 and 3")
    return f"round_{round_index:02d}"


def candidate_id(candidate_index: int) -> str:
    """Return a stable candidate identifier within a round."""
    if not 1 <= candidate_index <= 2:
        raise ValueError("candidate index must be between 1 and 2")
    return f"candidate_{candidate_index:02d}"


def candidate_run_id(round_index: int, candidate_index: int) -> str:
    """Return the V1-compatible biological run ID."""
    round_id(round_index)
    candidate_id(candidate_index)
    return f"candidate_r{round_index:02d}_c{candidate_index:02d}"


def attempt_id(attempt_index: int) -> str:
    """Return a stable tool-attempt identifier."""
    if attempt_index < 1:
        raise ValueError("attempt index must be positive")
    return f"attempt_{attempt_index:03d}"
