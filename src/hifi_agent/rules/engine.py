"""Deterministic Stage 8 expert-rule evaluator and conflict resolver."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from hifi_agent.exceptions import RuleConfigurationError
from hifi_agent.rules.context import RuleContext
from hifi_agent.rules.loader import (
    DEFAULT_RULES,
    DEFAULT_THRESHOLDS,
    load_rule_set,
    load_threshold_catalog,
)
from hifi_agent.rules.models import (
    CandidateParameters,
    CandidateParameterSpec,
    ConditionGroup,
    Decision,
    ExpertRule,
    ParameterCandidate,
    RiskLevel,
    RuleDecision,
    RulePredicate,
    RuleSet,
    Scalar,
    ThresholdCatalog,
)

RISK_ORDER = {"low": 0, "medium": 1, "medium_high": 2, "high": 3}
MAX_GLOBAL_CANDIDATES = 2


class RuleEngine:
    """Evaluate audited rules without shell execution, an LLM, or nondeterminism."""

    def __init__(self, rule_set: RuleSet, thresholds: ThresholdCatalog) -> None:
        self.rule_set = rule_set
        self.thresholds = thresholds
        self._rules_by_id = {rule.rule_id: rule for rule in rule_set.rules}

    def rule_matches(self, rule_id: str, context: RuleContext) -> bool:
        """Evaluate one named rule; primarily useful for rule-level acceptance tests."""
        try:
            rule = self._rules_by_id[rule_id]
        except KeyError as exc:
            raise RuleConfigurationError(f"Unknown rule ID: {rule_id}") from exc
        return self._matches_group(rule.when, context.metric_values())

    def evaluate(self, context: RuleContext) -> RuleDecision:
        """Return one deterministic baseline, stop, or retry decision."""
        metrics = context.metric_values()
        matched = sorted(
            (rule for rule in self.rule_set.rules if self._matches_group(rule.when, metrics)),
            key=lambda rule: (-rule.priority, rule.rule_id),
        )
        if not matched:
            return self._fallback_decision(metrics)

        highest_priority = matched[0].priority
        controlling = [rule for rule in matched if rule.priority == highest_priority]
        conflicts = self._find_control_conflicts(controlling, metrics)
        decision: Decision
        risk_level: RiskLevel
        if conflicts:
            decision = "STOP"
            action = "REQUIRE_HUMAN_REVIEW"
            candidates: list[ParameterCandidate] = []
            risk_level = "high"
            confidence = 0.99
            explanation = "同优先级专家规则产生冲突; 安全策略禁止自动生成候选并要求人工复核。"
        else:
            decision = controlling[0].decision
            action = controlling[0].action
            candidates = (
                self._materialize_candidates(controlling, metrics) if decision == "RETRY" else []
            )
            risk_level = max(
                (rule.risk_level for rule in controlling),
                key=lambda level: RISK_ORDER[level],
            )
            confidence = min(rule.confidence for rule in controlling)
            explanation = " ".join(rule.message for rule in controlling)

        reason_codes = _deduplicate(code for rule in matched for code in rule.reason_codes)
        evidence_keys = _deduplicate(
            evidence for rule in matched for evidence in rule.evidence_required
        )
        evidence = {key: metrics.get(key) for key in evidence_keys}
        decision_id = _decision_id(
            metrics,
            [rule.rule_id for rule in controlling],
            decision,
            [candidate.model_dump(mode="json") for candidate in candidates],
        )
        return RuleDecision(
            decision_id=decision_id,
            rule_set_version=self.rule_set.rule_set_version,
            threshold_catalog_version=self.thresholds.catalog_version,
            decision=decision,
            action=action,
            matched_rule_ids=[rule.rule_id for rule in matched],
            controlling_rule_ids=[rule.rule_id for rule in controlling],
            reason_codes=reason_codes,
            evidence=evidence,
            candidates=candidates,
            confidence=confidence,
            risk_level=risk_level,
            conflicts=conflicts,
            human_readable_explanation=explanation,
        )

    def _matches_group(
        self,
        group: ConditionGroup,
        metrics: dict[str, bool | int | float | str | None],
    ) -> bool:
        all_result = all(self._matches_clause(clause, metrics) for clause in group.all)
        any_result = any(self._matches_clause(clause, metrics) for clause in group.any)
        return all_result and (any_result if group.any else True)

    def _matches_clause(
        self,
        clause: RulePredicate | ConditionGroup,
        metrics: dict[str, bool | int | float | str | None],
    ) -> bool:
        if isinstance(clause, ConditionGroup):
            return self._matches_group(clause, metrics)
        observed = metrics.get(clause.metric)
        expected: Scalar | list[Scalar] | None
        if clause.threshold is not None:
            expected = self.thresholds.thresholds[clause.threshold].value
        else:
            expected = clause.value
        return _compare(observed, clause.op, expected)

    def _find_control_conflicts(
        self,
        controlling: list[ExpertRule],
        metrics: dict[str, bool | int | float | str | None],
    ) -> list[str]:
        conflicts: list[str] = []
        if len({rule.decision for rule in controlling}) > 1:
            conflicts.append("RULE_DECISION_CONFLICT")
        if len({rule.action for rule in controlling}) > 1:
            conflicts.append("RULE_ACTION_CONFLICT")
        assignments: dict[str, Scalar] = {}
        for rule in controlling:
            for candidate in rule.candidates:
                for parameter, spec in candidate.parameters.items():
                    value = self._resolve_candidate_value(spec, metrics)
                    previous = assignments.get(parameter)
                    if previous is not None and previous != value:
                        conflicts.append(f"CANDIDATE_PARAMETER_CONFLICT:{parameter}")
                    assignments[parameter] = value
        candidate_count = sum(len(rule.candidates) for rule in controlling)
        if candidate_count > MAX_GLOBAL_CANDIDATES:
            conflicts.append("GLOBAL_CANDIDATE_BUDGET_EXCEEDED")
        return sorted(set(conflicts))

    def _materialize_candidates(
        self,
        controlling: list[ExpertRule],
        metrics: dict[str, bool | int | float | str | None],
    ) -> list[ParameterCandidate]:
        candidates: list[ParameterCandidate] = []
        for rule in controlling:
            for template in rule.candidates:
                values = {
                    parameter: self._resolve_candidate_value(spec, metrics)
                    for parameter, spec in template.parameters.items()
                }
                try:
                    parameters = CandidateParameters.model_validate(values)
                except ValidationError as exc:
                    raise RuleConfigurationError(
                        f"Rule `{rule.rule_id}` produced an invalid candidate: {exc}"
                    ) from exc
                candidates.append(
                    ParameterCandidate(
                        candidate_id=template.candidate_id,
                        source_rule_id=rule.rule_id,
                        parameters=parameters,
                        risk_level=rule.risk_level,
                    )
                )
        return candidates

    def _resolve_candidate_value(
        self,
        spec: CandidateParameterSpec,
        metrics: dict[str, bool | int | float | str | None],
    ) -> Scalar:
        if spec.from_threshold is not None:
            value: Scalar | None = self.thresholds.thresholds[spec.from_threshold].value
        else:
            value = spec.value if spec.from_metric is None else metrics.get(spec.from_metric)
        return _transform_candidate_value(value, spec.from_metric, spec.transform)

    def _fallback_decision(
        self,
        metrics: dict[str, bool | int | float | str | None],
    ) -> RuleDecision:
        evidence = {
            key: metrics.get(key)
            for key in (
                "assembly_size_ratio",
                "busco_complete",
                "busco_duplicated",
                "mapped_read_fraction",
            )
        }
        return RuleDecision(
            decision_id=_decision_id(metrics, [], "STOP", []),
            rule_set_version=self.rule_set.rule_set_version,
            threshold_catalog_version=self.thresholds.catalog_version,
            decision="STOP",
            action="STOP_INSUFFICIENT_EVIDENCE",
            matched_rule_ids=[],
            controlling_rule_ids=[],
            reason_codes=["NO_EXPERT_RULE_MATCHED"],
            evidence=evidence,
            candidates=[],
            confidence=0.3,
            risk_level="high",
            conflicts=[],
            human_readable_explanation=(
                "没有专家规则能够安全解释当前指标; 停止自动调参并要求人工复核。"
            ),
        )


def load_default_rule_engine(
    rules_path: Path = DEFAULT_RULES,
    thresholds_path: Path = DEFAULT_THRESHOLDS,
) -> RuleEngine:
    """Load the repository's audited default Stage 8 rule engine."""
    thresholds = load_threshold_catalog(thresholds_path)
    rule_set = load_rule_set(rules_path, thresholds=thresholds)
    return RuleEngine(rule_set, thresholds)


