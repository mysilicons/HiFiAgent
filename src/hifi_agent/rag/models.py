"""Validated schemas for local knowledge indexing, retrieval, and explanation."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeSource(BaseModel):
    """One allowlisted official document, paper, or project rule source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    title: str
    file_path: Path
    url: str
    content_kind: Literal[
        "official_documentation",
        "peer_reviewed_paper",
        "project_rule_documentation",
    ]
    tool: str
    tool_version: str
    scope: Literal["v1", "out_of_scope_reference"]


class KnowledgeSourceCatalog(BaseModel):
    """Versioned provenance catalog for all local knowledge inputs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    catalog_version: str
    retrieved_at: date
    sources: list[KnowledgeSource] = Field(min_length=1)


class IndexedSource(BaseModel):
    """Knowledge source plus checksum captured when the index was built."""

    model_config = ConfigDict(extra="forbid")

    source: KnowledgeSource
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=1)
    chunk_count: int = Field(ge=1)


class KnowledgeChunk(BaseModel):
    """Stable, traceable section of one knowledge source."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(pattern=r"^[a-z][a-z0-9_]+_[0-9a-f]{12}$")
    source_id: str
    section: str
    text: str = Field(min_length=20)
    ordinal: int = Field(ge=1)
    parameter_tags: list[str] = Field(default_factory=list)
    problem_tags: list[str] = Field(default_factory=list)


class KnowledgeIndex(BaseModel):
    """Portable local full-text index with source provenance."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    catalog_version: str
    parser_version: Literal["1.0"] = "1.0"
    built_at: datetime
    sources: list[IndexedSource]
    chunks: list[KnowledgeChunk] = Field(min_length=1)


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
    parameter_tags: list[str]
    problem_tags: list[str]


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
