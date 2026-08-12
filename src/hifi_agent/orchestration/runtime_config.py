"""Resolve production sample configuration into one auditable runtime contract."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from hifi_agent.config import ConfigValidationResult, validate_config_file
from hifi_agent.exceptions import InputValidationError
from hifi_agent.schemas.sample import (
    ExecutionBudgetConfig,
    OptimizationConfig,
    SampleConfig,
)

DecisionMode = Literal["rules_only", "hybrid", "llm_disabled"]
ConfigSource = Literal["cli", "sample", "runtime", "config", "default"]


class EffectiveRuntimeConfig(BaseModel):
    """Complete current runtime settings consumed by orchestration services."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    sample: SampleConfig
    optimization: OptimizationConfig
    execution_budget: ExecutionBudgetConfig
    read_technology: Literal["pacbio_hifi"] = "pacbio_hifi"
    read_technology_evidence: Literal["USER_DECLARED_NOT_INFERRED"] = "USER_DECLARED_NOT_INFERRED"

    def maximum_planned_assemblies(self) -> int:
        """Return the bounded maximum allowed by rounds, candidates, and run budget."""
        if not self.optimization.enabled:
            return 1
        theoretical = 1 + (
            self.optimization.max_rounds * self.optimization.max_candidates_per_round
        )
        return min(theoretical, self.execution_budget.max_total_assemblies)

    def optimization_policy(self) -> OptimizationExecutionPolicy:
        """Compile every OptimizationConfig field into executable policy facts."""
        return OptimizationExecutionPolicy.from_config(self.optimization)


class OptimizationExecutionPolicy(BaseModel):
    """Production-facing policy compiled from all current optimization fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    round_indices: tuple[int, ...]
    candidate_indices: tuple[int, ...]
    minimum_candidate_runs: int
    max_parameter_changes_per_candidate: Literal[1]
    plateau_rounds: Literal[1]
    decision_strategy: Literal[
        "RULES_ONLY",
        "DETERMINISTIC_NO_LLM",
        "REQUIRED_LLM",
        "OPTIONAL_LLM_WITH_DETERMINISTIC_FALLBACK",
    ]
    confirmation_risk_levels: tuple[Literal["medium_high", "high"], ...]
    retain_all_attempts: Literal[True]

    @classmethod
    def from_config(cls, config: OptimizationConfig) -> OptimizationExecutionPolicy:
        """Compile every optimization setting into deterministic execution facts."""
        strategies = {
            "rules_only": "RULES_ONLY",
            "llm_disabled": "DETERMINISTIC_NO_LLM",
            "hybrid": (
                "REQUIRED_LLM" if config.require_llm else "OPTIONAL_LLM_WITH_DETERMINISTIC_FALLBACK"
            ),
        }
        confirmation: tuple[Literal["medium_high", "high"], ...] = (
            ("high",) if config.confirm_risk_level == "high" else ("medium_high", "high")
        )
        return cls(
            enabled=config.enabled,
            round_indices=(tuple(range(1, config.max_rounds + 1)) if config.enabled else ()),
            candidate_indices=tuple(range(1, config.max_candidates_per_round + 1)),
            minimum_candidate_runs=config.minimum_candidate_runs,
            max_parameter_changes_per_candidate=config.max_parameter_changes_per_candidate,
            plateau_rounds=config.plateau_rounds,
            decision_strategy=cast(
                Literal[
                    "RULES_ONLY",
                    "DETERMINISTIC_NO_LLM",
                    "REQUIRED_LLM",
                    "OPTIONAL_LLM_WITH_DETERMINISTIC_FALLBACK",
                ],
                strategies[config.decision_mode],
            ),
            confirmation_risk_levels=confirmation,
            retain_all_attempts=config.retain_all_attempts,
        )

    def permits_round(self, round_index: int) -> bool:
        """Return whether the configured optimization budget admits this round."""
        return round_index in self.round_indices

    def permits_candidate(self, candidate_index: int) -> bool:
        """Return whether the candidate coordinate is within the per-round cap."""
        return candidate_index in self.candidate_indices

    def permits_parameter_change_count(self, count: int) -> bool:
        """Enforce the one-variable-per-candidate scientific policy."""
        return 1 <= count <= self.max_parameter_changes_per_candidate

    def plateau_reached(self, consecutive_non_improving_rounds: int) -> bool:
        """Return whether the configured plateau stop condition has fired."""
        return consecutive_non_improving_rounds >= self.plateau_rounds

    def requires_confirmation(self, risk_level: str) -> bool:
        """Return whether the configured risk threshold requires operator consent."""
        return risk_level in self.confirmation_risk_levels


class RuntimePlan(BaseModel):
    """Read-only machine representation printed by ``hifi-agent plan``."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    sample_id: str
    outdir: Path
    decision_mode: DecisionMode
    optimization_enabled: bool
    max_rounds: int
    max_candidates_per_round: int
    maximum_planned_assemblies: int
    optimization_policy: OptimizationExecutionPolicy
    effective_config_sha256: str
    source_map: dict[str, ConfigSource]


