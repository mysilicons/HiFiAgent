"""Structured post-assembly metrics produced by phase 7."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssemblyMetrics(BaseModel):
    """Normalized multi-tool metrics for one assembly run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    assembly_size: int | None = None
    contig_count: int | None = None
    contig_n50: int | None = None
    contig_l50: int | None = None
    longest_contig: int | None = None
    quast_misassemblies: int | None = None
    quast_local_misassemblies: int | None = None
    genome_fraction: float | None = None
    duplication_ratio: float | None = None
    busco_complete: float | None = None
    busco_single: float | None = None
    busco_duplicated: float | None = None
    busco_fragmented: float | None = None
    busco_missing: float | None = None
    kmer_qv: float | None = None
    kmer_completeness: float | None = None
    mapped_read_fraction: float | None = None
    coverage_mean: float | None = None
    coverage_median: float | None = None
    coverage_cv: float | None = None
    low_coverage_window_fraction: float | None = None
    high_coverage_window_fraction: float | None = None
    assembly_size_ratio: float | None = None
    tool_failures: list[str] = Field(default_factory=list)
    metric_limitations: list[str] = Field(default_factory=list)
    metric_classes: dict[str, Literal["fact", "derived"]] = Field(default_factory=dict)
    tool_versions: dict[str, str | None] = Field(default_factory=dict)
    source_files: dict[str, str] = Field(default_factory=dict)
