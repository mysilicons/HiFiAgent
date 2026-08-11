"""Manifest-driven current QC evidence used by decision contexts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from hifi_agent.exceptions import AgentStateError
from hifi_agent.executors.models import ArtifactInventory
from hifi_agent.orchestration.runtime_models import sha256_file
from hifi_agent.schemas.metrics import AssemblyMetrics

MetricValue = bool | int | float | str | None


class MetricEvidence(BaseModel):
    """One typed QC metric with availability, applicability, and provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    value: MetricValue
    unit: str
    direction: Literal["higher", "lower", "target_one", "fact"]
    tool_version: str | None = None
    availability: Literal["AVAILABLE", "MISSING", "FAILED"]
    applicability: Literal["APPLICABLE", "NOT_APPLICABLE"]
    confidence: Literal["high", "medium", "low", "unavailable"]
    source_sha256: dict[str, str]
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_evidence_state(self) -> MetricEvidence:
        """Keep missing/failed/not-applicable metrics distinct from numeric zero."""
        if self.availability == "AVAILABLE" and self.value is None:
            raise ValueError("available metric requires a value")
        if self.availability != "AVAILABLE" and self.value is not None:
            raise ValueError("missing or failed metric must not use a pseudo-value")
        if self.applicability == "NOT_APPLICABLE" and self.confidence != "unavailable":
            raise ValueError("not-applicable metric must have unavailable confidence")
        return self

    @property
    def trusted_for_decision(self) -> bool:
        """Return whether the metric may support a parameter proposal."""
        return (
            self.availability == "AVAILABLE"
            and self.applicability == "APPLICABLE"
            and self.confidence in {"high", "medium"}
        )


class QcFeatureBundle(BaseModel):
    """Stable set of QC evidence bound to one completed assembly attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    sample_id: str
    attempt_ref: Path
    features: dict[str, MetricEvidence]
    tool_failures: tuple[str, ...] = ()
    known_limitations: tuple[str, ...] = ()
    source_sha256: dict[str, str]

    @model_validator(mode="after")
    def validate_keys(self) -> QcFeatureBundle:
        """Require dictionary keys to be the metric IDs they contain."""
        if any(key != item.metric_id for key, item in self.features.items()):
            raise ValueError("QC feature dictionary keys must match metric IDs")
        return self

    def applicable_metric_ids(self) -> tuple[str, ...]:
        """Return the only metrics eligible to support automated proposals."""
        return tuple(
            sorted(key for key, evidence in self.features.items() if evidence.trusted_for_decision)
        )


def build_attempt_qc_feature_bundle(
    attempt_root: Path,
    *,
    sample_id: str,
    reference_available: bool,
) -> QcFeatureBundle:
    """Build evidence only from checksummed paths declared by an attempt inventory."""
    root = attempt_root.resolve()
    inventory_path = root / "artifacts_manifest.json"
    try:
        inventory = ArtifactInventory.model_validate_json(inventory_path.read_text())
    except (OSError, ValidationError) as exc:
        raise AgentStateError(f"Attempt artifact inventory is invalid: {exc}") from exc
    candidates = [
        entry
        for entry in inventory.entries
        if entry.relative_path == Path("post_qc/assembly_metrics.json")
    ]
    if len(candidates) != 1:
        raise AgentStateError("Inventory must declare exactly one post-QC assembly metrics file")
    entry = candidates[0]
    metrics_path = root / entry.relative_path
    if not metrics_path.is_file() or sha256_file(metrics_path) != entry.sha256:
        raise AgentStateError("Post-QC metrics differ from the attempt inventory")
    try:
        metrics = AssemblyMetrics.model_validate_json(metrics_path.read_text())
    except ValidationError as exc:
        raise AgentStateError(f"Post-QC metrics violate the schema: {exc}") from exc
    failures = tuple(sorted(set(metrics.tool_failures)))
    failure_tools = {failure.split(":", maxsplit=1)[0].lower() for failure in failures}
    features: dict[str, MetricEvidence] = {}
    for field in AssemblyMetrics.model_fields:
        if field in {
            "schema_id",
            "run_id",
            "tool_failures",
            "metric_limitations",
            "metric_classes",
            "tool_versions",
            "tool_metadata",
            "source_files",
        }:
            continue
        value = getattr(metrics, field)
        reference_metric = field in {
            "quast_misassemblies",
            "quast_local_misassemblies",
            "genome_fraction",
            "duplication_ratio",
        }
        applicable = not reference_metric or reference_available
        failed = any(_metric_tool(field) == tool for tool in failure_tools)
        if failed:
            value = None
        availability: Literal["AVAILABLE", "MISSING", "FAILED"] = (
            "FAILED" if failed else ("AVAILABLE" if value is not None else "MISSING")
        )
        if not applicable:
            value = None
            availability = "MISSING"
        features[field] = MetricEvidence(
            metric_id=field,
            value=value,
            unit=_metric_unit(field),
            direction=_metric_direction(field),
            tool_version=metrics.tool_versions.get(_metric_tool(field)),
            availability=availability,
            applicability="APPLICABLE" if applicable else "NOT_APPLICABLE",
            confidence=(
                "unavailable"
                if not applicable or availability != "AVAILABLE"
                else ("medium" if field.startswith("coverage_") else "high")
            ),
            source_sha256={str(entry.relative_path): entry.sha256},
            limitations=(
                ("REFERENCE_REQUIRED",) if not applicable else tuple(metrics.metric_limitations)
            ),
        )
    return QcFeatureBundle(
        sample_id=sample_id,
        attempt_ref=root,
        features=features,
        tool_failures=failures,
        known_limitations=tuple(metrics.metric_limitations),
        source_sha256={
            str(inventory_path.relative_to(root)): sha256_file(inventory_path),
            str(entry.relative_path): entry.sha256,
        },
    )


def _metric_tool(metric_id: str) -> str:
    if metric_id.startswith("busco_"):
        return "busco"
    if metric_id.startswith("quast_") or metric_id in {"genome_fraction", "duplication_ratio"}:
        return "quast"
    if metric_id.startswith("kmer_"):
        return "merqury"
    if metric_id.startswith("coverage_") or metric_id.startswith("mapped_"):
        return "mapping"
    return "assembly"


def _metric_unit(metric_id: str) -> str:
    if metric_id.endswith("fraction") or metric_id.endswith("ratio"):
        return "ratio"
    if metric_id.startswith("busco_") or metric_id in {"genome_fraction", "kmer_completeness"}:
        return "percent"
    if metric_id in {"assembly_size", "contig_n50", "longest_contig"}:
        return "bp"
    if metric_id.startswith("coverage_"):
        return "x"
    return "count"


def _metric_direction(metric_id: str) -> Literal["higher", "lower", "target_one", "fact"]:
    directions: dict[str, Literal["higher", "lower", "target_one"]] = {
        "assembly_size_ratio": "target_one",
        "busco_complete": "higher",
        "busco_duplicated": "lower",
        "kmer_completeness": "higher",
        "kmer_qv": "higher",
        "mapped_read_fraction": "higher",
        "coverage_cv": "lower",
        "contig_n50": "higher",
        "quast_misassemblies": "lower",
    }
    return directions.get(metric_id, "fact")
