"""Validated schemas for local knowledge indexing, retrieval, and explanation."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

from hifi_agent.rules.models import CandidateParameters, RiskLevel

ParameterName = Literal["purge_level", "purge_similarity", "hom_cov", "disable_post_join"]
EvidenceLevel = Literal["official", "peer_reviewed", "project_internal"]
AuthorizationScope = Literal["parameter_guidance", "metric_interpretation", "context_only"]


class KnowledgeSource(BaseModel):
    """One allowlisted official document, paper, or project rule source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    title: str
    file_path: Path
    url: str
    version_url: str
    content_kind: Literal[
        "official_documentation",
        "peer_reviewed_paper",
        "project_rule_documentation",
    ]
    tool: str
    tool_version: str
    scope: Literal["v1", "out_of_scope_reference"]
    evidence_level: EvidenceLevel
    authorization_scope: list[AuthorizationScope] = Field(min_length=1)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_after: date
    parameter_tags: list[ParameterName] = Field(default_factory=list)
    problem_tags: list[str] = Field(default_factory=list)
    input_tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_parameter_authority(self) -> KnowledgeSource:
        """Only official parameter-guidance sources may authorize parameter tags."""
        if self.parameter_tags and (
            self.evidence_level != "official"
            or "parameter_guidance" not in self.authorization_scope
        ):
            raise ValueError("parameter tags require official parameter_guidance authority")
        if not self.url.startswith(("https://", "local://")):
            raise ValueError("source URL must use https:// or local://")
        if not self.version_url.startswith(("https://", "local://")):
            raise ValueError("version URL must use https:// or local://")
        if self.tool.lower() == "hifiasm":
            release_version = self.tool_version.split("-r", maxsplit=1)[0]
            if release_version not in self.version_url:
                raise ValueError("hifiasm version URL does not identify the declared release")
        return self


class KnowledgeSourceCatalog(BaseModel):
    """Versioned provenance catalog for all local knowledge inputs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    catalog_version: str
    retrieved_at: date
    target_hifiasm_version: str
    required_parameters: list[ParameterName]
    sources: list[KnowledgeSource] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_official_parameter_coverage(self) -> KnowledgeSourceCatalog:
        """Require official, parameter-authorized evidence for each declared parameter."""
        covered = {
            parameter
            for source in self.sources
            if source.evidence_level == "official"
            and "parameter_guidance" in source.authorization_scope
            for parameter in source.parameter_tags
        }
        missing = sorted(set(self.required_parameters) - covered)
        if missing:
            raise ValueError(f"required parameters lack official evidence: {missing}")
        return self


class IndexedSource(BaseModel):
    """Knowledge source plus checksum captured when the index was built."""

    model_config = ConfigDict(extra="forbid")

    source: KnowledgeSource
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    checksum_verified: Literal[True] = True
    stale: bool


class KnowledgeChunk(BaseModel):
    """Stable, traceable section of one knowledge source."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(pattern=r"^[a-z][a-z0-9_]+_[0-9a-f]{12}$")
    source_id: str
    section: str
    text: str = Field(min_length=20)
    ordinal: int = Field(ge=1)
    parameter_tags: list[ParameterName] = Field(default_factory=list)
    problem_tags: list[str] = Field(default_factory=list)
    input_tags: list[str] = Field(default_factory=list)
    authorized_parameter_tags: list[ParameterName] = Field(default_factory=list)
    quarantined: bool = False
    security_warnings: list[str] = Field(default_factory=list)


class KnowledgeIndex(BaseModel):
    """Portable local full-text index with source provenance."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    catalog_version: str
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_hifiasm_version: str
    parser_version: Literal["2.0"] = "2.0"
    built_at: datetime
    sources: list[IndexedSource]
    chunks: list[KnowledgeChunk] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_registered_chunks(self) -> KnowledgeIndex:
        """Prevent chunks from bypassing the allowlisted source catalog."""
        source_ids = {item.source.source_id for item in self.sources}
        unknown = sorted({chunk.source_id for chunk in self.chunks} - source_ids)
        if unknown:
            raise ValueError(f"index contains unregistered source IDs: {unknown}")
        return self


class KnowledgeIndexManifest(BaseModel):
    """Machine-readable receipt for one V2 index build."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    catalog_version: str
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_hifiasm_version: str
    built_at: datetime
    source_ids: list[str]
    source_sha256: dict[str, str]
    parameter_evidence: dict[ParameterName, list[str]]
    chunk_count: int = Field(ge=1)
    quarantined_chunk_count: int = Field(ge=0)
    warnings: list[str]


