"""Load and cross-validate versioned expert thresholds and rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from hifi_agent.exceptions import RuleConfigurationError
from hifi_agent.rules.context import RuleContext
from hifi_agent.rules.models import (
    CandidateParameters,
    ConditionGroup,
    ExpertRule,
    RulePredicate,
    RuleSet,
    ThresholdCatalog,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_THRESHOLDS = PROJECT_ROOT / "configs" / "thresholds.yaml"
DEFAULT_RULES = PROJECT_ROOT / "rules" / "v1_rules.yaml"
DERIVED_METRICS = frozenset(
    {
        "genome_size_known",
        "trusted_kmer_peak",
        "hom_cov_peak_ratio",
        "misassemblies_per_100mb",
        "core_metrics_complete",
    }
)


def load_threshold_catalog(path: Path = DEFAULT_THRESHOLDS) -> ThresholdCatalog:
    """Load thresholds and verify every entry's source and source version."""
    data = _load_yaml_object(path)
    try:
        catalog = ThresholdCatalog.model_validate(data)
    except ValidationError as exc:
        raise RuleConfigurationError(f"Threshold catalog is invalid: {path}: {exc}") from exc
    for threshold_id, entry in catalog.thresholds.items():
        source = catalog.sources.get(entry.source_id)
        if source is None:
            raise RuleConfigurationError(
                f"Threshold `{threshold_id}` references unknown source `{entry.source_id}`"
            )
        if source.version != entry.source_version:
            raise RuleConfigurationError(
                f"Threshold `{threshold_id}` source version {entry.source_version} does not match "
                f"catalog source version {source.version}"
            )
    return catalog


def load_rule_set(
    path: Path = DEFAULT_RULES,
    *,
    thresholds: ThresholdCatalog,
) -> RuleSet:
    """Load rules and cross-check IDs, metrics, thresholds, and catalog version."""
    data = _load_yaml_object(path)
    try:
        rule_set = RuleSet.model_validate(data)
    except ValidationError as exc:
        raise RuleConfigurationError(f"Rule set is invalid: {path}: {exc}") from exc
    if rule_set.threshold_catalog_version != thresholds.catalog_version:
        raise RuleConfigurationError(
            "Rule set threshold version does not match loaded threshold catalog: "
            f"{rule_set.threshold_catalog_version} != {thresholds.catalog_version}"
        )
    rule_ids = [rule.rule_id for rule in rule_set.rules]
    if len(rule_ids) != len(set(rule_ids)):
        raise RuleConfigurationError("Rule IDs must be unique")
    allowed_metrics = set(RuleContext.model_fields) | set(DERIVED_METRICS)
    for rule in rule_set.rules:
        _validate_rule_references(rule, thresholds, allowed_metrics)
    return rule_set


def _validate_rule_references(
    rule: ExpertRule,
    thresholds: ThresholdCatalog,
    allowed_metrics: set[str],
) -> None:
    for predicate in _iter_predicates(rule.when):
        if predicate.metric not in allowed_metrics:
            raise RuleConfigurationError(
                f"Rule `{rule.rule_id}` references unknown metric `{predicate.metric}`"
            )
        if predicate.threshold is not None and predicate.threshold not in thresholds.thresholds:
            raise RuleConfigurationError(
                f"Rule `{rule.rule_id}` references unknown threshold `{predicate.threshold}`"
            )
    for evidence in rule.evidence_required:
        if evidence not in allowed_metrics:
            raise RuleConfigurationError(
                f"Rule `{rule.rule_id}` requires unknown evidence `{evidence}`"
            )
    for candidate in rule.candidates:
        for parameter, spec in candidate.parameters.items():
            if spec.from_metric is not None and spec.from_metric not in allowed_metrics:
                raise RuleConfigurationError(
                    f"Rule `{rule.rule_id}` candidate references unknown metric "
                    f"`{spec.from_metric}`"
                )
            if spec.from_threshold is not None and spec.from_threshold not in thresholds.thresholds:
                raise RuleConfigurationError(
                    f"Rule `{rule.rule_id}` candidate references unknown threshold "
                    f"`{spec.from_threshold}`"
                )
            if spec.value is not None:
                _validate_static_candidate(rule.rule_id, parameter, spec.value)
            elif spec.from_threshold is not None:
                threshold_value = thresholds.thresholds[spec.from_threshold].value
                _validate_static_candidate(rule.rule_id, parameter, threshold_value)


def _iter_predicates(group: ConditionGroup) -> list[RulePredicate]:
    predicates: list[RulePredicate] = []
    for clause in [*group.all, *group.any]:
        if isinstance(clause, RulePredicate):
            predicates.append(clause)
        else:
            predicates.extend(_iter_predicates(clause))
    return predicates


def _validate_static_candidate(rule_id: str, parameter: str, value: object) -> None:
    try:
        CandidateParameters.model_validate({parameter: value})
    except ValidationError as exc:
        raise RuleConfigurationError(
            f"Rule `{rule_id}` candidate value for `{parameter}` is invalid: {exc}"
        ) from exc


def _load_yaml_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuleConfigurationError(f"Rule configuration file does not exist: {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise RuleConfigurationError(
            f"Rule configuration is not valid YAML: {path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RuleConfigurationError(f"Rule configuration must contain a mapping: {path}")
    return data
