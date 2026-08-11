"""Persistence and artifact helpers for the production coordinator."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from pydantic import ValidationError

from hifi_agent.decision.models import (
    DecisionContext,
    PreviousRoundOutcome,
    ProposalDecision,
)
from hifi_agent.exceptions import AgentStateError
from hifi_agent.executors.models import AttemptCoordinate
from hifi_agent.orchestration.manifests import (
    AssemblyAttemptRecord,
    ManifestStore,
    RoundRecord,
)
from hifi_agent.qc import QcFeatureBundle, build_attempt_qc_feature_bundle
from hifi_agent.schemas.assembly import AssemblyConfig
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.schemas.sample import SampleConfig

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def proposal_stop(decision: ProposalDecision) -> tuple[str, str, list[str]]:
    """Map an empty governed decision to one terminal contract."""
    rejected = {reason for item in decision.rejected for reason in item.reason_codes}
    if decision.status == "RULE_STOP":
        return "STOP_RULE_DECISION", "SCIENTIFIC", list(decision.reason_codes)
    if decision.status == "FAILED_REQUIRED_LLM":
        return "FAILED_REQUIRED_LLM", "FAILED", list(decision.reason_codes)
    if "RISK_CONFIRMATION_REQUIRED" in rejected:
        return "STOP_CONFIRMATION_REQUIRED", "ACTION_REQUIRED", ["RISK_CONFIRMATION_REQUIRED"]
    if "ASSEMBLY_BUDGET_EXHAUSTED" in rejected:
        return "STOP_BUDGET", "ACTION_REQUIRED", ["ASSEMBLY_BUDGET_EXHAUSTED"]
    return "STOP_NO_LEGAL_CANDIDATE", "SCIENTIFIC", list(decision.reason_codes)


def build_or_verify_qc(
    path: Path,
    run_dir: Path,
    record: AssemblyAttemptRecord,
    sample: SampleConfig,
) -> QcFeatureBundle:
    """Load immutable QC evidence or materialize it once from attempt artifacts."""
    if path.exists():
        return QcFeatureBundle.model_validate_json(path.read_text())
    bundle = build_attempt_qc_feature_bundle(
        run_dir / "02_assembly" / record.relative_directory(),
        sample_id=sample.sample_id,
        reference_available=sample.reference_genome is not None,
    )
    write_or_verify_json(path, bundle.model_dump(mode="json"))
    return bundle


def attempt_manifest_ref(run_dir: Path, record: AssemblyAttemptRecord) -> Path:
    """Return the canonical run-relative attempt manifest reference."""
    return (
        run_dir / "02_assembly" / record.relative_directory() / "attempt_manifest.json"
    ).relative_to(run_dir)


def required_attempt(run_dir: Path, reference: Path | None) -> AssemblyAttemptRecord:
    """Load a required typed attempt reference and fail closed on corruption."""
    if reference is None:
        raise AgentStateError("current state lacks a required attempt manifest reference")
    try:
        return AssemblyAttemptRecord.model_validate_json((run_dir / reference).read_text())
    except (OSError, ValidationError) as exc:
        raise AgentStateError(f"Attempt manifest is invalid: {reference}: {exc}") from exc


def latest_attempt(
    run_dir: Path,
    coordinate: AttemptCoordinate,
) -> AssemblyAttemptRecord | None:
    """Load the latest finalized attempt for one logical coordinate."""
    parent = run_dir / "02_assembly" / coordinate.relative_parent
    manifests = sorted(parent.glob("attempt_*/attempt_manifest.json")) if parent.exists() else []
    if not manifests:
        return None
    try:
        return AssemblyAttemptRecord.model_validate_json(manifests[-1].read_text())
    except (OSError, ValidationError) as exc:
        raise AgentStateError(f"Finalized attempt manifest is invalid: {exc}") from exc


def partial_attempt_exists(run_dir: Path, coordinate: AttemptCoordinate) -> bool:
    """Return whether the newest coordinate directory is not finalized."""
    parent = run_dir / "02_assembly" / coordinate.relative_parent
    attempts = sorted(parent.glob("attempt_*")) if parent.exists() else []
    return bool(attempts and not (attempts[-1] / "attempt_manifest.json").exists())


def pre_qc_exists(run_dir: Path) -> bool:
    """Return whether the immutable pre-QC inventory exists."""
    return (run_dir / "01_pre_qc/artifacts_manifest.json").is_file()


def attempt_config(run_dir: Path, record: AssemblyAttemptRecord) -> AssemblyConfig:
    """Load the full approved configuration for an attempt."""
    if record.approved_config_ref is None:
        raise AgentStateError("Attempt lacks approved configuration")
    try:
        return AssemblyConfig.model_validate_json(
            (run_dir / record.approved_config_ref.relative_path).read_text()
        )
    except (OSError, ValidationError) as exc:
        raise AgentStateError(f"Attempt approved configuration is invalid: {exc}") from exc


def attempt_metrics(run_dir: Path, record: AssemblyAttemptRecord) -> AssemblyMetrics:
    """Load normalized post-QC metrics for an attempt."""
    path = run_dir / "02_assembly" / record.relative_directory() / "post_qc/assembly_metrics.json"
    try:
        return AssemblyMetrics.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        raise AgentStateError(f"Attempt assembly metrics are invalid: {exc}") from exc


def load_context(run_dir: Path, round_index: int) -> DecisionContext:
    """Load the immutable current-incumbent decision context."""
    try:
        return DecisionContext.model_validate_json(
            (
                run_dir / "04_decisions" / f"round_{round_index:02d}" / "decision_context.json"
            ).read_text()
        )
    except (OSError, ValidationError) as exc:
        raise AgentStateError(f"Round decision context is invalid: {exc}") from exc


def proposal_path(run_dir: Path, round_index: int) -> Path:
    """Return the canonical proposal decision path for a round."""
    return run_dir / "04_decisions" / f"round_{round_index:02d}" / "proposal_decision.json"


def load_proposal_decision(run_dir: Path, round_index: int) -> ProposalDecision:
    """Load a typed immutable proposal decision."""
    try:
        return ProposalDecision.model_validate_json(proposal_path(run_dir, round_index).read_text())
    except (OSError, ValidationError) as exc:
        raise AgentStateError(f"Round proposal decision is invalid: {exc}") from exc


def write_or_load_round(
    run_dir: Path,
    manifests: ManifestStore,
    proposed: RoundRecord,
) -> Path:
    """Write a round once, or verify the immutable recovery copy."""
    path = run_dir / "04_decisions" / proposed.round_id / "round_manifest.json"
    if path.exists():
        existing = RoundRecord.model_validate_json(path.read_text())
        if (
            existing.round_outcome != proposed.round_outcome
            or existing.incumbent_after_ref != proposed.incumbent_after_ref
            or existing.comparison_ref != proposed.comparison_ref
        ):
            raise AgentStateError("Immutable round manifest differs during recovery")
        return path
    path = manifests.write_round(proposed)
    manifests.append_history(round_paths=[path])
    return path


def append_unique(values: list[Path], value: Path) -> list[Path]:
    """Append a path while preserving recovery idempotency."""
    return [*values, value] if value not in values else list(values)


def previous_round_outcomes(
    run_dir: Path,
    references: list[Path],
) -> tuple[PreviousRoundOutcome, ...]:
    """Build compact prior incumbent transitions for the next decision context."""
    outcomes: list[PreviousRoundOutcome] = []
    for reference in references:
        record = RoundRecord.model_validate_json((run_dir / reference).read_text())
        if (
            record.round_index == 0
            or record.incumbent_before_ref is None
            or record.incumbent_after_ref is None
        ):
            continue
        before = required_attempt(run_dir, record.incumbent_before_ref.relative_path)
        after = required_attempt(run_dir, record.incumbent_after_ref.relative_path)
        outcomes.append(
            PreviousRoundOutcome(
                round_index=record.round_index,
                incumbent_before_fingerprint=attempt_config(
                    run_dir, before
                ).parameter_fingerprint(),
                incumbent_after_fingerprint=attempt_config(run_dir, after).parameter_fingerprint(),
                outcome=record.round_outcome,
                reason_codes=tuple(record.stop_reason_codes or [record.round_outcome]),
            )
        )
    return tuple(outcomes)


def exclusive_copy(source: Path, destination: Path) -> None:
    """Copy a frozen snapshot with create-once semantics."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with source.open("rb") as input_handle, os.fdopen(descriptor, "wb") as output_handle:
        for chunk in iter(lambda: input_handle.read(1024 * 1024), b""):
            output_handle.write(chunk)
        output_handle.flush()
        os.fsync(output_handle.fileno())


def write_or_verify_json(path: Path, payload: object) -> None:
    """Materialize canonical JSON or verify the existing recovery artifact."""
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text() != content:
            raise AgentStateError(f"Immutable current artifact differs: {path}")
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def code_commit() -> str:
    """Return the exact Git commit used by the run identity when available."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"
    return completed.stdout.strip()
