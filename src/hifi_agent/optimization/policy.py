"""Versioned Stage 8 metric direction, materiality, and protection policy."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hifi_agent.exceptions import InputValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COMPARISON_POLICY = PROJECT_ROOT / "configs/comparison_policy.yaml"

MetricDirection = Literal["higher", "lower", "target_one"]
ThresholdMode = Literal["absolute", "relative"]
Applicability = Literal["always", "reference", "trusted_genome_size"]


class ComparisonMetricPolicy(BaseModel):
    """One audited metric's selection semantics."""

    model_config = ConfigDict(extra="forbid")

    direction: MetricDirection
    material_delta: float = Field(gt=0)
    material_mode: ThresholdMode = "absolute"
    required: bool
    applicability: Applicability = "always"
    hard_regression_delta: float | None = Field(default=None, gt=0)
    hard_regression_mode: ThresholdMode = "absolute"
    acceptance_min: float | None = None
    acceptance_max: float | None = None
    note: str = Field(min_length=10)

    @model_validator(mode="after")
    def validate_thresholds(self) -> ComparisonMetricPolicy:
        """Reject contradictory lower and upper acceptance bounds."""
        if (
            self.acceptance_min is not None
            and self.acceptance_max is not None
            and self.acceptance_min > self.acceptance_max
        ):
            raise ValueError("acceptance_min cannot exceed acceptance_max")
        return self


class ComparisonPolicy(BaseModel):
    """Complete versioned Stage 8 comparison policy."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    policy_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    metrics: dict[str, ComparisonMetricPolicy] = Field(min_length=1)


def load_comparison_policy(
    path: Path = DEFAULT_COMPARISON_POLICY,
) -> ComparisonPolicy:
    """Load a strict comparison policy without implicit fallback values."""
    try:
        payload = yaml.safe_load(path.read_text())
        return ComparisonPolicy.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise InputValidationError(f"Comparison policy is invalid: {path}: {exc}") from exc
