"""Sample configuration schema for V1 input validation."""

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

SAMPLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _coerce_path_list(value: object) -> object:
    """Allow a single path string where the public config accepts path/list."""
    if isinstance(value, str | Path):
        return [value]
    return value


def _coerce_optional_path_list(value: object) -> object:
    """Allow null, one path, or a path list for optional read inputs."""
    if value is None:
        return None
    return _coerce_path_list(value)


PathList = Annotated[list[Path], BeforeValidator(_coerce_path_list)]
OptionalPathList = Annotated[list[Path] | None, BeforeValidator(_coerce_optional_path_list)]


class ResourceConfig(BaseModel):
    """Resource limits supplied by the user before workflow execution."""

    model_config = ConfigDict(extra="forbid")

    # Keep a small host reserve on the 512-thread/1-TiB local execution server.
    max_threads: int = Field(default=480, ge=1)
    max_memory_gb: int = Field(default=960, ge=1)


class AgentConfig(BaseModel):
    """Agent retry and candidate budget limits."""

    model_config = ConfigDict(extra="forbid")

    max_retry_rounds: int = Field(default=1, ge=0, le=2)
    max_candidates_per_round: int = Field(default=2, ge=1, le=2)
    objective: Literal["balanced", "contiguity", "completeness", "conservative"] = "balanced"


class KmerConfig(BaseModel):
    """K-mer analysis settings for advisory pre-QC metrics."""

    model_config = ConfigDict(extra="forbid")

    k: int = Field(default=21, ge=15, le=31)
    low_coverage_peak_threshold: float = Field(default=10.0, ge=1.0, le=100.0)


class MappingQcConfig(BaseModel):
    """Conservative read-filter and coverage settings for post-assembly mapping."""

    model_config = ConfigDict(extra="forbid")

    min_read_length: int = Field(default=1000, ge=0)
    min_mean_qscore: float = Field(default=20.0, ge=0.0, le=60.0)
    coverage_window_size: int = Field(default=10_000, ge=100)


class SampleConfig(BaseModel):
    """Validated user-facing sample configuration for a single V1 run."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    hifi_reads: PathList
    outdir: Path
    species_name: str | None = None
    expected_genome_size: int | None = Field(default=None, ge=1)
    ploidy: int | None = Field(default=None, ge=1)
    inbred: bool | None = None
    busco_lineage: str | None = None
    kmer_reads: OptionalPathList = None
    reference_genome: Path | None = None
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    kmer: KmerConfig = Field(default_factory=KmerConfig)
    mapping_qc: MappingQcConfig = Field(default_factory=MappingQcConfig)

    @field_validator("sample_id")
    @classmethod
    def validate_sample_id(cls, value: str) -> str:
        """Require workflow-safe sample identifiers."""
        if not SAMPLE_ID_PATTERN.fullmatch(value):
            raise ValueError("sample_id must use only letters, numbers, underscores, and hyphens")
        return value
