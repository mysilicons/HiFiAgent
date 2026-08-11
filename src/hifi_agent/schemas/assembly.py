"""Production assembly configuration and parameter schemas."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ParameterName = Literal[
    "purge_level",
    "purge_similarity",
    "hom_cov",
    "disable_post_join",
]
RiskLevel = Literal["low", "medium", "medium_high", "high"]


class AssemblyParameters(BaseModel):
    """Complete whitelisted hifiasm parameter set used by every attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    purge_level: int = Field(default=3, ge=0, le=3)
    purge_similarity: float = Field(default=0.55, ge=0.0, le=1.0)
    hom_cov: int | None = Field(default=None, ge=1)
    disable_post_join: bool = False


class AssemblyConfig(BaseModel):
    """Full approved configuration shared by baseline and candidate execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    assembler: Literal["hifiasm"] = "hifiasm"
    input_reads: tuple[Path, ...] = Field(min_length=1)
    threads: int = Field(ge=1)
    parameters: AssemblyParameters = Field(default_factory=AssemblyParameters)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    source_metric_ids: tuple[str, ...] = ()
    risk_level: RiskLevel = "low"

    def parameter_fingerprint(self) -> str:
        """Hash the complete effective parameter set for global deduplication."""
        encoded = json.dumps(
            self.parameters.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


def baseline_assembly_config(
    *,
    reads: list[Path] | tuple[Path, ...],
    threads: int,
) -> AssemblyConfig:
    """Build the explicit full baseline config used by the common executor."""
    return AssemblyConfig(
        input_reads=tuple(path.resolve() for path in reads),
        threads=threads,
        reason_codes=("BASELINE_DEFAULTS",),
    )