class RetrievalHit(BaseModel):
    """One scored local retrieval result exposed to the explanation layer."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    source_id: str
    source_title: str
    source_url: str
    tool: str
    tool_version: str
    section: str
    text: str
    score: float = Field(gt=0.0)
    parameter_tags: list[ParameterName]
    problem_tags: list[str]
    input_tags: list[str] = Field(default_factory=list)
    authorized_parameter_tags: list[ParameterName] = Field(default_factory=list)
    evidence_level: EvidenceLevel = "official"
    authorization_scope: list[AuthorizationScope] = Field(default_factory=list)
    version_match: Literal["exact", "mismatch", "not_applicable"] = "not_applicable"
    warnings: list[str] = Field(default_factory=list)


class RetrievalTrace(BaseModel):
    """Deterministic audit record for one final retrieval result set."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    catalog_version: str
    actual_hifiasm_version: str
    query: str
    parameter_tags: list[ParameterName]
    problem_tags: list[str]
    input_tags: list[str]
    catalog_source_ids: list[str]
    result_source_ids: list[str]
    result_chunk_ids: list[str]
    warnings: list[str]


class RecommendedAction(StrEnum):
    """Only actions the optional explanation layer may emit."""

    KEEP_BASELINE = "KEEP_BASELINE"
    STOP_AND_REVIEW = "STOP_AND_REVIEW"
    RETRY_WHITELISTED_CANDIDATE = "RETRY_WHITELISTED_CANDIDATE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ExplainedParameter(StrEnum):
    """Complete parameter whitelist visible to LLM explanations."""

    PURGE_LEVEL = "purge_level"
    PURGE_SIMILARITY = "purge_similarity"
    HOM_COV = "hom_cov"
    DISABLE_POST_JOIN = "disable_post_join"


class ParameterExplanation(BaseModel):
    """Sourced explanation for a parameter already proposed by deterministic rules."""

    model_config = ConfigDict(extra="forbid")

    parameter: ExplainedParameter
    explanation: str = Field(min_length=10)
    source_ids: list[str] = Field(min_length=1)


class LLMExplanation(BaseModel):
    """Strict structured output accepted from the optional LLM."""

    model_config = ConfigDict(extra="forbid")

    recommended_action: RecommendedAction
    supporting_rule_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=20)
    uncertainties: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    parameter_explanations: list[ParameterExplanation] = Field(default_factory=list)


class RuleFacts(BaseModel):
    """Immutable deterministic facts kept separate from LLM prose."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    decision: Literal["BASELINE", "STOP", "RETRY"]
    action: str
    matched_rule_ids: list[str]
    controlling_rule_ids: list[str]
    reason_codes: list[str]
    evidence: dict[str, bool | int | float | str | None]
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: str
    candidate_parameters: list[dict[str, bool | int | float | str]]


class ExplanationBundle(BaseModel):
    """Stage 10 artifact separating rules, retrieval, and LLM explanation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    rule_facts: RuleFacts
    retrieval_evidence: list[RetrievalHit]
    llm_enabled: bool
    llm_status: Literal["DISABLED", "SUCCESS", "INSUFFICIENT_EVIDENCE", "FAILED"]
    provider: str | None = None
    model: str | None = None
    explanation: LLMExplanation
    safety_checks: list[str]
    api_metadata: dict[str, bool | int | float | str | None] = Field(default_factory=dict)


class RagComparison(BaseModel):
    """Rules-only versus rules+RAG invariant comparison."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    decision_id: str
    rules_only_decision: str
    rules_only_action: str
    rag_recommended_action: RecommendedAction
    decision_changed: bool
    candidate_parameters_changed: bool
    retrieved_source_ids: list[str]
    explanation_added: bool
    safety_status: Literal["PASS", "FAIL"]


class RagTraceEvent(BaseModel):
    """Append-only Stage 10 decision trace event with retrieved evidence IDs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    timestamp: datetime
    decision_id: str
    event: Literal["RAG_EXPLANATION"] = "RAG_EXPLANATION"
    source_ids: list[str]
    chunk_ids: list[str]
    llm_enabled: bool
    llm_status: str
    provider: str | None
    model: str | None
    recommended_action: RecommendedAction
    safety_status: Literal["PASS", "FAIL"]


