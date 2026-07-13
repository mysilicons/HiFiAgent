"""Normalize run artifacts into one deterministic expert-rule context."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from hifi_agent.exceptions import RuleEvaluationError
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.schemas.sample import SampleConfig


class RuleContext(BaseModel):
    """Metrics and metadata available to the Stage 8 expert rules."""

    model_config = ConfigDict(extra="forbid")

    input_type: str = "pacbio_hifi"
    ploidy: int | None = None
    inbred: bool | None = None
    expected_genome_size: int | None = None
    estimated_genome_size: int | None = None
    estimated_coverage: float | None = None
    kmer_source: str | None = None
    kmer_peak_depth: float | None = None
    genomescope_model_status: str | None = None
    kmer_warning_count: int = 0
    hifiasm_hom_cov: float | None = None
    assembly_size: int | None = None
    assembly_size_ratio: float | None = None
    contig_n50: int | None = None
    quast_mode: str | None = None
    quast_misassemblies: int | None = None
    busco_complete: float | None = None
    busco_duplicated: float | None = None
    kmer_completeness: float | None = None
    mapped_read_fraction: float | None = None
    coverage_cv: float | None = None
    tool_failure_count: int = 0

    def metric_values(self) -> dict[str, bool | int | float | str | None]:
        """Return stored and derived values addressable by rule predicates."""
        values: dict[str, bool | int | float | str | None] = self.model_dump()
        values["genome_size_known"] = (
            self.expected_genome_size is not None or self.estimated_genome_size is not None
        )
        values["trusted_kmer_peak"] = (
            self.kmer_source == "same_data_advisory"
            and self.genomescope_model_status == "success"
            and self.kmer_warning_count == 0
        )
        values["hom_cov_peak_ratio"] = _safe_ratio(
            self.hifiasm_hom_cov,
            self.kmer_peak_depth,
        )
        values["misassemblies_per_100mb"] = _misassemblies_per_100mb(
            self.quast_misassemblies,
            self.assembly_size,
        )
        values["core_metrics_complete"] = all(
            value is not None
            for value in (
                self.assembly_size_ratio,
                self.contig_n50,
                self.busco_complete,
                self.busco_duplicated,
                self.mapped_read_fraction,
            )
        )
        return values


def load_rule_context(run_dir: Path) -> RuleContext:
    """Load validated Stage 2/4/6/7 artifacts from one completed run directory."""
    required = {
        "resolved_config": run_dir / "00_metadata" / "resolved_config.yaml",
        "raw_metrics": run_dir / "01_pre_qc" / "raw_metrics.json",
        "assembly_manifest": (
            run_dir / "02_assembly" / "baseline" / "metadata" / "assembly_manifest.json"
        ),
        "assembly_metrics": run_dir / "03_post_qc" / "baseline" / "assembly_metrics.json",
        "quast_metrics": (run_dir / "03_post_qc" / "baseline" / "quast" / "quast_metrics.json"),
    }
    missing = [f"{name}: {path}" for name, path in required.items() if not path.is_file()]
    if missing:
        raise RuleEvaluationError(f"Rule context artifact(s) missing: {', '.join(missing)}")

    try:
        config_data = yaml.safe_load(required["resolved_config"].read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise RuleEvaluationError(f"Unable to read resolved config: {exc}") from exc
    if not isinstance(config_data, dict):
        raise RuleEvaluationError("resolved_config.yaml must contain a mapping")
    try:
        config = SampleConfig.model_validate(config_data)
    except ValidationError as exc:
        raise RuleEvaluationError(f"Resolved sample config is invalid: {exc}") from exc
    raw = _read_object_json(required["raw_metrics"])
    manifest = _read_object_json(required["assembly_manifest"])
    try:
        assembly = AssemblyMetrics.model_validate_json(required["assembly_metrics"].read_text())
    except (OSError, ValidationError) as exc:
        raise RuleEvaluationError(f"Assembly metrics are invalid: {exc}") from exc
    quast = _read_object_json(required["quast_metrics"])

    return RuleContext(
        input_type="pacbio_hifi",
        ploidy=config.ploidy,
        inbred=config.inbred,
        expected_genome_size=config.expected_genome_size,
        estimated_genome_size=_optional_int(raw.get("estimated_genome_size")),
        estimated_coverage=_optional_float(raw.get("estimated_coverage")),
        kmer_source=_optional_string(raw.get("kmer_source")),
        kmer_peak_depth=_optional_float(raw.get("kmer_peak_depth")),
        genomescope_model_status=_optional_string(raw.get("genomescope_model_status")),
        kmer_warning_count=_kmer_warning_count(raw.get("warnings")),
        hifiasm_hom_cov=_optional_float(manifest.get("homozygous_coverage_threshold")),
        assembly_size=assembly.assembly_size,
        assembly_size_ratio=assembly.assembly_size_ratio,
        contig_n50=assembly.contig_n50,
        quast_mode=_optional_string(quast.get("mode")),
        quast_misassemblies=assembly.quast_misassemblies,
        busco_complete=assembly.busco_complete,
        busco_duplicated=assembly.busco_duplicated,
        kmer_completeness=assembly.kmer_completeness,
        mapped_read_fraction=assembly.mapped_read_fraction,
        coverage_cv=assembly.coverage_cv,
        tool_failure_count=len(assembly.tool_failures),
    )


def _read_object_json(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuleEvaluationError(f"Unable to read JSON object {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuleEvaluationError(f"Expected JSON object: {path}")
    return data


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _misassemblies_per_100mb(count: int | None, assembly_size: int | None) -> float | None:
    if count is None or assembly_size is None or assembly_size <= 0:
        return None
    return count / assembly_size * 100_000_000


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _kmer_warning_count(value: object) -> int:
    if not isinstance(value, list):
        return 0
    return sum(isinstance(item, str) and item.startswith("KMER_") for item in value)
