"""Build a deterministic, confidence-aware QC feature bundle for rules and LLMs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hifi_agent.exceptions import ToolExecutionError
from hifi_agent.schemas.sample import SampleConfig

Confidence = Literal["high", "medium", "low", "unavailable"]
Scalar = bool | int | float | str | None


class MetricEvidence(BaseModel):
    """One normalized QC fact with units, provenance, confidence, and limitations."""

    model_config = ConfigDict(extra="forbid")

    metric_id: str
    value: Scalar
    unit: str
    sources: list[str] = Field(min_length=1)
    confidence: Confidence
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_missing_confidence(self) -> MetricEvidence:
        """Require unavailable confidence exactly when a metric value is missing."""
        if self.value is None and self.confidence != "unavailable":
            raise ValueError("missing QC metric must have unavailable confidence")
        if self.value is not None and self.confidence == "unavailable":
            raise ValueError("available QC metric cannot have unavailable confidence")
        return self


class QcFeatureBundle(BaseModel):
    """Stable pre-QC and user-metadata evidence consumed by later V2 stages."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    sample_id: str
    features: dict[str, MetricEvidence]
    warnings: list[str]
    missing_metrics: list[str]
    tool_failures: list[str]
    kmer_peak_authorizes_hom_cov: bool
    source_sha256: dict[str, str]

    @model_validator(mode="after")
    def validate_feature_keys(self) -> QcFeatureBundle:
        """Ensure feature dictionary keys match their stable metric IDs."""
        mismatched = [key for key, item in self.features.items() if key != item.metric_id]
        if mismatched:
            raise ValueError(f"QC feature keys do not match metric IDs: {mismatched}")
        return self

    def llm_summary(self) -> dict[str, object]:
        """Return a path-free structured summary safe to send to a configured LLM."""
        return {
            "schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "features": {
                metric_id: {
                    "value": evidence.value,
                    "unit": evidence.unit,
                    "confidence": evidence.confidence,
                    "limitations": evidence.limitations,
                }
                for metric_id, evidence in self.features.items()
            },
            "warnings": self.warnings,
            "missing_metrics": self.missing_metrics,
            "tool_failures": self.tool_failures,
            "kmer_peak_authorizes_hom_cov": self.kmer_peak_authorizes_hom_cov,
        }


def build_qc_feature_bundle(
    run_dir: Path,
    *,
    output_path: Path | None = None,
    llm_summary_path: Path | None = None,
) -> QcFeatureBundle:
    """Load normalized pre-QC artifacts, build stable evidence, and write V2 outputs."""
    resolved_run = run_dir.resolve()
    config_path = resolved_run / "00_metadata/resolved_config.yaml"
    raw_path = resolved_run / "01_pre_qc/raw_metrics.json"
    kmer_path = resolved_run / "01_pre_qc/kmer/kmer_metrics.json"
    config = _load_config(config_path)
    raw = _load_object(raw_path, required=True)
    kmer = _load_object(kmer_path, required=False)
    warnings = sorted(
        {
            *_string_list(raw.get("warnings")),
            *_string_list(kmer.get("warnings")),
        }
    )
    features, derived_warnings, hom_cov_authorized = _build_features(config, raw, kmer, warnings)
    warnings = sorted({*warnings, *derived_warnings})
    failures = sorted(set(_string_list(raw.get("tool_failures"))))
    missing = sorted(key for key, value in features.items() if value.value is None)
    source_paths = [config_path, raw_path, *([kmer_path] if kmer_path.is_file() else [])]
    bundle = QcFeatureBundle(
        sample_id=config.sample_id,
        features=features,
        warnings=warnings,
        missing_metrics=missing,
        tool_failures=failures,
        kmer_peak_authorizes_hom_cov=hom_cov_authorized,
        source_sha256={str(path.relative_to(resolved_run)): _sha256(path) for path in source_paths},
    )
    destination = output_path or resolved_run / "01_pre_qc/qc_feature_bundle.json"
    summary_destination = llm_summary_path or resolved_run / "01_pre_qc/qc_llm_summary.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    summary_destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(bundle.model_dump_json(indent=2) + "\n")
    summary_destination.write_text(
        json.dumps(bundle.llm_summary(), indent=2, sort_keys=True) + "\n"
    )
    return bundle