ProposalValue = StrictBool | StrictInt | StrictFloat
DecisionMode = Literal["rules_only", "hybrid", "llm_disabled"]


class ProposedParameter(BaseModel):
    """One evidence-bound parameter value proposed by an LLM."""

    model_config = ConfigDict(extra="forbid")

    parameter: ParameterName
    value: ProposalValue
    source_ids: list[str] = Field(min_length=1)
    metric_ids: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=10)
    applicability: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    uncertainty: str = Field(min_length=5)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_exact_parameter_type(self) -> ProposedParameter:
        """Prevent bool-as-int and numeric coercion across parameter types."""
        if self.parameter in {"purge_level", "hom_cov"}:
            if not isinstance(self.value, int) or isinstance(self.value, bool):
                raise ValueError(f"{self.parameter} requires an integer value")
        elif self.parameter == "purge_similarity":
            if not isinstance(self.value, float):
                raise ValueError("purge_similarity requires a floating-point value")
        elif not isinstance(self.value, bool):
            raise ValueError("disable_post_join requires a boolean value")
        return self


class LLMParameterProposal(BaseModel):
    """One complete candidate proposed within the Stage 6 JSON envelope."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    parameters: list[ProposedParameter] = Field(min_length=1, max_length=4)
    summary: str = Field(min_length=20)

    @model_validator(mode="after")
    def validate_unique_parameters(self) -> LLMParameterProposal:
        """Reject duplicate parameter declarations instead of silently merging them."""
        names = [item.parameter for item in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("proposal contains duplicate parameter declarations")
        return self


class LLMProposalBundle(BaseModel):
    """Strict, provider-neutral Stage 6 structured LLM output."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    proposals: list[LLMParameterProposal] = Field(max_length=6)
    global_uncertainties: list[str] = Field(default_factory=list)


class ApprovedCandidate(BaseModel):
    """Deterministically approved candidate; Stage 7 may consume only this model."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    origin: Literal["rule", "llm"]
    requested_parameters: CandidateParameters
    approved_parameters: CandidateParameters
    source_ids: list[str] = Field(min_length=1)
    metric_ids: list[str] = Field(min_length=1)
    reason_codes: list[str] = Field(min_length=1)
    risk_level: RiskLevel
    requires_user_confirmation: bool
    confidence: float = Field(ge=0.0, le=1.0)
    parameter_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def prohibit_silent_parameter_changes(self) -> ApprovedCandidate:
        """The arbiter may approve or reject, never rewrite a proposal."""
        if self.requested_parameters != self.approved_parameters:
            raise ValueError("approved parameters must exactly match requested parameters")
        payload = json.dumps(
            self.approved_parameters.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        if self.parameter_fingerprint != hashlib.sha256(payload.encode()).hexdigest():
            raise ValueError("parameter fingerprint does not match approved parameters")
        return self


class RejectedProposal(BaseModel):
    """Auditable rejection of a rule or LLM proposal."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    origin: Literal["rule", "llm"]
    reason_codes: list[str] = Field(min_length=1)
    requested_parameters: dict[str, bool | int | float] = Field(default_factory=dict)


class ProposalDecisionBundle(BaseModel):
    """Complete Stage 6 result with retrieval, provider, approval, and rejection audit."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    decision_id: str
    decision_mode: DecisionMode
    terminal_status: Literal[
        "CANDIDATES_APPROVED",
        "NO_CANDIDATE",
        "STOP_RULE_AUTHORITY",
        "STOP_LLM_REQUIRED",
    ]
    llm_status: Literal[
        "DISABLED",
        "NOT_REQUESTED",
        "NOT_CALLED_RULE_STOP",
        "NOT_CALLED_BUDGET",
        "INSUFFICIENT_EVIDENCE",
        "SUCCESS",
        "FAILED",
    ]
    provider: str | None = None
    model: str | None = None
    prompt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    proposal_output_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    retrieved_evidence: list[RetrievalHit]
    raw_llm_bundle: LLMProposalBundle | None = None
    approved_candidates: list[ApprovedCandidate] = Field(max_length=2)
    rejected_proposals: list[RejectedProposal]
    reason_codes: list[str] = Field(min_length=1)
    safety_checks: list[str]
    api_metadata: dict[str, bool | int | float | str | None] = Field(default_factory=dict)