def write_rule_decision(decision: RuleDecision, output: Path) -> Path:
    """Write a stable JSON decision artifact."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(decision.model_dump_json(indent=2) + "\n")
    return output


def _compare(
    observed: bool | int | float | str | None,
    operator: str,
    expected: Scalar | list[Scalar] | None,
) -> bool:
    if operator == "is_null":
        return observed is None
    if operator == "not_null":
        return observed is not None
    if observed is None or expected is None:
        return False
    if operator == "==":
        return observed == expected
    if operator == "!=":
        return observed != expected
    if operator == "in":
        return isinstance(expected, list) and observed in expected
    if operator == "not_in":
        return isinstance(expected, list) and observed not in expected
    if isinstance(observed, bool) or isinstance(expected, bool | list):
        return False
    if not isinstance(observed, int | float) or not isinstance(expected, int | float):
        return False
    if operator == ">":
        return observed > expected
    if operator == ">=":
        return observed >= expected
    if operator == "<":
        return observed < expected
    if operator == "<=":
        return observed <= expected
    raise RuleConfigurationError(f"Unsupported operator: {operator}")


def _transform_candidate_value(
    value: Scalar | None,
    from_metric: str | None,
    transform: str,
) -> Scalar:
    if value is None:
        raise RuleConfigurationError(f"Candidate value is unavailable from metric `{from_metric}`")
    if transform == "round_int":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RuleConfigurationError("round_int candidate transform requires a numeric metric")
        return round(value)
    if not isinstance(value, bool | int | float | str):
        raise RuleConfigurationError("Candidate value must be scalar")
    return value


def _deduplicate(values: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def _decision_id(
    metrics: dict[str, bool | int | float | str | None],
    controlling_rule_ids: list[str],
    decision: str,
    candidates: list[dict[str, object]],
) -> str:
    payload = json.dumps(
        {
            "metrics": metrics,
            "controlling_rule_ids": controlling_rule_ids,
            "decision": decision,
            "candidates": candidates,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"D-{hashlib.sha256(payload.encode()).hexdigest()[:12].upper()}"
