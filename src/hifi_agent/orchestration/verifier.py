"""Read-only current run verifier for identity, journal, budget, and control-plane links."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hifi_agent.config import verify_recorded_input_checksums
from hifi_agent.exceptions import AgentStateError, InputValidationError, ToolExecutionError
from hifi_agent.executors.hifiasm_contract import (
    RealizedParameters,
    RenderedArgv,
    check_parameter_contract,
)
from hifi_agent.executors.models import ArtifactInventory, CompletionMarker
from hifi_agent.orchestration.budget import BudgetLedger
from hifi_agent.orchestration.comparison import RoundComparison
from hifi_agent.orchestration.identity import IdentityStore
from hifi_agent.orchestration.journal import StateStore
from hifi_agent.orchestration.manifests import (
    AssemblyAttemptRecord,
    ManifestStore,
    RoundRecord,
)
from hifi_agent.orchestration.runtime_models import RunState, sha256_file
from hifi_agent.qc import QcFeatureBundle
from hifi_agent.reporting.models import FinalSummary
from hifi_agent.schemas.assembly import AssemblyConfig


class VerificationCheck(BaseModel):
    """One machine-readable verifier result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str
    status: Literal["PASS", "WARNING", "FAIL"]
    message: str


class VerificationReport(BaseModel):
    """Read-only aggregate returned by ``hifi-agent verify-run``."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    checked_at: datetime
    run_dir: Path
    deep: bool
    status: Literal["PASS", "WARNING", "FAIL"]
    checks: list[VerificationCheck] = Field(min_length=1)


def verify_run(
    run_dir: Path,
    *,
    deep: bool = False,
    rag_index: Path | None = None,
    expected_writer_lock: bool = False,
    verify_reports: bool = True,
) -> VerificationReport:
    """Verify current control-plane artifacts without modifying or recovering the run."""
    root = run_dir.resolve()
    checks: list[VerificationCheck] = []
    identity = None
    state = None
    try:
        identity = IdentityStore(root).verify_snapshots(rag_index=rag_index)
        checks.append(_pass("IDENTITY", "Immutable identity snapshots match"))
    except AgentStateError as exc:
        checks.append(_fail("IDENTITY", str(exc)))

    try:
        state = StateStore(root).verify_read_only()
        checks.append(_pass("STATE_JOURNAL", "State and append-only event journal agree"))
    except AgentStateError as exc:
        checks.append(_fail("STATE_JOURNAL", str(exc)))

    try:
        snapshot = BudgetLedger(root).snapshot()
        if any(value < -1e-12 for value in snapshot.balance.values()):
            raise AgentStateError("current budget ledger contains a negative balance")
        checks.append(
            _pass(
                "BUDGET_LEDGER",
                f"Budget ledger is contiguous through sequence {snapshot.sequence}",
            )
        )
    except AgentStateError as exc:
        checks.append(_fail("BUDGET_LEDGER", str(exc)))

    try:
        history = ManifestStore(root).verify()
        checks.append(
            _pass(
                "MANIFEST_HISTORY",
                f"Manifest history hash chain is valid through sequence {history.sequence}",
            )
        )
    except AgentStateError as exc:
        checks.append(_fail("MANIFEST_HISTORY", str(exc)))

    if identity is not None and state is not None:
        if state.identity == identity:
            checks.append(_pass("IDENTITY_STATE_LINK", "State embeds the immutable run identity"))
        else:
            checks.append(_fail("IDENTITY_STATE_LINK", "State identity differs from metadata"))

    lock_path = root / "05_agent/run.lock"
    if lock_path.exists() and not expected_writer_lock:
        checks.append(
            VerificationCheck(
                check_id="ACTIVE_LOCK",
                status="WARNING",
                message="Run currently has a writer lock; verification remained read-only",
            )
        )
    elif lock_path.exists():
        checks.append(_pass("ACTIVE_LOCK", "Expected coordinator writer lock is present"))
    else:
        checks.append(_pass("ACTIVE_LOCK", "No active writer lock is present"))

    if deep:
        checks.extend(_verify_input_checksums(root))
        checks.extend(_verify_registered_manifests(root))
        checks.extend(_verify_parameter_contracts(root))
        checks.extend(_verify_qc_sources(root))
        if state is not None:
            checks.extend(_verify_incumbent_chain(root, state))
            if verify_reports and state.state.value == "TERMINAL":
                checks.extend(_verify_terminal_reports(root, state))
    else:
        checks.append(
            VerificationCheck(
                check_id="DEEP_ARTIFACTS",
                status="WARNING",
                message="Large attempt artifacts were not re-hashed; use --deep",
            )
        )
    status: Literal["PASS", "WARNING", "FAIL"]
    if any(check.status == "FAIL" for check in checks):
        status = "FAIL"
    elif any(check.status == "WARNING" for check in checks):
        status = "WARNING"
    else:
        status = "PASS"
    return VerificationReport(
        checked_at=datetime.now(UTC),
        run_dir=root,
        deep=deep,
        status=status,
        checks=checks,
    )


def _verify_input_checksums(root: Path) -> list[VerificationCheck]:
    """Re-hash every declared biological and recorded-replay input for deep verification."""
    try:
        verify_recorded_input_checksums(root / "00_metadata/input_checksums.tsv")
    except InputValidationError as exc:
        return [_fail("INPUT_CHECKSUMS", str(exc))]
    return [_pass("INPUT_CHECKSUMS", "All recorded input bytes and SHA-256 values match")]


def require_verification_success(report: VerificationReport) -> None:
    """Raise a normalized error for a failed verification report."""
    if report.status == "FAIL":
        failed = ", ".join(check.check_id for check in report.checks if check.status == "FAIL")
        raise AgentStateError(f"current run verification failed: {failed}")


def _verify_registered_manifests(root: Path) -> list[VerificationCheck]:
    paths = sorted(
        [
            *(root / "02_assembly").glob("**/artifacts_manifest.json"),
            *(root / "02_assembly").glob("**/partial_artifacts_manifest.json"),
        ]
    )
    if not paths:
        return [_pass("DEEP_ARTIFACTS", "No current attempt manifests exist yet")]
    checks: list[VerificationCheck] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(_fail("DEEP_ARTIFACTS", f"Invalid manifest {path}: {exc}"))
            continue
        if not isinstance(payload, dict) or payload.get("schema_id") != "hifi-agent":
            checks.append(_fail("DEEP_ARTIFACTS", f"Unsupported manifest schema: {path}"))
            continue
        try:
            inventory = ArtifactInventory.model_validate(payload)
            attempt_root = path.parent
            if path.name == "artifacts_manifest.json":
                marker = CompletionMarker.model_validate_json(
                    (attempt_root / "COMPLETED.json").read_text()
                )
                if marker.artifacts_manifest_sha256 != sha256_file(path):
                    raise ValueError("completion marker does not bind the inventory")
            for entry in inventory.entries:
                artifact = attempt_root / entry.relative_path
                stat = artifact.stat()
                if (
                    not artifact.is_file()
                    or stat.st_size != entry.bytes
                    or stat.st_mtime_ns != entry.mtime_ns
                    or sha256_file(artifact) != entry.sha256
                ):
                    raise ValueError(f"artifact drift: {entry.relative_path}")
            if path.name == "artifacts_manifest.json":
                registered = {
                    entry.relative_path
                    for entry in inventory.entries
                    if entry.relative_path.parts
                    and entry.relative_path.parts[0]
                    in {"assembly", "post_qc", "contract", "metadata"}
                }
                discovered = {
                    artifact.relative_to(attempt_root)
                    for directory in ("assembly", "post_qc", "contract", "metadata")
                    for artifact in (attempt_root / directory).rglob("*")
                    if artifact.is_file()
                    and artifact.relative_to(attempt_root) != Path("metadata/execution_status.json")
                }
                if discovered != registered:
                    raise ValueError(
                        "unregistered attempt artifact set differs: "
                        f"missing={sorted(map(str, registered - discovered))}, "
                        f"extra={sorted(map(str, discovered - registered))}"
                    )
        except (OSError, ValueError, ToolExecutionError) as exc:
            checks.append(_fail("DEEP_ARTIFACTS", f"Attempt inventory failed: {path}: {exc}"))
            continue
        checks.append(_pass("DEEP_ARTIFACTS", f"Re-hashed registered inventory {path}"))
    return checks


def _verify_parameter_contracts(root: Path) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    for path in sorted((root / "02_assembly").glob("**/attempt_manifest.json")):
        try:
            record = AssemblyAttemptRecord.model_validate_json(path.read_text())
            if not record.comparison_eligible:
                continue
            if (
                record.approved_config_ref is None
                or record.rendered_config_ref is None
                or record.realized_config_ref is None
            ):
                raise ValueError("eligible attempt lacks parameter contract references")
            approved = AssemblyConfig.model_validate_json(
                (root / record.approved_config_ref.relative_path).read_text()
            )
            rendered = RenderedArgv.model_validate_json(
                (root / record.rendered_config_ref.relative_path).read_text()
            )
            realized = RealizedParameters.model_validate_json(
                (root / record.realized_config_ref.relative_path).read_text()
            )
            contract = check_parameter_contract(approved, rendered, realized)
            if contract.status != "PASS":
                raise ValueError("approved/rendered/realized parameters differ")
        except (OSError, ValueError) as exc:
            checks.append(_fail("PARAMETER_CONTRACT", f"{path}: {exc}"))
            continue
        checks.append(_pass("PARAMETER_CONTRACT", f"Verified six-piece contract {path}"))
    return checks or [_pass("PARAMETER_CONTRACT", "No finalized attempt contracts yet")]


def _verify_qc_sources(root: Path) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    for path in sorted((root / "04_decisions").glob("round_*/**/*qc_feature_bundle.json")):
        try:
            bundle = QcFeatureBundle.model_validate_json(path.read_text())
            attempt_root = bundle.attempt_ref.resolve()
            if not attempt_root.is_relative_to((root / "02_assembly").resolve()):
                raise ValueError("QC bundle attempt_ref escapes the current assembly root")
            for relative, expected in bundle.source_sha256.items():
                source = attempt_root / relative
                if not source.is_file() or sha256_file(source) != expected:
                    raise ValueError(f"QC source hash drift: {relative}")
        except (OSError, ValueError) as exc:
            checks.append(_fail("QC_SOURCE_HASH", f"{path}: {exc}"))
            continue
        checks.append(_pass("QC_SOURCE_HASH", f"Verified QC evidence sources {path}"))
    return checks or [_pass("QC_SOURCE_HASH", "No decision QC bundles exist yet")]


def _verify_incumbent_chain(root: Path, state: RunState) -> list[VerificationCheck]:
    try:
        baseline_ref = state.baseline_run_ref
        incumbent_ref = state.incumbent_run_ref
        completed_round_refs = state.completed_round_refs
        if baseline_ref is None:
            if incumbent_ref is not None:
                raise ValueError("incumbent exists without a baseline")
            return [_pass("INCUMBENT_CHAIN", "Run terminated before baseline completion")]
        current = baseline_ref
        for reference in completed_round_refs:
            record = RoundRecord.model_validate_json((root / reference).read_text())
            if record.incumbent_before_ref is not None:
                before = record.incumbent_before_ref.relative_path
                if record.round_index > 0 and before != current:
                    raise ValueError(
                        f"round {record.round_index} incumbent_before does not continue the chain"
                    )
            if record.incumbent_after_ref is not None:
                current = record.incumbent_after_ref.relative_path
            if (
                record.comparison_ref is not None
                and record.comparison_ref.relative_path.name == "comparison.json"
            ):
                comparison = RoundComparison.model_validate_json(
                    (root / record.comparison_ref.relative_path).read_text()
                )
                selected = comparison.selected_attempt_ref or comparison.incumbent_before_ref
                if selected != current:
                    raise ValueError("round comparison selected run differs from incumbent_after")
        if incumbent_ref != current:
            raise ValueError("state incumbent does not match the completed round chain")
    except (OSError, ValueError, AttributeError) as exc:
        return [_fail("INCUMBENT_CHAIN", str(exc))]
    return [_pass("INCUMBENT_CHAIN", "Selected run traces continuously to baseline")]


def _verify_terminal_reports(root: Path, state: RunState) -> list[VerificationCheck]:
    required = (
        Path("06_report/final_report.md"),
        Path("06_report/final_summary.json"),
        Path("06_report/all_runs.tsv"),
        Path("06_report/all_parameters.tsv"),
        Path("06_report/provenance.tsv"),
        Path("06_report/verification_report.json"),
    )
    try:
        report_refs = tuple(state.report_refs)
        if tuple(report_refs) != required:
            raise ValueError("terminal state report_refs differ from the canonical report set")
        if any(not (root / path).is_file() for path in required):
            raise ValueError("one or more canonical terminal report files are missing")
        summary = FinalSummary.model_validate_json(
            (root / "06_report/final_summary.json").read_text()
        )
        if summary.terminal_outcome != state.terminal_outcome:
            raise ValueError("report outcome differs from state")
        if summary.outcome_class != state.outcome_class:
            raise ValueError("report outcome class differs from state")
        if summary.selected_run_ref != state.incumbent_run_ref:
            raise ValueError("report selected run differs from state incumbent")
        with (root / "06_report/all_runs.tsv").open(newline="") as handle:
            run_rows = list(csv.DictReader(handle, delimiter="\t"))
        with (root / "06_report/all_parameters.tsv").open(newline="") as handle:
            parameter_rows = list(csv.DictReader(handle, delimiter="\t"))
        provenance_lines = (root / "06_report/provenance.tsv").read_text().splitlines()
        if len(run_rows) != len(summary.attempts):
            raise ValueError("all_runs.tsv and final_summary attempt counts differ")
        attempts = {item.attempt_id: item for item in summary.attempts}
        for row in run_rows:
            attempt = attempts.get(row.get("attempt_id", ""))
            if attempt is None:
                raise ValueError("all_runs.tsv contains an unknown attempt")
            if (
                row.get("attempt_ref") != str(attempt.attempt_ref)
                or row.get("status") != attempt.status
                or row.get("selected")
                != str(attempt.attempt_ref == summary.selected_run_ref).lower()
                or json.loads(row.get("metrics_json", "{}")) != attempt.metrics
            ):
                raise ValueError("all_runs.tsv differs from final_summary attempt facts")
        expected_parameter_rows = sum(len(item.approved_parameters) for item in summary.attempts)
        if len(parameter_rows) != expected_parameter_rows:
            raise ValueError("all_parameters.tsv and final_summary parameter counts differ")
        for row in parameter_rows:
            attempt = attempts.get(row.get("attempt_id", ""))
            name = row.get("parameter", "")
            if attempt is None or name not in attempt.approved_parameters:
                raise ValueError("all_parameters.tsv contains an unknown parameter row")
            requested_parameters = attempt.requested_config.get("parameters")
            requested = (
                requested_parameters
                if isinstance(requested_parameters, dict)
                else attempt.requested_config
            )
            realized = attempt.realized_parameters or {}
            if (
                json.loads(row.get("requested", "null")) != requested.get(name, "NOT_REQUESTED")
                or json.loads(row.get("approved", "null")) != attempt.approved_parameters[name]
                or tuple(json.loads(row.get("rendered_argv_json", "[]"))) != attempt.rendered_argv
                or json.loads(row.get("realized", "null")) != realized.get(name, "NOT_AVAILABLE")
            ):
                raise ValueError("all_parameters.tsv differs from the parameter contract")
        if not provenance_lines or provenance_lines[0] != "role\trelative_path\tsha256":
            raise ValueError("provenance.tsv header is invalid")
        verification = VerificationReport.model_validate_json(
            (root / "06_report/verification_report.json").read_text()
        )
        if summary.verification_status != verification.status:
            raise ValueError("summary and verification report status differ")
        markdown = (root / "06_report/final_report.md").read_text()
        if (
            summary.terminal_outcome not in markdown
            or str(summary.selected_run_ref or "NOT_AVAILABLE") not in markdown
            or any(str(item) not in markdown for item in summary.incumbent_chain)
            or any(item.proposal_id not in markdown for item in summary.proposals)
        ):
            raise ValueError("Markdown does not contain authoritative JSON outcome/selection")
    except (OSError, ValueError, AttributeError) as exc:
        return [_fail("TERMINAL_REPORTS", str(exc))]
    return [_pass("TERMINAL_REPORTS", "Markdown/JSON/TSV terminal facts agree")]


def _pass(check_id: str, message: str) -> VerificationCheck:
    return VerificationCheck(check_id=check_id, status="PASS", message=message)


def _fail(check_id: str, message: str) -> VerificationCheck:
    return VerificationCheck(check_id=check_id, status="FAIL", message=message)