@dataclass(frozen=True)
class RuntimeConfigResult:
    """Resolved current configuration plus optional materialized audit paths."""

    validation: ConfigValidationResult
    effective: EffectiveRuntimeConfig
    source_map: dict[str, ConfigSource]
    effective_config_path: Path
    config_sources_path: Path

    def plan(self) -> RuntimePlan:
        """Build a deterministic, read-only execution plan."""
        return RuntimePlan(
            sample_id=self.effective.sample.sample_id,
            outdir=self.effective.sample.outdir,
            decision_mode=self.effective.optimization.decision_mode,
            optimization_enabled=self.effective.optimization.enabled,
            max_rounds=self.effective.optimization.max_rounds,
            max_candidates_per_round=(self.effective.optimization.max_candidates_per_round),
            maximum_planned_assemblies=self.effective.maximum_planned_assemblies(),
            optimization_policy=self.effective.optimization_policy(),
            effective_config_sha256=_sha256_json(self.effective.model_dump(mode="json")),
            source_map=self.source_map,
        )


def resolve_runtime_config(
    config_path: Path,
    *,
    decision_mode_override: DecisionMode | None = None,
    write_outputs: bool = False,
) -> RuntimeConfigResult:
    """Validate and resolve one config without silently accepting semantic conflicts."""
    validation = validate_config_file(config_path, write_outputs=write_outputs)
    config = validation.config

    optimization, optimization_sources = _resolve_optimization(
        config,
        field_sources=validation.field_sources,
        decision_mode_override=decision_mode_override,
    )
    budget, budget_sources = _resolve_budget(
        config,
        field_sources=validation.field_sources,
    )
    effective_sample = config.model_copy(
        update={
            "schema_id": "hifi-agent",
            "read_technology": "pacbio_hifi",
            "optimization": optimization,
            "execution_budget": budget,
        }
    )
    effective = EffectiveRuntimeConfig(
        sample=effective_sample,
        optimization=optimization,
        execution_budget=budget,
    )
    source_map: dict[str, ConfigSource] = {
        **validation.field_sources,
        **optimization_sources,
        **budget_sources,
    }
    effective_path = validation.metadata_dir / "effective_config.json"
    sources_path = validation.metadata_dir / "config_sources.json"
    if write_outputs:
        _atomic_json(effective_path, effective.model_dump(mode="json"))
        _atomic_json(
            sources_path,
            {
                "schema_id": "hifi-agent",
                "sample_id": config.sample_id,
                "sources": source_map,
            },
        )
    return RuntimeConfigResult(
        validation=validation,
        effective=effective,
        source_map=source_map,
        effective_config_path=effective_path,
        config_sources_path=sources_path,
    )


def _resolve_optimization(
    config: SampleConfig,
    *,
    field_sources: Mapping[str, ConfigSource],
    decision_mode_override: DecisionMode | None,
) -> tuple[OptimizationConfig, dict[str, ConfigSource]]:
    updates: dict[str, object] = {}
    if decision_mode_override is not None:
        updates["decision_mode"] = decision_mode_override
    try:
        optimization = OptimizationConfig.model_validate(
            {**config.optimization.model_dump(mode="python"), **updates}
        )
    except ValueError as exc:
        raise InputValidationError(
            f"Effective optimization configuration is invalid: {exc}"
        ) from exc

    sources: dict[str, ConfigSource] = {}
    for field in OptimizationConfig.model_fields:
        key = f"optimization.{field}"
        if field == "decision_mode" and decision_mode_override is not None:
            sources[key] = "cli"
        else:
            sources[key] = field_sources.get(key, "default")
    return optimization, sources


def _resolve_budget(
    config: SampleConfig,
    *,
    field_sources: Mapping[str, ConfigSource],
) -> tuple[ExecutionBudgetConfig, dict[str, ConfigSource]]:
    budget = config.execution_budget
    sources: dict[str, ConfigSource] = {}
    for field in ExecutionBudgetConfig.model_fields:
        key = f"execution_budget.{field}"
        sources[key] = field_sources.get(key, "default")
    return budget, sources


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
