"""Strict schemas for the cross-stage V2 final report."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = bool | int | float | str | None
EvidenceKind = Literal["FACT", "DERIVED", "RULE_CONCLUSION", "LLM_TEXT"]
RunStatus = Literal["COMPLETED", "FAILED", "REJECTED", "NOT_RUN"]
OutcomeClass = Literal["ACCEPTED", "STOPPED", "FAILED", "INCOMPLETE"]
ParameterContractStatus = Literal["PASS", "FAIL", "MISSING", "NOT_APPLICABLE"]


class V2EvidenceBlock(BaseModel):
    """One explicitly typed fact, derivation, rule conclusion, or LLM statement."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    kind: EvidenceKind
    source: str
    content: dict[str, object]


class V2InputRecord(BaseModel):
    """One checksum-bound input with a redacted display path."""

    model_config = ConfigDict(extra="forbid")

    role: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)


class V2ParameterLineage(BaseModel):
    """Requested through argv parameter lineage for one candidate attempt."""

    model_config = ConfigDict(extra="forbid")

    parameter: str
    requested: Scalar
    approved: Scalar
    rendered: Scalar
    realized: Scalar
    argv_value: Scalar
    contract_status: ParameterContractStatus
    argv_matches_realized: bool | None


class V2RunRecord(BaseModel):
    """One baseline or candidate attempt, including failed and rejected entries."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    attempt_id: str
    round_index: int = Field(ge=0, le=3)
    candidate_index: int | None = Field(default=None, ge=1, le=2)
    kind: Literal["baseline", "candidate", "rejected_proposal"]
    status: RunStatus
    reason_codes: list[str] = Field(default_factory=list)
    failure_category: str | None = None
    error: str | None = None
    parameter_contract_status: ParameterContractStatus
    parameters: list[V2ParameterLineage] = Field(default_factory=list)
    metrics: dict[str, Scalar] = Field(default_factory=dict)
    command: list[str] = Field(default_factory=list)
    cpu_hours: float = Field(default=0.0, ge=0.0)
    walltime_hours: float = Field(default=0.0, ge=0.0)
    disk_bytes: int = Field(default=0, ge=0)
    source: str


class V2LLMRecord(BaseModel):
    """Provider provenance and isolated LLM status/text metadata."""

    model_config = ConfigDict(extra="forbid")

    status: str
    provider: str | None = None
    model: str | None = None
    response_id: str | None = None
    index_sha256: str | None = None
    prompt_sha256: str | None = None
    proposal_output_sha256: str | None = None
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    raw_proposal_count: int = Field(default=0, ge=0)
    rejected_proposal_count: int = Field(default=0, ge=0)


class V2FinalReport(BaseModel):
    """Complete Stage 10 machine-readable report spanning V1 or V2 history."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    generated_at: datetime
    sample_id: str
    compatibility_mode: Literal["V2", "V1_COMPATIBILITY"]
    paths_redacted: bool
    terminal_outcome: str
    outcome_class: OutcomeClass
    optimization_succeeded: bool
    optimization_selected_run_id: str | None
    final_run_id: str | None
    final_assembly_path: str | None
    stop_reason_codes: list[str]
    inputs: list[V2InputRecord]
    pre_qc: dict[str, object]
    baseline_parameters: dict[str, Scalar]
    baseline_metrics: dict[str, Scalar]
    decision_mode: str
    llm: V2LLMRecord
    approved_candidates: list[dict[str, object]]
    rejected_proposals: list[dict[str, object]]
    runs: list[V2RunRecord]
    incumbent_timeline: list[dict[str, object]]
    tools_and_provenance: list[dict[str, object]]
    limitations: list[str]
    review_recommendations: list[str]
    evidence: list[V2EvidenceBlock]

    @model_validator(mode="after")
    def validate_stop_semantics(self) -> V2FinalReport:
        """Forbid a STOP outcome from being presented as successful optimization."""
        if self.terminal_outcome.startswith("STOP_") and (
            self.outcome_class != "STOPPED" or self.optimization_succeeded
        ):
            raise ValueError("STOP outcomes must be classified as unsuccessful STOPPED runs")
        return self
