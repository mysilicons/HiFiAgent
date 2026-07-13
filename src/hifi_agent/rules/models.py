"""Validated schemas for deterministic expert rules and decisions."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = bool | int | float | str
Operator = Literal[">", ">=", "<", "<=", "==", "!=", "in", "not_in", "is_null", "not_null"]
Decision = Literal["BASELINE", "STOP", "RETRY"]
RiskLevel = Literal["low", "medium", "medium_high", "high"]
ThresholdLevel = Literal["warning", "action", "acceptance"]
Transform = Literal["identity", "round_int"]

WHITELISTED_PARAMETERS = frozenset(
    {"purge_level", "purge_similarity", "hom_cov", "disable_post_join"}
)


class ThresholdSource(BaseModel):
    """Provenance record shared by one or more threshold entries."""

    model_config = ConfigDict(extra="forbid")

    title: str
    version: str
    kind: Literal["expert_consensus", "tool_documentation", "project_specification"]
    locator: str
    notes: str


class ThresholdEntry(BaseModel):
    """One versioned warning, action, or acceptance threshold."""

    model_config = ConfigDict(extra="forbid")

    value: Scalar
    level: ThresholdLevel
    source_id: str
    source_version: str
    description: str
    conservative: bool = True


class ThresholdCatalog(BaseModel):
    """Complete versioned threshold catalog loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    catalog_version: str
    sources: dict[str, ThresholdSource]
    thresholds: dict[str, ThresholdEntry]


class RulePredicate(BaseModel):
    """Atomic comparison against one normalized rule-context metric."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    op: Operator
    value: Scalar | list[Scalar] | None = None
    threshold: str | None = None

    @model_validator(mode="after")
    def validate_operand(self) -> RulePredicate:
        """Require exactly one operand except for null-check operators."""
        if self.op in {"is_null", "not_null"}:
            if self.value is not None or self.threshold is not None:
                raise ValueError(f"operator {self.op} does not accept an operand")
            return self
        if (self.value is None) == (self.threshold is None):
            raise ValueError("predicate requires exactly one of `value` or `threshold`")
        return self


class ConditionGroup(BaseModel):
    """Recursive boolean group; `all` and `any` may be combined."""

    model_config = ConfigDict(extra="forbid")

    all: list[RulePredicate | ConditionGroup] = Field(default_factory=list)
    any: list[RulePredicate | ConditionGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_clause(self) -> ConditionGroup:
        """Reject empty condition groups that would match everything accidentally."""
        if not self.all and not self.any:
            raise ValueError("condition group requires at least one `all` or `any` clause")
        return self


class CandidateParameterSpec(BaseModel):
    """Static or metric-derived value for one whitelisted parameter."""

    model_config = ConfigDict(extra="forbid")

    value: Scalar | None = None
    from_metric: str | None = None
    from_threshold: str | None = None
    transform: Transform = "identity"

    @model_validator(mode="after")
    def require_value_source(self) -> CandidateParameterSpec:
        """Require exactly one static or dynamic candidate value source."""
        sources = (
            self.value is not None,
            self.from_metric is not None,
            self.from_threshold is not None,
        )
        if sum(sources) != 1:
            raise ValueError(
                "candidate parameter requires one of `value`, `from_metric`, or `from_threshold`"
            )
        return self


class CandidateTemplate(BaseModel):
    """Audited template for one bounded hifiasm retry candidate."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    parameters: dict[str, CandidateParameterSpec]


class ExpertRule(BaseModel):
    """One deterministic, reviewable expert rule."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    priority: int = Field(ge=1, le=100)
    when: ConditionGroup
    decision: Decision
    action: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    reason_codes: list[str] = Field(min_length=1)
    risk_level: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)
    max_candidates: int = Field(default=0, ge=0, le=2)
    evidence_required: list[str] = Field(min_length=1)
    candidates: list[CandidateTemplate] = Field(default_factory=list)
    message: str

    @model_validator(mode="after")
    def validate_candidate_contract(self) -> ExpertRule:
        """Ensure retry/candidate declarations are internally consistent."""
        invalid_reason_codes = [
            code for code in self.reason_codes if re.fullmatch(r"[A-Z][A-Z0-9_]+", code) is None
        ]
        if invalid_reason_codes:
            raise ValueError(f"invalid reason_codes: {invalid_reason_codes}")
        if self.decision == "RETRY" and not self.candidates:
            raise ValueError("RETRY rules require at least one candidate")
        if self.decision != "RETRY" and self.candidates:
            raise ValueError("only RETRY rules may declare candidates")
        if len(self.candidates) > self.max_candidates:
            raise ValueError("candidate count exceeds max_candidates")
        for candidate in self.candidates:
            unknown = set(candidate.parameters) - WHITELISTED_PARAMETERS
            if unknown:
                raise ValueError(f"candidate uses non-whitelisted parameters: {sorted(unknown)}")
        return self


class RuleSet(BaseModel):
    """Versioned collection of expert rules."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    rule_set_version: str
    threshold_catalog_version: str
    rules: list[ExpertRule] = Field(min_length=1)


class CandidateParameters(BaseModel):
    """Strict whitelist and range validation for generated hifiasm parameters."""

    model_config = ConfigDict(extra="forbid")

    purge_level: int | None = Field(default=None, ge=0, le=3)
    purge_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    hom_cov: int | None = Field(default=None, ge=1)
    disable_post_join: bool | None = None

    @model_validator(mode="after")
    def require_parameter(self) -> CandidateParameters:
        """Reject empty retry candidates."""
        if not self.model_dump(exclude_none=True):
            raise ValueError("candidate must set at least one whitelisted parameter")
        return self


class ParameterCandidate(BaseModel):
    """Concrete, validated candidate emitted by a matched rule."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    source_rule_id: str
    parameters: CandidateParameters
    risk_level: RiskLevel


class RuleDecision(BaseModel):
    """Deterministic baseline, stop, or retry decision produced without an LLM."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    decision_id: str
    rule_set_version: str
    threshold_catalog_version: str
    decision: Decision
    action: str
    matched_rule_ids: list[str]
    controlling_rule_ids: list[str]
    reason_codes: list[str]
    evidence: dict[str, Scalar | None]
    candidates: list[ParameterCandidate]
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    conflicts: list[str]
    human_readable_explanation: str
