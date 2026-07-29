"""Strict schemas for the Stage 11 V2 benchmark and ablation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class V2DatasetAudit(BaseModel):
    """Identity and structural validation result for one genuine FASTQ."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    species: str
    accession: str
    genome_size_class: str
    role: str
    bytes: int = Field(ge=1)
    read_count: int = Field(ge=1)
    total_bases: int = Field(ge=1)
    checksum_status: Literal["FULL_PASS", "FAIL", "NOT_RUN"]
    checksum_verified: bool
    fastq_header_verified: bool


class V2SafetyScenarioResult(BaseModel):
    """Expected and observed output of one production comparator scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    expected_outcome: str
    observed_outcome: str
    passed: bool


class V2AblationMetrics(BaseModel):
    """Common metric surface for one of the four required ablation groups."""

    model_config = ConfigDict(extra="forbid")

    valid_candidate_rate: float | None
    safety_rejection_rate: float | None
    material_improvement_rate: float
    hard_regression_rate: float
    plateau_stop_accuracy: float
    invalid_duplicate_candidate_rate: float
    average_assembly_count: float
    incremental_cpu_hours: float
    incremental_walltime_hours: float
    incremental_disk_bytes: int = Field(ge=0)
    llm_call_count: int = Field(ge=0)
    llm_prompt_tokens: int = Field(ge=0)
    llm_completion_tokens: int = Field(ge=0)
    llm_failure_fallback_rate: float | None
    final_human_review_agreement: float


class V2AblationResult(BaseModel):
    """Configuration and measured outcome of one required ablation group."""

    model_config = ConfigDict(extra="forbid")

    group_id: Literal["A", "B", "C", "D"]
    label: str
    rules: bool
    rag: bool
    llm_proposals: bool
    multi_round: bool
    metrics: V2AblationMetrics
    interpretation: str


class V2BenchmarkReport(BaseModel):
    """Complete machine-readable Stage 11 acceptance result."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    generated_at: datetime
    result: Literal["PASS", "FAIL"]
    dataset_audits: list[V2DatasetAudit] = Field(min_length=2)
    safety_scenarios: list[V2SafetyScenarioResult] = Field(min_length=5)
    ablations: list[V2AblationResult] = Field(min_length=4, max_length=4)
    real_candida_terminal_outcome: str
    real_candida_candidate_contract: str
    real_candida_candidate_parameter_count: int = Field(ge=1)
    limitations: list[str]
