"""Machine-readable production terminal report contracts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AttemptSummary(BaseModel):
    """Manifest-derived facts for one assembly attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: str
    attempt_ref: Path
    round_index: int
    candidate_index: int | None
    status: str
    comparison_eligible: bool
    requested_config: dict[str, object]
    approved_parameters: dict[str, bool | int | float | None]
    rendered_argv: tuple[str, ...]
    realized_parameters: dict[str, bool | int | float | None] | None
    metrics: dict[str, bool | int | float | str | None]
    resource_usage: dict[str, float | int | None]
    error: str | None
    reason_codes: tuple[str, ...]

    @field_validator("attempt_ref")
    @classmethod
    def safe_ref(cls, value: Path) -> Path:
        """Reject attempt references outside the current run root."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("report attempt references must be run-relative")
        return value


class RoundSummary(BaseModel):
    """Manifest-derived incumbent transition for one completed round."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    round_index: int
    round_ref: Path
    incumbent_before_ref: Path | None
    incumbent_after_ref: Path | None
    outcome: str
    stop_reason_codes: tuple[str, ...]
    comparison_ref: Path | None
    approved_candidate_count: int
    rejected_candidate_count: int
    attempt_count: int


class LLMActivitySummary(BaseModel):
    """Secret-free account of whether an LLM participated in a round."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    round_index: int
    status: str
    provider: str | None
    model: str | None
    call_id: str
    prompt_sha256: str | None
    output_sha256: str | None
    failure_reason: str | None


class ProposalSummary(BaseModel):
    """Manifest-derived approved or rejected proposal, including execution linkage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    round_index: int = Field(ge=1, le=3)
    proposal_id: str
    disposition: Literal["APPROVED", "REJECTED"]
    candidate_index: int | None = Field(default=None, ge=1, le=2)
    origin: Literal["rule", "llm"]
    requested_changes: dict[str, object]
    approved_diff: dict[str, bool | int | float | None] | None
    parameter_fingerprint: str | None
    source_ids: tuple[str, ...]
    metric_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    executed_attempt_refs: tuple[Path, ...] = ()

    @field_validator("executed_attempt_refs")
    @classmethod
    def safe_executed_refs(cls, value: tuple[Path, ...]) -> tuple[Path, ...]:
        """Reject proposal execution references outside the current run root."""
        if any(item.is_absolute() or ".." in item.parts for item in value):
            raise ValueError("proposal execution references must be run-relative")
        return value


class FinalSummary(BaseModel):
    """Authoritative terminal summary from which Markdown and TSV files are derived."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    generated_at: datetime
    run_uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    sample_id: str
    package_version: str
    code_commit: str
    terminal_outcome: str
    outcome_class: Literal["SCIENTIFIC", "ACTION_REQUIRED", "FAILED"]
    process_exit_code: Literal[0, 3, 4, 5]
    selected_run_ref: Path | None
    baseline_run_ref: Path | None
    incumbent_chain: tuple[Path, ...]
    attempts: tuple[AttemptSummary, ...]
    rounds: tuple[RoundSummary, ...]
    proposals: tuple[ProposalSummary, ...] = ()
    llm_activity: tuple[LLMActivitySummary, ...]
    budget_limits: dict[str, float]
    budget_reserved: dict[str, float]
    budget_committed: dict[str, float]
    budget_remaining: dict[str, float]
    stop_reason_codes: tuple[str, ...]
    scientific_limitations: tuple[str, ...]
    verification_status: Literal["PENDING", "PASS", "WARNING", "FAIL"]

    @field_validator("selected_run_ref", "baseline_run_ref")
    @classmethod
    def safe_ref(cls, value: Path | None) -> Path | None:
        """Reject selected or baseline references outside the current run root."""
        if value is not None and (value.is_absolute() or ".." in value.parts):
            raise ValueError("report selected/baseline references must be run-relative")
        return value

    @model_validator(mode="after")
    def validate_terminal_contract(self) -> FinalSummary:
        """Bind exit semantics and the selected run to the reported incumbent chain."""
        expected = process_exit_code_for_terminal(self.terminal_outcome, self.outcome_class)
        if self.process_exit_code != expected:
            raise ValueError("report process exit code differs from its terminal outcome class")
        if any(item.is_absolute() or ".." in item.parts for item in self.incumbent_chain):
            raise ValueError("report incumbent chain references must be run-relative")
        if self.baseline_run_ref is not None and (
            not self.incumbent_chain or self.incumbent_chain[0] != self.baseline_run_ref
        ):
            raise ValueError("report incumbent chain does not start at baseline")
        chain_selected = self.incumbent_chain[-1] if self.incumbent_chain else None
        if self.selected_run_ref != chain_selected:
            raise ValueError("report selected run differs from the incumbent chain tail")
        return self


def process_exit_code_for_terminal(
    outcome: str,
    outcome_class: Literal["SCIENTIFIC", "ACTION_REQUIRED", "FAILED"],
) -> Literal[0, 3, 4, 5]:
    """Map one current terminal classification to the stable CLI exit contract."""
    if outcome == "FAILED_REQUIRED_LLM":
        return 5
    if outcome_class == "ACTION_REQUIRED":
        return 3
    if outcome_class == "FAILED":
        return 4
    return 0
