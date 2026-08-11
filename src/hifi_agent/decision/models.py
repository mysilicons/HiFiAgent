"""Immutable data contracts for current incumbent-aware proposal decisions."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from hifi_agent.qc import QcFeatureBundle
from hifi_agent.schemas.assembly import AssemblyConfig, ParameterName, RiskLevel
from hifi_agent.schemas.metrics import AssemblyMetrics

DecisionMode = Literal["rules_only", "hybrid", "llm_disabled"]
ProposalValue = StrictBool | StrictInt | StrictFloat | str | None
MetricEffect = Literal["increase", "decrease", "toward_one", "diagnostic"]


class PreviousRoundOutcome(BaseModel):
    """Small immutable fact from an earlier completed round."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    round_index: int = Field(ge=0, le=3)
    incumbent_before_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    incumbent_after_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: str
    reason_codes: tuple[str, ...] = Field(min_length=1)


class DecisionContext(BaseModel):
    """Complete current-incumbent context shared by rules, RAG, LLM, and arbiter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    run_uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    read_technology: Literal["pacbio_hifi"]
    sample_facts: dict[str, bool | int | float | str | None]
    qc_feature_bundle: QcFeatureBundle
    incumbent_attempt_ref: Path
    incumbent_attempt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    incumbent_config: AssemblyConfig
    incumbent_parameter_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    incumbent_metrics: AssemblyMetrics
    incumbent_metric_source_sha256: dict[str, str]
    round_index: int = Field(ge=1, le=3)
    seen_parameter_fingerprints: tuple[str, ...]
    comparison_policy_id: str
    comparison_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    remaining_budget: dict[str, float]
    previous_round_outcomes: tuple[PreviousRoundOutcome, ...] = ()
    applicable_metric_ids: tuple[str, ...]
    known_limitations: tuple[str, ...] = ()
    tool_failures: tuple[str, ...] = ()
    created_at: datetime

    @field_validator("incumbent_attempt_ref")
    @classmethod
    def require_run_relative_ref(cls, value: Path) -> Path:
        """Prevent local absolute paths from leaking into proposal prompts."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("incumbent attempt reference must be run-relative")
        return value

    @model_validator(mode="after")
    def validate_incumbent_and_evidence(self) -> DecisionContext:
        """Bind fingerprints and applicable IDs to the typed incumbent evidence."""
        if self.incumbent_parameter_fingerprint != self.incumbent_config.parameter_fingerprint():
            raise ValueError("incumbent parameter fingerprint does not match its full config")
        expected = set(self.qc_feature_bundle.applicable_metric_ids())
        if not set(self.applicable_metric_ids) <= expected:
            raise ValueError("context marks unavailable QC metrics as applicable")
        if self.round_index > 1 and "baseline" in self.incumbent_attempt_ref.parts:
            raise ValueError("round 2/3 context cannot silently fall back to baseline")
        return self

    def llm_summary(self) -> dict[str, object]:
        """Return a path-free, minimal structured context for one provider call."""
        return {
            "schema_id": self.schema_id,
            "sample_facts": self.sample_facts,
            "round_index": self.round_index,
            "incumbent_parameters": self.incumbent_config.parameters.model_dump(mode="json"),
            "incumbent_fingerprint": self.incumbent_parameter_fingerprint,
            "metrics": {
                metric_id: self.qc_feature_bundle.features[metric_id].value
                for metric_id in self.applicable_metric_ids
            },
            "remaining_budget": self.remaining_budget,
            "previous_round_outcomes": [
                outcome.model_dump(mode="json") for outcome in self.previous_round_outcomes
            ],
            "known_limitations": self.known_limitations,
            "tool_failures": self.tool_failures,
        }