def _build_features(
    config: SampleConfig,
    raw: dict[str, object],
    kmer: dict[str, object],
    warnings: list[str],
) -> tuple[dict[str, MetricEvidence], list[str], bool]:
    config_source = "00_metadata/resolved_config.yaml"
    raw_source = "01_pre_qc/raw_metrics.json"
    kmer_source_file = "01_pre_qc/kmer/kmer_metrics.json"
    kmer_source = _optional_string(raw.get("kmer_source")) or _optional_string(
        kmer.get("kmer_source")
    )
    model_status = _optional_string(raw.get("genomescope_model_status")) or _optional_string(
        kmer.get("genomescope_model_status")
    )
    peak_depth = _optional_number(raw.get("kmer_peak_depth"))
    if peak_depth is None:
        peak_depth = _optional_number(kmer.get("peak_depth"))
    reported_genomescope_size = _positive_int(kmer.get("genomescope_genome_size"))
    if (
        reported_genomescope_size is None
        and raw.get("estimated_genome_size_source") == "genomescope"
    ):
        reported_genomescope_size = _positive_int(raw.get("estimated_genome_size"))
    genomescope_size = reported_genomescope_size if model_status == "success" else None
    kmer_confidence, kmer_limitations = _kmer_confidence(
        kmer_source,
        model_status,
        peak_depth,
        warnings,
        _optional_number(kmer.get("low_coverage_peak_threshold")) or 10.0,
    )
    selected_size, size_confidence, size_limitations, size_warnings = _select_genome_size(
        config.expected_genome_size,
        genomescope_size,
        model_status,
        kmer_confidence,
    )
    total_bases = _positive_int(raw.get("total_bases"))
    coverage = total_bases / selected_size if total_bases is not None and selected_size else None
    coverage_confidence: Confidence = size_confidence if coverage is not None else "unavailable"
    coverage_limitations = list(size_limitations)
    derived_warnings = list(size_warnings)
    mean_qscore = _optional_number(raw.get("mean_qscore"))
    heterozygosity = (
        _optional_number(kmer.get("genomescope_heterozygosity"))
        if model_status == "success"
        else None
    )
    repeat_fraction = (
        _optional_number(kmer.get("genomescope_repeat_fraction"))
        if model_status == "success"
        else None
    )
    if coverage is not None and coverage > 200:
        derived_warnings.append("COVERAGE_EXTREME_HIGH")
        coverage_confidence = "low"
        coverage_limitations.append("COVERAGE_OUTSIDE_TYPICAL_AUTOMATION_RANGE")
    elif coverage is not None and coverage < 15:
        derived_warnings.append("COVERAGE_BELOW_ACTION_THRESHOLD")
        coverage_confidence = "low"
        coverage_limitations.append("COVERAGE_BELOW_AUTOMATION_THRESHOLD")
    if mean_qscore is not None and mean_qscore < 20:
        derived_warnings.append("READ_MEAN_QSCORE_BELOW_20")

    features = {
        "input_status": _evidence(
            "input_status", _optional_string(raw.get("input_status")), "category", raw_source
        ),
        "read_count": _evidence(
            "read_count", _nonnegative_int(raw.get("read_count")), "reads", raw_source
        ),
        "total_bases": _evidence("total_bases", total_bases, "bp", raw_source),
        "mean_read_length": _evidence(
            "mean_read_length",
            _optional_number(raw.get("mean_read_length")),
            "bp",
            raw_source,
        ),
        "read_n50": _evidence("read_n50", _positive_int(raw.get("read_n50")), "bp", raw_source),
        "mean_qscore": _evidence("mean_qscore", mean_qscore, "phred", raw_source),
        "gc_percent": _evidence(
            "gc_percent", _optional_number(raw.get("gc_percent")), "percent", raw_source
        ),
        "expected_genome_size": _evidence(
            "expected_genome_size",
            config.expected_genome_size,
            "bp",
            config_source,
            confidence="medium" if config.expected_genome_size is not None else "unavailable",
            limitations=(
                ["USER_DECLARED_GENOME_SIZE_NOT_INDEPENDENTLY_VERIFIED"]
                if config.expected_genome_size is not None
                else []
            ),
        ),
        "genomescope_genome_size": _evidence(
            "genomescope_genome_size",
            genomescope_size,
            "bp",
            kmer_source_file,
            confidence=(kmer_confidence if genomescope_size is not None else "unavailable"),
            limitations=kmer_limitations,
        ),
        "selected_genome_size": _evidence(
            "selected_genome_size",
            selected_size,
            "bp",
            config_source if config.expected_genome_size is not None else kmer_source_file,
            confidence=size_confidence,
            limitations=size_limitations,
        ),
        "estimated_coverage": _evidence(
            "estimated_coverage",
            coverage,
            "x",
            raw_source,
            confidence=coverage_confidence,
            limitations=coverage_limitations,
        ),
        "kmer_source": _evidence(
            "kmer_source",
            kmer_source,
            "category",
            raw_source,
            confidence="high" if kmer_source is not None else "unavailable",
        ),
        "kmer_peak_depth": _evidence(
            "kmer_peak_depth",
            peak_depth,
            "x",
            kmer_source_file,
            confidence=kmer_confidence if peak_depth is not None else "unavailable",
            limitations=kmer_limitations,
        ),
        "genomescope_model_status": _evidence(
            "genomescope_model_status",
            model_status,
            "category",
            kmer_source_file,
            confidence="high" if model_status is not None else "unavailable",
        ),
        "heterozygosity": _evidence(
            "heterozygosity",
            heterozygosity,
            "percent",
            kmer_source_file,
            confidence=kmer_confidence if heterozygosity is not None else "unavailable",
            limitations=kmer_limitations,
        ),
        "repeat_fraction": _evidence(
            "repeat_fraction",
            repeat_fraction,
            "fraction",
            kmer_source_file,
            confidence=kmer_confidence if repeat_fraction is not None else "unavailable",
            limitations=kmer_limitations,
        ),
        "ploidy": _evidence(
            "ploidy",
            config.ploidy,
            "copies",
            config_source,
            confidence="high" if config.ploidy is not None else "unavailable",
            limitations=["USER_DECLARED_METADATA"] if config.ploidy is not None else [],
        ),
        "inbred": _evidence(
            "inbred",
            config.inbred,
            "boolean",
            config_source,
            confidence="high" if config.inbred is not None else "unavailable",
            limitations=["USER_DECLARED_METADATA"] if config.inbred is not None else [],
        ),
        "reference_available": _evidence(
            "reference_available",
            config.reference_genome is not None,
            "boolean",
            config_source,
            confidence="high",
            limitations=["REFERENCE_COMPATIBILITY_NOT_ASSESSED"]
            if config.reference_genome is not None
            else [],
        ),
    }
    hom_cov_authorized = (
        kmer_source == "independent_high_confidence"
        and kmer_confidence == "high"
        and peak_depth is not None
        and model_status == "success"
    )
    return features, derived_warnings, hom_cov_authorized


