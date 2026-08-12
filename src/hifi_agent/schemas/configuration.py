"""Strict external sample and shared runtime configuration schemas."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hifi_agent.schemas.sample import (
    ExecutionBudgetConfig,
    KmerConfig,
    MappingQcConfig,
    OptimizationConfig,
    OptionalPathList,
    PathList,
    ResourceConfig,
    RuntimeBehaviorConfig,
    ToolName,
)


class RuntimePathsConfig(BaseModel):
    """Shared roots resolved relative to the runtime configuration file."""

    model_config = ConfigDict(extra="forbid")

    data_root: Path
    output_root: Path
    cache_root: Path


class RuntimeToolConfig(BaseModel):
    """Shared tool resolution and governed BUSCO cache behavior."""

    model_config = ConfigDict(extra="forbid")

    executable_overrides: dict[ToolName, Path] = Field(default_factory=dict)
    busco_cache: Path = Path("busco")
    coverage_backend: Literal["auto", "mosdepth", "bedtools"] = "auto"
    download_missing_busco: bool = True


class RuntimeFileConfig(BaseModel):
    """Sample-independent runtime settings loaded by one or more samples."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["hifi-agent-runtime"]
    paths: RuntimePathsConfig
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)
    execution_budget: ExecutionBudgetConfig = Field(default_factory=ExecutionBudgetConfig)
    tools: RuntimeToolConfig = Field(default_factory=RuntimeToolConfig)
    kmer: KmerConfig = Field(default_factory=KmerConfig)
    mapping_qc: MappingQcConfig = Field(default_factory=MappingQcConfig)
    runtime: RuntimeBehaviorConfig = Field(
        default_factory=lambda: RuntimeBehaviorConfig(
            resume_mode="auto",
            retention="standard",
        )
    )


class SampleFileConfig(BaseModel):
    """Scientific facts and input locations for one HiFi sample."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["hifi-agent-sample"]
    runtime_config: Path
    sample_id: str
    output_name: str | None = None
    read_technology: Literal["pacbio_hifi"]
    hifi_reads: PathList
    species_name: str | None = None
    expected_genome_size: int | None = Field(default=None, ge=1)
    ploidy: int | None = Field(default=None, ge=1)
    inbred: bool | None = None
    busco_lineage: str | None = None
    kmer_reads: OptionalPathList = None
    reference_genome: Path | None = None