class RawProposal(BaseModel):
    """Untrusted rule or LLM proposal retained before safety validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    origin: Literal["rule", "llm"]
    changes: dict[str, ProposalValue]
    source_ids: tuple[str, ...] = ()
    metric_ids: tuple[str, ...] = ()
    expected_metric_effects: dict[str, MetricEffect]
    rationale: str = ""
    risk_level: RiskLevel = "low"

    @model_validator(mode="after")
    def bind_metric_effects(self) -> RawProposal:
        """Require an explicit predicted direction for every cited metric."""
        if set(self.expected_metric_effects) != set(self.metric_ids):
            raise ValueError("expected_metric_effects must match metric_ids exactly")
        return self


class ProposalDirective(BaseModel):
    """Unified deterministic rule output consumed by every decision mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    directive_id: str
    action: Literal["STOP", "PROPOSE"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    proposals: tuple[RawProposal, ...] = ()

    @model_validator(mode="after")
    def validate_action(self) -> ProposalDirective:
        """A rule STOP is authoritative and cannot carry executable proposals."""
        if self.action == "STOP" and self.proposals:
            raise ValueError("STOP directive cannot carry proposals")
        return self


class AuthorizedEvidence(BaseModel):
    """One governed, checksummed retrieval chunk available to the arbiter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    chunk_id: str
    chunk_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorized_parameters: tuple[ParameterName, ...]
    source_version: str
    target_hifiasm_version: str | None = None
    review_after: date
    text: str


class RetrievalTrace(BaseModel):
    """Governed retrieval lineage, including every filtered source reason."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    query: str
    index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: tuple[AuthorizedEvidence, ...]
    filter_reason_codes: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class LLMProposalEnvelope(BaseModel):
    """Strict top-level schema returned by the optional LLM provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposals: tuple[RawProposal, ...] = ()

    @model_validator(mode="after")
    def require_llm_origin(self) -> LLMProposalEnvelope:
        """Prevent a provider from impersonating deterministic rule lineage."""
        if any(proposal.origin != "llm" for proposal in self.proposals):
            raise ValueError("LLM envelope can contain only origin=llm proposals")
        return self


class LLMCallReceipt(BaseModel):
    """Non-secret provider receipt bound to context, prompt, schema, and output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    call_id: str
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reservation_id: str
    provider: str | None
    model: str | None
    status: Literal["NOT_CALLED", "SUCCESS", "FAILED"]
    attempted_at: datetime | None = None
    prompt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    index_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    schema_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, bool | int | float | str | None] = Field(default_factory=dict)
    failure_reason: str | None = None

    @model_validator(mode="after")
    def require_call_time(self) -> LLMCallReceipt:
        """Successful and failed provider calls require an auditable call time."""
        if self.reservation_id != "NOT_RESERVED" and self.attempted_at is None:
            raise ValueError("attempted LLM calls require attempted_at")
        return self


class ApprovedProposal(BaseModel):
    """Single-change proposal overlaid onto the complete current incumbent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    proposal_id: str
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: Literal["rule", "llm"]
    approved_diff: dict[ParameterName, StrictBool | StrictInt | StrictFloat | None]
    incumbent_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    full_config: AssemblyConfig
    parameter_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_ids: tuple[str, ...] = Field(min_length=1)
    metric_ids: tuple[str, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    risk_level: RiskLevel


class RejectedProposal(BaseModel):
    """Raw proposal plus deterministic rejection reasons."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    proposal: RawProposal
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_codes: tuple[str, ...] = Field(min_length=1)


class ProposalDecision(BaseModel):
    """Complete immutable output of the one current proposal provider interface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    decision_mode: DecisionMode
    require_llm: bool
    max_candidates: int = Field(ge=1, le=2)
    risk_confirmation_granted: bool
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    directive_id: str
    directive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_trace_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: Literal[
        "RULE_STOP",
        "CANDIDATES_APPROVED",
        "NO_LEGAL_CANDIDATE",
        "OPTIONAL_LLM_FALLBACK",
        "FAILED_REQUIRED_LLM",
    ]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    retrieval_trace: RetrievalTrace | None = None
    llm_receipt: LLMCallReceipt
    raw_proposals: tuple[RawProposal, ...]
    approved: tuple[ApprovedProposal, ...]
    rejected: tuple[RejectedProposal, ...]
    raw_proposal_refs: tuple[Path, ...]
    approved_proposal_refs: tuple[Path, ...]
    rejected_proposal_refs: tuple[Path, ...]