def _select_genome_size(
    expected: int | None,
    genomescope: int | None,
    model_status: str | None,
    kmer_confidence: Confidence,
) -> tuple[int | None, Confidence, list[str], list[str]]:
    limitations: list[str] = []
    warnings: list[str] = []
    if expected is not None:
        confidence: Confidence = "medium"
        limitations.append("USER_DECLARED_GENOME_SIZE_NOT_INDEPENDENTLY_VERIFIED")
        if genomescope is not None:
            relative_difference = abs(expected - genomescope) / expected
            if relative_difference > 0.25:
                confidence = "low"
                warnings.append("GENOME_SIZE_ESTIMATES_CONFLICT")
                limitations.append("EXPECTED_AND_GENOMESCOPE_SIZE_DIFFER_GT_25_PERCENT")
        return expected, confidence, limitations, warnings
    if genomescope is not None and model_status == "success":
        limitations.append("GENOMESCOPE_DERIVED_GENOME_SIZE")
        return genomescope, kmer_confidence, limitations, warnings
    return None, "unavailable", ["GENOME_SIZE_UNAVAILABLE"], ["GENOME_SIZE_UNAVAILABLE"]


def _kmer_confidence(
    source: str | None,
    model_status: str | None,
    peak_depth: float | None,
    warnings: list[str],
    low_peak_threshold: float,
) -> tuple[Confidence, list[str]]:
    limitations: list[str] = []
    if source is None or peak_depth is None:
        return "unavailable", ["KMER_EVIDENCE_UNAVAILABLE"]
    confidence: Confidence = "high" if source == "independent_high_confidence" else "low"
    if source == "same_data_advisory":
        limitations.append("KMER_SOURCE_SAME_HIFI_READS_NOT_INDEPENDENT")
    if model_status != "success":
        confidence = "low"
        limitations.append("GENOMESCOPE_MODEL_NOT_SUCCESSFUL")
    if peak_depth < low_peak_threshold or "KMER_LOW_COVERAGE_PEAK" in warnings:
        confidence = "low"
        limitations.append("KMER_PEAK_BELOW_TRUST_THRESHOLD")
    if "KMER_MULTIPLE_COMPARABLE_PEAKS" in warnings:
        confidence = "low"
        limitations.append("KMER_MULTIPLE_COMPARABLE_PEAKS")
    if "KMER_NO_CLEAR_PEAK" in warnings:
        confidence = "low"
        limitations.append("KMER_NO_CLEAR_PEAK")
    return confidence, sorted(set(limitations))


def _evidence(
    metric_id: str,
    value: Scalar,
    unit: str,
    source: str,
    *,
    confidence: Confidence | None = None,
    limitations: list[str] | None = None,
) -> MetricEvidence:
    resolved_confidence: Confidence = confidence or ("high" if value is not None else "unavailable")
    return MetricEvidence(
        metric_id=metric_id,
        value=value,
        unit=unit,
        sources=[source],
        confidence=resolved_confidence,
        limitations=limitations or [],
    )


def _load_config(path: Path) -> SampleConfig:
    try:
        data = yaml.safe_load(path.read_text())
        return SampleConfig.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ToolExecutionError(f"QC resolved config is invalid: {path}: {exc}") from exc


def _load_object(path: Path, *, required: bool) -> dict[str, object]:
    if not path.is_file() and not required:
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolExecutionError(f"QC JSON artifact is invalid: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolExecutionError(f"QC JSON artifact must contain an object: {path}")
    return data


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _positive_int(value: object) -> int | None:
    number = _optional_number(value)
    return round(number) if number is not None and number > 0 else None


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
