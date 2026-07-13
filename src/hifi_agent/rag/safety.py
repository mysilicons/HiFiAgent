"""Non-bypassable validation for optional LLM explanations."""

from __future__ import annotations

import re

from hifi_agent.exceptions import LLMSafetyError
from hifi_agent.rag.models import LLMExplanation, RecommendedAction, RetrievalHit
from hifi_agent.rules.models import RuleDecision

FLAG_PATTERN = re.compile(r"(?<!\w)(--[a-z][a-z0-9-]*|-[a-zA-Z](?:\d+(?:\.\d+)?)?)")
PARAMETER_TO_FLAGS = {
    "purge_level": {"-l"},
    "purge_similarity": {"-s"},
    "hom_cov": {"--hom-cov"},
    "disable_post_join": {"-u"},
}


def expected_explanation_action(decision: RuleDecision) -> RecommendedAction:
    """Map deterministic rule decisions to the only legal explanation action."""
    if decision.decision == "BASELINE":
        return RecommendedAction.KEEP_BASELINE
    if decision.decision == "RETRY":
        return RecommendedAction.RETRY_WHITELISTED_CANDIDATE
    return RecommendedAction.STOP_AND_REVIEW


def validate_llm_explanation(
    explanation: LLMExplanation,
    *,
    decision: RuleDecision,
    hits: list[RetrievalHit],
) -> list[str]:
    """Reject action, rule, source, parameter, or command-line expansion attempts."""
    expected_action = expected_explanation_action(decision)
    if explanation.recommended_action != expected_action:
        raise LLMSafetyError(
            f"LLM action {explanation.recommended_action} cannot override {expected_action}"
        )
    allowed_rules = set(decision.matched_rule_ids) | set(decision.controlling_rule_ids)
    if (
        not explanation.supporting_rule_ids
        or not set(explanation.supporting_rule_ids) <= allowed_rules
    ):
        raise LLMSafetyError("LLM cited a rule that did not match the deterministic decision")
    allowed_sources = {hit.source_id for hit in hits}
    if not explanation.source_ids or not set(explanation.source_ids) <= allowed_sources:
        unknown_sources = sorted(set(explanation.source_ids) - allowed_sources)
        raise LLMSafetyError(f"LLM cited source ID(s) that were not retrieved: {unknown_sources}")
    cited_hits = [hit for hit in hits if hit.source_id in explanation.source_ids]
    if not any(hit.tool != "HiFiAgent" for hit in cited_hits):
        raise LLMSafetyError("LLM explanation must cite at least one external official source")
    if explanation.confidence > decision.confidence:
        raise LLMSafetyError("LLM confidence cannot exceed the deterministic rule confidence")
    allowed_parameters = {
        parameter
        for candidate in decision.candidates
        for parameter in candidate.parameters.model_dump(exclude_none=True)
    }
    explained_parameters = {
        parameter_explanation.parameter.value
        for parameter_explanation in explanation.parameter_explanations
    }
    if explained_parameters != allowed_parameters:
        raise LLMSafetyError(
            "LLM parameter explanations must exactly match deterministic candidate parameters"
        )
    for parameter_explanation in explanation.parameter_explanations:
        if not set(parameter_explanation.source_ids) <= allowed_sources:
            raise LLMSafetyError("A parameter explanation cited an unretrieved source")
    allowed_flags = {
        flag for parameter in allowed_parameters for flag in PARAMETER_TO_FLAGS[parameter]
    }
    prose = " ".join(
        [
            explanation.explanation,
            *explanation.uncertainties,
            *(item.explanation for item in explanation.parameter_explanations),
        ]
    )
    flags = set(FLAG_PATTERN.findall(prose))
    if not flags <= allowed_flags:
        raise LLMSafetyError(f"LLM introduced command-line parameter token(s): {sorted(flags)}")
    _validate_scientific_claims(prose, decision)
    return [
        "ACTION_MATCHES_RULE_DECISION",
        "RULE_IDS_ARE_MATCHED_RULES",
        "SOURCE_IDS_ARE_RETRIEVED",
        "EXTERNAL_OFFICIAL_SOURCE_CITED",
        "CONFIDENCE_NOT_ABOVE_RULE_CONFIDENCE",
        "PARAMETERS_MATCH_RULE_CANDIDATES",
        "NO_UNAPPROVED_COMMAND_LINE_FLAGS",
        "NUMERIC_UNITS_AND_REASON_SEMANTICS_GROUNDED",
        "RULE_AND_BUDGET_AUTHORITY_UNCHANGED",
    ]


def _validate_scientific_claims(prose: str, decision: RuleDecision) -> None:
    normalized = prose.lower()
    duplicated = decision.evidence.get("busco_duplicated")
    if isinstance(duplicated, int | float) and not isinstance(duplicated, bool):
        incorrectly_scaled = duplicated * 100
        scaled_pattern = rf"\b{re.escape(f'{incorrectly_scaled:g}')}\s*%"
        correct_pattern = rf"\b{re.escape(f'{duplicated:g}')}\s*%"
        if (
            duplicated != 0
            and re.search(scaled_pattern, normalized)
            and not re.search(correct_pattern, normalized)
        ):
            raise LLMSafetyError("LLM incorrectly rescaled an already-percent BUSCO metric")
    if "BUSCO_DUPLICATION_NOT_HIGH" in decision.reason_codes:
        contradiction_patterns = (
            r"busco\s+duplic\w*(?:\s+at\s+\d+(?:\.\d+)?\s*%)?\s+"
            r"(?:is|was|remains)\s+(?:very\s+)?high\b",
            r"busco\s+duplic\w*\s+(?:is\s+)?(?:above|exceeds?)\b",
            r"\bhigh\s+busco\s+duplic\w*",
        )
        if any(re.search(pattern, normalized) for pattern in contradiction_patterns):
            raise LLMSafetyError(
                "LLM contradicted BUSCO_DUPLICATION_NOT_HIGH deterministic evidence"
            )
