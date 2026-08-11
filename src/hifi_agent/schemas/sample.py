"""Strict production sample configuration schemas."""

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

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


class OptimizationConfig(BaseModel):
    """Bounded optimization and decision-mode configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_rounds: int = Field(default=3, ge=0, le=3)
    max_candidates_per_round: int = Field(default=1, ge=1, le=2)
    minimum_candidate_runs: int = Field(default=0, ge=0, le=1)
    max_parameter_changes_per_candidate: Literal[1] = 1
    plateau_rounds: Literal[1] = 1
    decision_mode: Literal["rules_only", "hybrid", "llm_disabled"] = "rules_only"
    require_llm: bool = False
    llm_replay_transcript: Path | None = None
    confirm_risk_level: Literal["medium_high", "high"] = "medium_high"
    retain_all_attempts: Literal[True] = True

    @model_validator(mode="after")
    def validate_required_llm_mode(self) -> "OptimizationConfig":
        """A required LLM is meaningful only in hybrid mode."""
        if self.require_llm and self.decision_mode != "hybrid":
            raise ValueError("require_llm=true requires decision_mode=hybrid")
        if self.llm_replay_transcript is not None and self.decision_mode != "hybrid":
            raise ValueError("llm_replay_transcript requires decision_mode=hybrid")
        if self.minimum_candidate_runs and (not self.enabled or self.max_rounds == 0):
            raise ValueError(
                "minimum_candidate_runs requires optimization.enabled=true and max_rounds>=1"
            )
        return self


class ExecutionBudgetConfig(BaseModel):
    """Run-level current budgets applied before any expensive launch."""

    model_config = ConfigDict(extra="forbid")

    max_total_assemblies: int = Field(default=7, ge=1, le=7)
    max_tool_retries: int = Field(default=1, ge=0, le=3)
    max_cpu_hours: float = Field(default=10_000.0, ge=0.0)
    max_walltime_hours: float = Field(default=168.0, ge=0.0)
    min_free_disk_gib: float = Field(default=100.0, ge=0.0)
    max_llm_calls_per_round: int = Field(default=1, ge=0, le=1)
    max_total_llm_calls: int = Field(default=3, ge=0, le=3)

    @model_validator(mode="after")
    def validate_llm_call_limits(self) -> "ExecutionBudgetConfig":
        """The global call budget cannot be smaller than a single-round allowance."""
        if self.max_total_llm_calls < self.max_llm_calls_per_round:
            raise ValueError("max_total_llm_calls must be >= max_llm_calls_per_round")
        return self


ToolName = Literal[
    "java",
    "nextflow",
    "hifiasm",
    "gfatools",
    "seqkit",
    "nanoplot",
    "meryl",
    "quast",
    "busco",
    "merqury",
    "minimap2",
    "samtools",
    "bedtools",
    "mosdepth",
    "rscript",
    "genomescope",
]


class ToolchainConfig(BaseModel):
    """Explicit tool resolution settings; personal-host fallbacks are forbidden."""

    model_config = ConfigDict(extra="forbid")

    executable_overrides: dict[ToolName, Path] = Field(default_factory=dict)
    busco_lineage_dir: Path | None = None
    coverage_backend: Literal["auto", "mosdepth", "bedtools"] = "auto"

    @field_validator("executable_overrides")
    @classmethod
    def validate_override_command_names(cls, value: dict[ToolName, Path]) -> dict[ToolName, Path]:
        """Require override filenames that workflow PATH resolution can consume exactly."""
        expected_names = {
            "nanoplot": {"NanoPlot"},
            "quast": {"quast.py"},
            "merqury": {"merqury.sh"},
            "rscript": {"Rscript"},
            "genomescope": {"genomescope2", "genomescope.R"},
        }
        for name, path in value.items():
            expected = expected_names.get(name, {name})
            if path.name not in expected:
                raise ValueError(
                    f"tools.executable_overrides.{name} must use one of {sorted(expected)!r}"
                )
        return value


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
    """Validated single-sample production configuration."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["hifi-agent"]
    sample_id: str
    read_technology: Literal["pacbio_hifi"]
    input_root_env: str | None = None
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
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)
    execution_budget: ExecutionBudgetConfig = Field(default_factory=ExecutionBudgetConfig)
    tools: ToolchainConfig = Field(default_factory=ToolchainConfig)
    kmer: KmerConfig = Field(default_factory=KmerConfig)
    mapping_qc: MappingQcConfig = Field(default_factory=MappingQcConfig)

    @field_validator("sample_id")
    @classmethod
    def validate_sample_id(cls, value: str) -> str:
        """Require workflow-safe sample identifiers."""
        if not SAMPLE_ID_PATTERN.fullmatch(value):
            raise ValueError("sample_id must use only letters, numbers, underscores, and hyphens")
        return value

    @field_validator("input_root_env")
    @classmethod
    def validate_input_root_env(cls, value: str | None) -> str | None:
        """Restrict portable input roots to an explicit application-owned variable."""
        if value is not None and not re.fullmatch(r"HIFI_AGENT_[A-Z0-9_]+", value):
            raise ValueError("input_root_env must name an HIFI_AGENT_* environment variable")
        return value
