"""current run identity, state, and transaction models for the single control plane."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RunPhase(StrEnum):
    """Complete current lifecycle; later stages activate the scientific transitions."""

    INITIALIZING = "INITIALIZING"
    INPUT_VALIDATION = "INPUT_VALIDATION"
    ENVIRONMENT_PREFLIGHT = "ENVIRONMENT_PREFLIGHT"
    PRE_QC = "PRE_QC"
    BASELINE_PLAN = "BASELINE_PLAN"
    BASELINE_ASSEMBLY = "BASELINE_ASSEMBLY"
    BASELINE_POST_QC = "BASELINE_POST_QC"
    BASELINE_REVIEW = "BASELINE_REVIEW"
    ROUND_CONTEXT = "ROUND_CONTEXT"
    RAG_RETRIEVAL = "RAG_RETRIEVAL"
    LLM_PROPOSAL = "LLM_PROPOSAL"
    SAFETY_REVIEW = "SAFETY_REVIEW"
    BUDGET_RESERVATION = "BUDGET_RESERVATION"
    CANDIDATE_ASSEMBLY = "CANDIDATE_ASSEMBLY"
    CANDIDATE_POST_QC = "CANDIDATE_POST_QC"
    ROUND_COMPARISON = "ROUND_COMPARISON"
    INCUMBENT_UPDATE = "INCUMBENT_UPDATE"
    REPORTING = "REPORTING"
    VERIFYING = "VERIFYING"
    TERMINAL = "TERMINAL"


class RunIdentity(BaseModel):
    """Immutable identity created only after validation and environment preflight."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    run_uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    sample_id: str
    run_dir: Path
    created_at: datetime
    code_commit: str
    package_version: str
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    comparison_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rag_index_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        sample_id: str,
        run_dir: Path,
        code_commit: str,
        package_version: str,
        config: Path,
        effective_config: Path,
        input_manifest: Path,
        environment_manifest: Path,
        comparison_policy: Path,
        rag_index: Path | None = None,
    ) -> RunIdentity:
        """Hash all immutable snapshots and create a fresh run UUID."""
        return cls(
            run_uuid=uuid.uuid4().hex,
            sample_id=sample_id,
            run_dir=run_dir.resolve(),
            created_at=datetime.now(UTC),
            code_commit=code_commit,
            package_version=package_version,
            config_sha256=sha256_file(config),
            effective_config_sha256=sha256_file(effective_config),
            input_manifest_sha256=sha256_file(input_manifest),
            environment_manifest_sha256=sha256_file(environment_manifest),
            comparison_policy_sha256=sha256_file(comparison_policy),
            rag_index_sha256=sha256_file(rag_index) if rag_index is not None else None,
        )


class RunEvent(BaseModel):
    """One append-only, transaction-bound lifecycle event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    transaction_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    sequence: int = Field(ge=1)
    timestamp: datetime
    state_before: RunPhase | None
    state_after: RunPhase
    action: str = Field(min_length=1)
    reason_codes: list[str] = Field(min_length=1)
    round_index: int = Field(default=0, ge=0, le=3)
    candidate_index: int | None = Field(default=None, ge=1, le=2)
    attempt_id: str | None = None
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RunState(BaseModel):
    """The only authoritative lifecycle snapshot for one current run."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    identity: RunIdentity
    sequence: int = Field(default=0, ge=0)
    state: RunPhase = RunPhase.INITIALIZING
    round_index: int = Field(default=0, ge=0, le=3)
    candidate_index: int | None = Field(default=None, ge=1, le=2)
    active_attempt_id: str | None = None
    baseline_run_ref: Path | None = None
    incumbent_run_ref: Path | None = None
    seen_parameter_fingerprints: list[str] = Field(default_factory=list)
    completed_round_refs: list[Path] = Field(default_factory=list)
    budget_snapshot_ref: Path | None = None
    latest_decision_ref: Path | None = None
    terminal_outcome: str | None = None
    outcome_class: Literal["SCIENTIFIC", "ACTION_REQUIRED", "FAILED"] | None = None
    terminal_reason_codes: list[str] = Field(default_factory=list)
    last_error: str | None = None
    report_refs: list[Path] = Field(default_factory=list)
    last_transaction_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    last_event: RunEvent | None = None


class PendingTransaction(BaseModel):
    """Write-ahead record used to reconcile the snapshot/event crash window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    run_uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    previous_sequence: int = Field(ge=0)
    event: RunEvent
    next_state: RunState
    next_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        previous_sequence: int,
        event: RunEvent,
        next_state: RunState,
    ) -> PendingTransaction:
        """Bind a pending record to the exact next-state serialization."""
        return cls(
            run_uuid=next_state.identity.run_uuid,
            previous_sequence=previous_sequence,
            event=event,
            next_state=next_state,
            next_state_sha256=sha256_json(next_state.model_dump(mode="json")),
        )


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 for a required file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(payload: object) -> str:
    """Hash a JSON-compatible payload using canonical separators and ordering."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def state_control_sha256(state: RunState) -> str:
    """Bind an event to the authoritative control fields without recursive event data."""
    return sha256_json(
        state.model_dump(
            mode="json",
            exclude={"last_event", "last_transaction_id"},
        )
    )
