"""Validated Stage 12 report and synthetic scenario schemas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hifi_agent.agent.models import AssemblyParameters
from hifi_agent.rules.models import RiskLevel
from hifi_agent.schemas.metrics import AssemblyMetrics

ReportStatus = Literal["SUCCESS", "WARNING", "FAILED", "NOT_RUN"]
MetricValue = bool | int | float | str | None


class ModuleRecord(BaseModel):
    """Success, warning, failure, or not-run status for one report module."""

    model_config = ConfigDict(extra="forbid")

    module: str
    status: ReportStatus
    source_file: str | None = None
    message: str
    limitations: list[str] = Field(default_factory=list)


class ProvenanceRecord(BaseModel):
    """Checksum and role of one source artifact consumed by the report."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    role: str
    path: str
    status: Literal["AVAILABLE", "MISSING", "INVALID"]
    sha256: str | None = None
    byte_size: int | None = None


class MetricRecord(BaseModel):
    """One displayed metric with exact source file and JSON pointer."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    label: str
    value: MetricValue
    unit: str | None = None
    source_file: str
    json_pointer: str
    synthetic: bool = False
    transformation: str | None = None


class InputRecord(BaseModel):
    """Checksum-backed input record with optionally redacted path."""

    model_config = ConfigDict(extra="forbid")

    role: str
    path: str
    sha256: str
    byte_size: int = Field(ge=0)


class SoftwareRecord(BaseModel):
    """Tool version and the artifact from which it was recovered."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    version: str | None
    source_file: str


class ParameterChange(BaseModel):
    """Candidate parameter difference with reason, evidence, risk, and result."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    parameter: str
    baseline_value: MetricValue
    candidate_value: MetricValue
    reason_codes: list[str]
    evidence: dict[str, MetricValue]
    risk_level: RiskLevel
    result: str
    synthetic: bool = False


class AssemblyRunRecord(BaseModel):
    """Baseline, real candidate, or explicitly synthetic candidate report row."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    kind: Literal["baseline", "synthetic_baseline", "candidate", "synthetic_candidate"]
    status: ReportStatus
    parameters: dict[str, MetricValue]
    metrics: dict[str, MetricRecord]
    reason_codes: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    result: str
    synthetic: bool = False


class FinalReportData(BaseModel):
    """Complete machine-readable input to the Stage 12 Jinja2 template."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    report_status: ReportStatus
    sample_id: str
    run_dir: str
    paths_redacted: bool
    scenario_id: str | None = None
    scenario_disclaimer: str | None = None
    sample_config: dict[str, object]
    inputs: list[InputRecord]
    pre_qc_metrics: dict[str, MetricRecord]
    filtering_metrics: dict[str, MetricRecord]
    software_versions: list[SoftwareRecord]
    assembly_runs: list[AssemblyRunRecord]
    parameter_changes: list[ParameterChange]
    rule_facts: dict[str, object]
    agent_summary: dict[str, object]
    optimization_summary: dict[str, object]
    rag_explanation: dict[str, object]
    final_selection: str
    final_selection_reason: str
    warnings: list[str]
    limitations: list[str]
    errors: list[str]
    modules: list[ModuleRecord]
    provenance: list[ProvenanceRecord]
    figures: list[str]
    reproducible_commands: list[str]


class SyntheticTransformation(BaseModel):
    """Auditable transformation from a real metric to one synthetic value."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    operation: Literal["set", "multiply", "derive_ratio"]
    source_value: int | float
    synthetic_value: int | float
    rationale: str


class SyntheticCandidate(BaseModel):
    """Artificial candidate used only to validate Stage 12 reporting."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    parameters: AssemblyParameters
    reason_codes: list[str]
    evidence: dict[str, MetricValue]
    risk_level: RiskLevel
    result: str
    metrics: AssemblyMetrics


class SyntheticReportScenario(BaseModel):
    """Provenance-rich artificial anomaly derived from genuine Candida data."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str
    generated_at: datetime
    synthetic: Literal[True] = True
    disclaimer: str
    source_sample_id: str
    source_run_id: Literal["baseline"] = "baseline"
    source_run_dir: Path
    source_artifacts: dict[str, str]
    source_sha256: dict[str, str]
    transformations: list[SyntheticTransformation]
    candidate: SyntheticCandidate
