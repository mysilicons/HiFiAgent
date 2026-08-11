"""Common, immutable current attempt executor for baseline and candidates."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from hifi_agent.exceptions import AgentStateError, InterruptedExecutionError, ToolExecutionError
from hifi_agent.executors.hifiasm_contract import (
    check_parameter_contract,
    display_command,
    parse_hifiasm_argv,
    render_hifiasm_argv,
)
from hifi_agent.executors.models import (
    ArtifactInventory,
    ArtifactInventoryEntry,
    AssemblyInputManifest,
    AttemptCoordinate,
    CompletionMarker,
    ExecutionEstimate,
    ExecutionStatus,
    PostQcContract,
    WorkflowInvocation,
    WorkflowResult,
)
from hifi_agent.orchestration.budget import BudgetAction, BudgetLedger, BudgetResource
from hifi_agent.orchestration.manifests import (
    AssemblyAttemptRecord,
    ManifestReference,
    ManifestStore,
    ResourceUsage,
)
from hifi_agent.orchestration.runtime_models import sha256_file
from hifi_agent.schemas.assembly import AssemblyConfig
from hifi_agent.schemas.sample import SampleConfig


class AssemblyWorkflowRunner(Protocol):
    """Execution port implemented by Nextflow and portable fixture runners."""

    def run(self, invocation: WorkflowInvocation) -> WorkflowResult:
        """Execute assembly plus homologous post-QC in one attempt root."""


class AssemblyExecutor:
    """Own attempt allocation, command contract, budget, inventory, and completion."""

    def __init__(
        self,
        run_dir: Path,
        *,
        sample: SampleConfig,
        inputs: AssemblyInputManifest,
        environment_manifest_sha256: str,
        budget: BudgetLedger,
        manifests: ManifestStore,
        runner: AssemblyWorkflowRunner,
        hifiasm_executable: str = "hifiasm",
    ) -> None:
        self.run_dir = run_dir.resolve()
        self.sample = sample
        self.inputs = inputs
        self.environment_manifest_sha256 = environment_manifest_sha256
        self.budget = budget
        self.manifests = manifests
        self.runner = runner
        self.hifiasm_executable = hifiasm_executable

    def execute(
        self,
        *,
        coordinate: AttemptCoordinate,
        requested_config: Mapping[str, object],
        approved_config: AssemblyConfig,
        resume: bool = False,
        retry: bool = False,
        estimate: ExecutionEstimate | None = None,
    ) -> AssemblyAttemptRecord | None:
        """Execute or resume one attempt; interruptions deliberately return no final manifest."""
        self._validate_approved(approved_config)
        attempt_index, retry_parent = self._select_attempt(
            coordinate,
            approved_config=approved_config,
            resume=resume,
            retry=retry,
        )
        attempt_id = _attempt_id(coordinate, attempt_index)
        attempt_root = (
            self.run_dir
            / "02_assembly"
            / coordinate.relative_parent
            / f"attempt_{attempt_index:03d}"
        )
        for directory in ("metadata", "contract", "workflow", "assembly", "post_qc"):
            (attempt_root / directory).mkdir(parents=True, exist_ok=True)

        contract_dir = attempt_root / "contract"
        requested_path = contract_dir / "requested_config.json"
        approved_path = contract_dir / "approved_config.json"
        rendered_path = contract_dir / "rendered_argv.json"
        command_path = contract_dir / "hifiasm_command.txt"
        realized_path = contract_dir / "realized_parameters.json"
        check_path = contract_dir / "parameter_contract_check.json"
        post_qc_path = attempt_root / "metadata/post_qc_contract.json"
        status_path = attempt_root / "metadata/execution_status.json"

        rendered = render_hifiasm_argv(
            approved_config,
            executable=self.hifiasm_executable,
            output_prefix=f"{self.sample.sample_id}.{coordinate.logical_run_id}",
        )
        post_qc = PostQcContract.from_sample(self.sample)
        _write_or_verify_json(
            requested_path,
            {"schema_id": "hifi-agent", "requested": dict(requested_config)},
        )
        _write_or_verify_json(approved_path, approved_config.model_dump(mode="json"))
        _write_or_verify_json(rendered_path, rendered.model_dump(mode="json"))
        _write_or_verify_text(command_path, display_command(rendered.argv) + "\n")
        _write_or_verify_json(post_qc_path, post_qc.model_dump(mode="json"))

        active_estimate = estimate or ExecutionEstimate()
        reservations = self._reserve_attempt(
            attempt_id,
            coordinate=coordinate,
            retry=retry,
            estimate=active_estimate,
        )
        started_at, resume_count = _start_status(status_path, attempt_id, resume=resume)
        invocation = WorkflowInvocation(
            coordinate=coordinate,
            attempt_id=attempt_id,
            attempt_root=attempt_root,
            sample=self.sample,
            approved_config=approved_config,
            inputs=self.inputs,
            post_qc_contract=post_qc,
            rendered_hifiasm_argv=rendered.argv,
            resume=resume,
        )
        try:
            result = self.runner.run(invocation)
        except InterruptedExecutionError as exc:
            _update_status(
                status_path,
                attempt_id,
                started_at,
                "INTERRUPTED",
                resume_count=resume_count,
                error=str(exc),
            )
            return None
        except (ToolExecutionError, OSError) as exc:
            self._settle_after_launch(reservations, ResourceUsage())
            record = self._finalize_ineligible(
                coordinate=coordinate,
                attempt_index=attempt_index,
                attempt_id=attempt_id,
                attempt_root=attempt_root,
                started_at=started_at,
                retry_parent=retry_parent,
                requested_path=requested_path,
                approved_path=approved_path,
                rendered_path=rendered_path,
                realized_path=None,
                status="FAILED",
                reason_codes=["ASSEMBLY_OR_POST_QC_TOOL_FAILURE"],
                error=str(exc),
            )
            _update_status(
                status_path,
                attempt_id,
                started_at,
                "FAILED",
                resume_count=resume_count,
                error=str(exc),
            )
            return record

        try:
            self._validate_runner_artifacts(attempt_root, result)
            realized = parse_hifiasm_argv(result.realized_hifiasm_argv)
            contract = check_parameter_contract(approved_config, rendered, realized)
            _exclusive_json(realized_path, realized.model_dump(mode="json"))
            _exclusive_json(check_path, contract.model_dump(mode="json"))
        except (ToolExecutionError, OSError) as exc:
            self._settle_after_launch(reservations, result.resource_usage)
            record = self._finalize_ineligible(
                coordinate=coordinate,
                attempt_index=attempt_index,
                attempt_id=attempt_id,
                attempt_root=attempt_root,
                started_at=started_at,
                retry_parent=retry_parent,
                requested_path=requested_path,
                approved_path=approved_path,
                rendered_path=rendered_path,
                realized_path=None,
                status="FAILED",
                reason_codes=["INVALID_WORKFLOW_RESULT"],
                error=str(exc),
                resource_usage=result.resource_usage,
                command=list(result.realized_hifiasm_argv),
                tool_versions=result.tool_versions,
            )
            _update_status(
                status_path,
                attempt_id,
                started_at,
                "FAILED",
                resume_count=resume_count,
                error=str(exc),
            )
            return record
        self._settle_after_launch(reservations, result.resource_usage)
        if contract.status != "PASS":
            record = self._finalize_ineligible(
                coordinate=coordinate,
                attempt_index=attempt_index,
                attempt_id=attempt_id,
                attempt_root=attempt_root,
                started_at=started_at,
                retry_parent=retry_parent,
                requested_path=requested_path,
                approved_path=approved_path,
                rendered_path=rendered_path,
                realized_path=realized_path,
                status="CONTRACT_VIOLATION",
                reason_codes=list(contract.reason_codes),
                error="Actual hifiasm argv differs from the approved current config",
                resource_usage=result.resource_usage,
                command=list(result.realized_hifiasm_argv),
                tool_versions=result.tool_versions,
            )
            _update_status(
                status_path,
                attempt_id,
                started_at,
                "FAILED",
                resume_count=resume_count,
                error=record.error,
            )
            return record

        inventory_path = self._write_inventory(attempt_id, attempt_root)
        marker = CompletionMarker(
            attempt_id=attempt_id,
            completed_at=datetime.now(UTC),
            artifacts_manifest_sha256=sha256_file(inventory_path),
            parameter_contract_sha256=sha256_file(check_path),
        )
        marker_path = attempt_root / "COMPLETED.json"
        _exclusive_json(marker_path, marker.model_dump(mode="json"))
        completed_at = marker.completed_at
        record = AssemblyAttemptRecord(
            attempt_id=attempt_id,
            logical_run_id=coordinate.logical_run_id,
            round_id=coordinate.round_id,
            round_index=coordinate.round_index,
            candidate_index=coordinate.candidate_index,
            attempt_index=attempt_index,
            status="COMPLETED",
            requested_config_ref=ManifestReference.from_path(self.run_dir, requested_path),
            approved_config_ref=ManifestReference.from_path(self.run_dir, approved_path),
            rendered_config_ref=ManifestReference.from_path(self.run_dir, rendered_path),
            realized_config_ref=ManifestReference.from_path(self.run_dir, realized_path),
            command=list(result.realized_hifiasm_argv),
            tool_versions=result.tool_versions,
            environment_manifest_sha256=self.environment_manifest_sha256,
            started_at=started_at,
            completed_at=completed_at,
            resource_usage=result.resource_usage.model_copy(
                update={"artifact_bytes": _inventory_bytes(inventory_path)}
            ),
            artifacts_inventory_ref=ManifestReference.from_path(self.run_dir, inventory_path),
            completion_marker_ref=ManifestReference.from_path(self.run_dir, marker_path),
            retry_parent_attempt_id=retry_parent,
            comparison_eligible=True,
        )
        manifest_path = self.manifests.write_attempt(record)
        self.manifests.append_history(attempt_paths=[manifest_path])
        _update_status(
            status_path,
            attempt_id,
            started_at,
            "COMPLETED",
            resume_count=resume_count,
        )
        return record

    def verify_completed_attempt(self, record: AssemblyAttemptRecord) -> None:
        """Re-hash inventory and completion evidence before comparison."""
        if not record.comparison_eligible or record.completion_marker_ref is None:
            raise AgentStateError("Attempt is not comparison eligible")
        attempt_root = self.run_dir / "02_assembly" / record.relative_directory()
        inventory_path = attempt_root / "artifacts_manifest.json"
        marker_path = attempt_root / "COMPLETED.json"
        try:
            inventory = ArtifactInventory.model_validate_json(inventory_path.read_text())
            marker = CompletionMarker.model_validate_json(marker_path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"Attempt completion evidence is invalid: {exc}") from exc
        if marker.artifacts_manifest_sha256 != sha256_file(inventory_path):
            raise AgentStateError("Attempt inventory hash differs from completion marker")
        for entry in inventory.entries:
            path = attempt_root / entry.relative_path
            if (
                not path.is_file()
                or path.stat().st_size != entry.bytes
                or path.stat().st_mtime_ns != entry.mtime_ns
                or sha256_file(path) != entry.sha256
            ):
                raise AgentStateError(f"Attempt artifact inventory drift: {entry.relative_path}")

    def _validate_approved(self, approved: AssemblyConfig) -> None:
        expected_reads = tuple(path.resolve() for path in self.sample.hifi_reads)
        if tuple(path.resolve() for path in approved.input_reads) != expected_reads:
            raise ToolExecutionError("Approved assembly reads differ from validated current inputs")
        if approved.threads > self.sample.resources.max_threads:
            raise ToolExecutionError("Approved assembly threads exceed current resource limits")

    def _select_attempt(
        self,
        coordinate: AttemptCoordinate,
        *,
        approved_config: AssemblyConfig,
        resume: bool,
        retry: bool,
    ) -> tuple[int, str | None]:
        if resume and retry:
            raise AgentStateError("resume and retry are mutually exclusive")
        parent = self.run_dir / "02_assembly" / coordinate.relative_parent
        attempts = sorted(parent.glob("attempt_[0-9][0-9][0-9]")) if parent.exists() else []
        if not attempts:
            if retry:
                raise AgentStateError("Tool retry requires a prior failed attempt")
            return 1, None
        latest = attempts[-1]
        latest_index = int(latest.name.removeprefix("attempt_"))
        manifest_path = latest / "attempt_manifest.json"
        if resume:
            if manifest_path.exists():
                raise AgentStateError("A finalized attempt cannot be resumed")
            self._assert_same_config(latest, approved_config)
            return latest_index, None
        if retry:
            try:
                record = AssemblyAttemptRecord.model_validate_json(manifest_path.read_text())
            except (OSError, ValidationError) as exc:
                raise AgentStateError("Retry requires a valid finalized failed attempt") from exc
            if record.status not in {"FAILED", "CONTRACT_VIOLATION"}:
                raise AgentStateError("Tool retry requires the latest attempt to have failed")
            self._assert_same_config(latest, approved_config)
            return latest_index + 1, record.attempt_id
        raise AgentStateError("Attempt directory already exists; use resume or retry explicitly")

    def _assert_same_config(self, attempt_root: Path, approved: AssemblyConfig) -> None:
        try:
            previous = AssemblyConfig.model_validate_json(
                (attempt_root / "contract/approved_config.json").read_text()
            )
        except (OSError, ValidationError) as exc:
            raise AgentStateError("Existing attempt approved config is invalid") from exc
        if previous != approved:
            raise AgentStateError("Resume/retry cannot change the approved assembly config")

    def _reserve_attempt(
        self,
        attempt_id: str,
        *,
        coordinate: AttemptCoordinate,
        retry: bool,
        estimate: ExecutionEstimate,
    ) -> dict[BudgetResource, str]:
        round_id = coordinate.round_id
        reservations: dict[BudgetResource, str] = {}
        resources = (
            (BudgetResource.ASSEMBLY, 1.0),
            (BudgetResource.CPU_HOURS, estimate.cpu_hours),
            (BudgetResource.WALLTIME_HOURS, estimate.walltime_hours),
        )
        active_ids: set[str] = set()
        for entry in self.budget.load_entries():
            if entry.reservation_id is None:
                continue
            if entry.action == BudgetAction.RESERVE:
                active_ids.add(entry.reservation_id)
            elif entry.action in {BudgetAction.COMMIT, BudgetAction.RELEASE}:
                active_ids.discard(entry.reservation_id)
        snapshot = self.budget.snapshot()
        for resource, amount in resources:
            reservation_id = f"{attempt_id}:{resource.value.lower()}"
            if reservation_id not in active_ids and amount > snapshot.balance[resource] + 1e-12:
                raise AgentStateError(
                    f"current budget exhausted for {resource.value} before attempt launch"
                )
        disk_id = f"{attempt_id}:disk_gib"
        if disk_id not in active_ids:
            limits = self.budget.load_limits()
            usable_disk = (
                estimate.observed_free_gib
                - limits.min_free_disk_gib
                - snapshot.reserved[BudgetResource.DISK_GIB]
            )
            if estimate.artifact_gib > usable_disk + 1e-12:
                raise AgentStateError("current disk budget exhausted before attempt launch")
        retry_id = f"{attempt_id}:tool_retry"
        if (
            retry
            and retry_id not in active_ids
            and 1.0 > snapshot.balance[BudgetResource.TOOL_RETRY] + 1e-12
        ):
            raise AgentStateError("current tool retry budget exhausted before attempt launch")
        for resource, amount in resources:
            if amount <= 0:
                continue
            reservation_id = f"{attempt_id}:{resource.value.lower()}"
            self.budget.reserve(
                resource,
                amount,
                reservation_id=reservation_id,
                reason_code="ATTEMPT_PRELAUNCH",
                round_id=round_id,
                attempt_id=attempt_id,
            )
            reservations[resource] = reservation_id
        self.budget.reserve_disk(
            estimate.artifact_gib,
            observed_free_gib=estimate.observed_free_gib,
            reservation_id=disk_id,
            reason_code="ATTEMPT_PRELAUNCH",
            round_id=round_id,
            attempt_id=attempt_id,
        )
        reservations[BudgetResource.DISK_GIB] = disk_id
        if retry:
            self.budget.reserve(
                BudgetResource.TOOL_RETRY,
                1,
                reservation_id=retry_id,
                reason_code="TOOL_RETRY_PRELAUNCH",
                round_id=round_id,
                attempt_id=attempt_id,
            )
            reservations[BudgetResource.TOOL_RETRY] = retry_id
        return reservations

    def _settle_after_launch(
        self,
        reservations: dict[BudgetResource, str],
        usage: ResourceUsage,
    ) -> None:
        actual = {
            BudgetResource.ASSEMBLY: 1.0,
            BudgetResource.CPU_HOURS: usage.cpu_hours,
            BudgetResource.WALLTIME_HOURS: usage.walltime_hours,
            BudgetResource.TOOL_RETRY: 1.0,
        }
        for resource, reservation_id in reservations.items():
            if resource == BudgetResource.DISK_GIB:
                self.budget.release(reservation_id, reason_code="ATTEMPT_DISK_ACCOUNTED")
            else:
                self.budget.commit(
                    reservation_id,
                    actual[resource],
                    reason_code="ATTEMPT_ACTUAL_USAGE",
                )

    def _validate_runner_artifacts(
        self,
        attempt_root: Path,
        result: WorkflowResult,
    ) -> None:
        if result.post_qc_contract_id != "post-qc":
            raise ToolExecutionError("Runner used a non-homologous post-QC contract")
        resolved_root = attempt_root.resolve()
        resolved = []
        for artifact in result.artifacts:
            path = artifact.resolve()
            if not path.is_file() or not path.is_relative_to(resolved_root):
                raise ToolExecutionError(f"Runner returned an invalid attempt artifact: {path}")
            resolved.append(path)
        if not any(path.is_relative_to(resolved_root / "assembly") for path in resolved):
            raise ToolExecutionError("Runner returned no assembly artifact")
        if not any(path.is_relative_to(resolved_root / "post_qc") for path in resolved):
            raise ToolExecutionError("Runner returned no post-QC artifact")

    def _write_inventory(
        self,
        attempt_id: str,
        attempt_root: Path,
        *,
        filename: str = "artifacts_manifest.json",
    ) -> Path:
        excluded = {
            Path("artifacts_manifest.json"),
            Path("partial_artifacts_manifest.json"),
            Path("COMPLETED.json"),
            Path("attempt_manifest.json"),
            Path("metadata/execution_status.json"),
        }
        entries = []
        for path in sorted(attempt_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(attempt_root)
            if relative in excluded or relative.is_relative_to(Path("workflow/work")):
                continue
            stat = path.stat()
            entries.append(
                ArtifactInventoryEntry(
                    relative_path=relative,
                    bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    sha256=sha256_file(path),
                )
            )
        inventory = ArtifactInventory(
            attempt_id=attempt_id,
            created_at=datetime.now(UTC),
            entries=tuple(entries),
        )
        path = attempt_root / filename
        _exclusive_json(path, inventory.model_dump(mode="json"))
        return path

    def _finalize_ineligible(
        self,
        *,
        coordinate: AttemptCoordinate,
        attempt_index: int,
        attempt_id: str,
        attempt_root: Path,
        started_at: datetime,
        retry_parent: str | None,
        requested_path: Path,
        approved_path: Path,
        rendered_path: Path,
        realized_path: Path | None,
        status: str,
        reason_codes: list[str],
        error: str,
        resource_usage: ResourceUsage | None = None,
        command: list[str] | None = None,
        tool_versions: dict[str, str] | None = None,
    ) -> AssemblyAttemptRecord:
        inventory_path = self._write_inventory(
            attempt_id,
            attempt_root,
            filename="partial_artifacts_manifest.json",
        )
        usage = resource_usage or ResourceUsage()
        record = AssemblyAttemptRecord(
            attempt_id=attempt_id,
            logical_run_id=coordinate.logical_run_id,
            round_id=coordinate.round_id,
            round_index=coordinate.round_index,
            candidate_index=coordinate.candidate_index,
            attempt_index=attempt_index,
            status=status,  # type: ignore[arg-type]
            requested_config_ref=ManifestReference.from_path(self.run_dir, requested_path),
            approved_config_ref=ManifestReference.from_path(self.run_dir, approved_path),
            rendered_config_ref=ManifestReference.from_path(self.run_dir, rendered_path),
            realized_config_ref=(
                ManifestReference.from_path(self.run_dir, realized_path)
                if realized_path is not None
                else None
            ),
            command=command or [],
            tool_versions=tool_versions or {},
            environment_manifest_sha256=self.environment_manifest_sha256,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            resource_usage=usage.model_copy(
                update={"artifact_bytes": _inventory_bytes(inventory_path)}
            ),
            artifacts_inventory_ref=ManifestReference.from_path(self.run_dir, inventory_path),
            error=error,
            retry_parent_attempt_id=retry_parent,
            comparison_eligible=False,
            ineligible_reason_codes=reason_codes,
        )
        path = self.manifests.write_attempt(record)
        self.manifests.append_history(attempt_paths=[path])
        return record


def _attempt_id(coordinate: AttemptCoordinate, attempt_index: int) -> str:
    return f"{coordinate.logical_run_id}.attempt_{attempt_index:03d}"


def _write_or_verify_json(path: Path, payload: object) -> None:
    expected = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    _write_or_verify_text(path, expected)


def _write_or_verify_text(path: Path, content: str) -> None:
    if path.exists():
        if path.read_text() != content:
            raise AgentStateError(f"Resume contract drift: {path}")
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _exclusive_json(path: Path, payload: object) -> None:
    _write_or_verify_json(path, payload)


def _start_status(path: Path, attempt_id: str, *, resume: bool) -> tuple[datetime, int]:
    now = datetime.now(UTC)
    if path.exists():
        try:
            previous = ExecutionStatus.model_validate_json(path.read_text())
        except ValidationError as exc:
            raise AgentStateError("Attempt recovery status is invalid") from exc
        if not resume or previous.status not in {"RUNNING", "INTERRUPTED"}:
            raise AgentStateError("Attempt is not eligible for interruption resume")
        started_at = previous.started_at
        resume_count = previous.resume_count + 1
    else:
        started_at = now
        resume_count = 0
    _atomic_status(
        path,
        ExecutionStatus(
            attempt_id=attempt_id,
            status="RUNNING",
            started_at=started_at,
            updated_at=now,
            resume_count=resume_count,
        ),
    )
    return started_at, resume_count


def _update_status(
    path: Path,
    attempt_id: str,
    started_at: datetime,
    status: str,
    *,
    resume_count: int,
    error: str | None = None,
) -> None:
    _atomic_status(
        path,
        ExecutionStatus(
            attempt_id=attempt_id,
            status=status,  # type: ignore[arg-type]
            started_at=started_at,
            updated_at=datetime.now(UTC),
            resume_count=resume_count,
            error=error,
        ),
    )


def _atomic_status(path: Path, status: ExecutionStatus) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(status.model_dump_json(indent=2) + "\n")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)


def _inventory_bytes(path: Path) -> int:
    inventory = ArtifactInventory.model_validate_json(path.read_text())
    return sum(entry.bytes for entry in inventory.entries)
