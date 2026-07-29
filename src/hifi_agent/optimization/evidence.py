"""Checksum-preserving loaders from retained baseline and Stage 7 attempts."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from hifi_agent.agent.models import AssemblyConfig, AssemblyParameters
from hifi_agent.exceptions import InputValidationError
from hifi_agent.executors.candidate import CandidateExecutionReceipt
from hifi_agent.optimization.round_models import ComparableRun
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.schemas.sample import SampleConfig


def load_baseline_comparable(run_dir: Path) -> ComparableRun:
    """Load the genuine baseline as an incumbent without mutating its V1 layout."""
    resolved = run_dir.resolve()
    config_path = resolved / "00_metadata/resolved_config.yaml"
    metrics_path = resolved / "03_post_qc/baseline/assembly_metrics.json"
    manifest_path = resolved / "02_assembly/baseline/metadata/assembly_manifest.json"
    try:
        config = SampleConfig.model_validate(yaml.safe_load(config_path.read_text()))
        metrics = AssemblyMetrics.model_validate_json(metrics_path.read_text())
        manifest = json.loads(manifest_path.read_text())
    except (OSError, yaml.YAMLError, json.JSONDecodeError, ValidationError) as exc:
        raise InputValidationError(f"Baseline comparison evidence is invalid: {exc}") from exc
    assembly_config = AssemblyConfig(
        run_id="baseline",
        input_reads=config.hifi_reads,
        threads=config.resources.max_threads,
        parameters=AssemblyParameters(),
        reason_codes=["BASELINE_DEFAULT"],
        risk_level="low",
    )
    return ComparableRun(
        run_id="baseline",
        attempt_id="baseline_retained",
        config=assembly_config,
        metrics=metrics,
        metrics_path=metrics_path,
        parameter_contract_status="PASS",
        execution_status="COMPLETED",
        cpu_hours=_positive_number(manifest, "cpu_seconds") / 3600,
        walltime_hours=_positive_number(manifest, "real_time_seconds") / 3600,
    )


def load_stage7_comparable(attempt_dir: Path) -> ComparableRun:
    """Load one immutable Stage 7 attempt and its contract status."""
    resolved = attempt_dir.resolve()
    receipt_path = resolved / "stage7_execution.json"
    try:
        receipt = CandidateExecutionReceipt.model_validate_json(receipt_path.read_text())
        run_id = receipt.attempt.run_id
        assembly = receipt.workflow_run_dir / f"02_assembly/{run_id}"
        metrics_path = receipt.workflow_run_dir / f"03_post_qc/{run_id}/assembly_metrics.json"
        config = AssemblyConfig.model_validate_json(
            (assembly / "metadata/approved_config.json").read_text()
        )
        metrics = AssemblyMetrics.model_validate_json(metrics_path.read_text())
        contract = json.loads((assembly / "metadata/parameter_contract_check.json").read_text())
        manifest = json.loads((assembly / "metadata/assembly_manifest.json").read_text())
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise InputValidationError(f"Stage 7 comparison evidence is invalid: {exc}") from exc
    return ComparableRun(
        run_id=run_id,
        attempt_id=receipt.attempt.attempt_id,
        config=config,
        metrics=metrics,
        metrics_path=metrics_path,
        parameter_contract_status=("PASS" if contract.get("status") == "PASS" else "FAIL"),
        execution_status="COMPLETED" if receipt.status == "COMPLETED" else "FAILED",
        cpu_hours=_positive_number(manifest, "cpu_seconds") / 3600,
        walltime_hours=_positive_number(manifest, "real_time_seconds") / 3600,
    )


def _positive_number(payload: dict[str, object], field: str) -> float:
    value = payload.get(field)
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise InputValidationError(f"Assembly manifest has invalid {field}")
    return float(value)
