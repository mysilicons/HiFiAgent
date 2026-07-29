"""Immutable V2 attempt history and read-only V1 migration inspection."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from hifi_agent.exceptions import AgentStateError, InputValidationError
from hifi_agent.orchestration.models import (
    ArtifactRecord,
    AttemptIdentity,
    AttemptManifest,
    HistoryManifest,
    RoundRecord,
    RunIdentity,
    attempt_id,
    candidate_run_id,
)


class V1MigrationInspection(BaseModel):
    """Read-only description of a legacy V1 run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "2.0"
    mode: str = "DRY_RUN_READ_ONLY"
    run_dir: Path
    sample_id: str
    artifacts_found: list[Path]
    missing_required: list[Path]
    would_create: list[Path]


class V1RunView:
    """Read-only loader for legacy V1 artifacts."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()

    def inspect(self) -> V1MigrationInspection:
        """Inspect required V1 artifacts without writing to the run directory."""
        config_path = self.run_dir / "00_metadata/resolved_config.yaml"
        if not config_path.is_file():
            raise InputValidationError(f"V1 resolved config is missing: {config_path}")
        import yaml

        try:
            data = yaml.safe_load(config_path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise InputValidationError(f"V1 resolved config is invalid: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("sample_id"), str):
            raise InputValidationError("V1 resolved config has no valid sample_id")
        required = [
            config_path,
            self.run_dir / "00_metadata/validation_receipt.json",
            self.run_dir / "01_pre_qc/raw_metrics.json",
            self.run_dir / "02_assembly/baseline/metadata/assembly_manifest.json",
            self.run_dir / "03_post_qc/baseline/assembly_metrics.json",
        ]
        found = [path for path in required if path.is_file()]
        missing = [path for path in required if not path.is_file()]
        return V1MigrationInspection(
            run_dir=self.run_dir,
            sample_id=data["sample_id"],
            artifacts_found=found,
            missing_required=missing,
            would_create=[
                self.run_dir / "05_agent/v2/run_identity.json",
                self.run_dir / "02_assembly/baseline/attempt_001/artifact_manifest.json",
                self.run_dir / "03_post_qc/baseline/attempt_001/artifact_manifest.json",
            ],
        )


def inspect_v1_migration(run_dir: Path) -> V1MigrationInspection:
    """Return a dry-run-only migration plan for a V1 directory."""
    return V1RunView(run_dir).inspect()


class AttemptHistoryStore:
    """Create checksum-bound attempt identities without overwriting history."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.metadata_dir = self.run_dir / "05_agent/v2"
        self.identity_path = self.metadata_dir / "run_identity.json"
        self.history_path = self.metadata_dir / "history_manifest.json"
        self.lock_dir = self.metadata_dir / "locks"

    def initialize(self, sample_id: str, config_path: Path) -> RunIdentity:
        """Atomically create a run identity; concurrent duplicate creation fails."""
        if self.identity_path.exists():
            raise AgentStateError(f"V2 run identity already exists: {self.identity_path}")
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        identity = RunIdentity(
            run_uuid=uuid.uuid4().hex,
            sample_id=sample_id,
            created_at=datetime.now(UTC),
            run_dir=self.run_dir,
            config_sha256=_sha256(config_path),
        )
        try:
            _exclusive_json(self.identity_path, identity.model_dump(mode="json"))
        except FileExistsError as exc:
            raise AgentStateError(f"V2 run identity already exists: {self.identity_path}") from exc
        history = HistoryManifest(
            run_identity=identity,
            updated_at=datetime.now(UTC),
            attempts=[],
        )
        try:
            _exclusive_json(self.history_path, history.model_dump(mode="json"))
        except FileExistsError as exc:
            raise AgentStateError(f"V2 history already exists: {self.history_path}") from exc
        return identity

    def load_identity(self, *, verify_config: Path | None = None) -> RunIdentity:
        """Load the identity and optionally verify the current config checksum."""
        try:
            identity = RunIdentity.model_validate_json(self.identity_path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(
                f"V2 run identity is invalid: {self.identity_path}: {exc}"
            ) from exc
        if verify_config is not None and _sha256(verify_config) != identity.config_sha256:
            raise AgentStateError("V2 config checksum differs from the initialized run identity")
        return identity

    def load_history(self) -> HistoryManifest:
        """Load and validate the history index."""
        try:
            return HistoryManifest.model_validate_json(self.history_path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(
                f"V2 history manifest is invalid: {self.history_path}: {exc}"
            ) from exc

    def begin_attempt(
        self,
        *,
        kind: Literal["baseline", "candidate"],
        round_index: int,
        candidate_index: int | None = None,
        retry: bool = False,
    ) -> AttemptIdentity:
        """Return an idempotent incomplete/completed attempt or reserve the next retry."""
        identity = self.load_identity()
        logical = _logical_directory(self.run_dir, kind, round_index, candidate_index)
        lock_name = (
            "baseline" if kind == "baseline" else f"r{round_index:02d}_c{candidate_index:02d}"
        )
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        lock = self.lock_dir / f"{lock_name}.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError as exc:
            raise AgentStateError(
                f"Attempt reservation is already in progress: {lock_name}"
            ) from exc
        os.close(descriptor)
        try:
            existing = sorted(logical.glob("attempt_[0-9][0-9][0-9]*"))
            if existing and not retry:
                return _identity_from_directory(
                    identity,
                    kind,
                    round_index,
                    candidate_index,
                    existing[-1],
                )
            next_index = len(existing) + 1
            attempt = AttemptIdentity(
                run_uuid=identity.run_uuid,
                kind=kind,
                round_index=round_index,
                candidate_index=candidate_index,
                attempt_index=next_index,
                run_id=(
                    "baseline"
                    if kind == "baseline"
                    else candidate_run_id(round_index, _required_candidate(candidate_index))
                ),
                attempt_id=attempt_id(next_index),
            )
            assembly_dir = self.run_dir / "02_assembly" / attempt.relative_directory()
            post_qc_dir = self.run_dir / "03_post_qc" / attempt.relative_directory()
            assembly_dir.mkdir(parents=True, exist_ok=False)
            try:
                post_qc_dir.mkdir(parents=True, exist_ok=False)
            except Exception:
                assembly_dir.rmdir()
                raise
            _exclusive_json(assembly_dir / "attempt_identity.json", attempt.model_dump(mode="json"))
            _exclusive_json(post_qc_dir / "attempt_identity.json", attempt.model_dump(mode="json"))
            self._append_attempt(attempt)
            return attempt
        finally:
            lock.unlink(missing_ok=True)

    def complete_attempt(
        self,
        attempt: AttemptIdentity,
        *,
        artifacts: dict[str, Path],
        status: Literal["COMPLETED", "FAILED"] = "COMPLETED",
        parameter_fingerprint: str | None = None,
        error: str | None = None,
    ) -> AttemptManifest:
        """Write an immutable manifest and completion receipt for one attempt."""
        assembly_dir = self.run_dir / "02_assembly" / attempt.relative_directory()
        manifest_path = assembly_dir / "artifact_manifest.json"
        completion_path = assembly_dir / "completion.json"
        if manifest_path.exists() or completion_path.exists():
            existing = self.load_attempt(attempt)
            self.verify_attempt(attempt)
            return existing
        records = [
            _artifact_record(role, path.resolve()) for role, path in sorted(artifacts.items())
        ]
        manifest = AttemptManifest(
            identity=attempt,
            status=status,
            created_at=datetime.fromtimestamp(assembly_dir.stat().st_mtime, tz=UTC),
            completed_at=datetime.now(UTC),
            parameter_fingerprint=parameter_fingerprint,
            artifacts=records,
            error=error,
        )
        _exclusive_json(manifest_path, manifest.model_dump(mode="json"))
        manifest_digest = _sha256(manifest_path)
        _exclusive_json(
            completion_path,
            {
                "schema_version": "2.0",
                "status": status,
                "manifest_sha256": manifest_digest,
            },
        )
        post_qc_dir = self.run_dir / "03_post_qc" / attempt.relative_directory()
        _exclusive_json(
            post_qc_dir / "artifact_manifest.json",
            {
                "schema_version": "2.0",
                "assembly_manifest": str(manifest_path),
                "assembly_manifest_sha256": manifest_digest,
                "post_qc_artifacts": [
                    record.model_dump(mode="json")
                    for record in records
                    if "metric" in record.role or "post_qc" in record.role
                ],
            },
        )
        return manifest

    def load_attempt(self, attempt: AttemptIdentity) -> AttemptManifest:
        """Load an attempt manifest."""
        path = (
            self.run_dir / "02_assembly" / attempt.relative_directory() / "artifact_manifest.json"
        )
        try:
            return AttemptManifest.model_validate_json(path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"Attempt manifest is invalid: {path}: {exc}") from exc

    def verify_attempt(self, attempt: AttemptIdentity) -> AttemptManifest:
        """Verify the completion receipt, manifest, and every referenced artifact."""
        directory = self.run_dir / "02_assembly" / attempt.relative_directory()
        manifest_path = directory / "artifact_manifest.json"
        completion_path = directory / "completion.json"
        try:
            completion = json.loads(completion_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentStateError(
                f"Attempt completion receipt is invalid: {completion_path}"
            ) from exc
        if completion.get("manifest_sha256") != _sha256(manifest_path):
            raise AgentStateError("Attempt manifest checksum mismatch")
        manifest = self.load_attempt(attempt)
        for record in manifest.artifacts:
            if not record.path.is_file():
                raise AgentStateError(f"Attempt artifact is missing: {record.path}")
            stat = record.path.stat()
            if (
                stat.st_size != record.bytes
                or stat.st_mtime_ns != record.mtime_ns
                or _sha256(record.path) != record.sha256
            ):
                raise AgentStateError(f"Attempt artifact checksum mismatch: {record.path}")
        return manifest

    def is_complete(self, attempt: AttemptIdentity) -> bool:
        """Return whether a valid completed attempt exists."""
        completion = self.run_dir / "02_assembly" / attempt.relative_directory() / "completion.json"
        if not completion.is_file():
            return False
        return self.verify_attempt(attempt).status == "COMPLETED"

    def verify_history(self) -> HistoryManifest:
        """Verify every attempt that has a completion receipt."""
        history = self.load_history()
        for attempt in history.attempts:
            completion = (
                self.run_dir / "02_assembly" / attempt.relative_directory() / "completion.json"
            )
            if completion.is_file():
                self.verify_attempt(attempt)
        return history

    def record_round(self, record: RoundRecord) -> RoundRecord:
        """Persist one immutable round record and index it exactly once."""
        directory = self.run_dir / "04_decisions/rounds" / f"round_{record.round_index:02d}"
        path = directory / "round_record.json"
        if path.is_file():
            try:
                existing = RoundRecord.model_validate_json(path.read_text())
            except (OSError, ValidationError) as exc:
                raise AgentStateError(f"Round record is invalid: {path}: {exc}") from exc
            if existing != record:
                raise AgentStateError(f"Round record is immutable and already differs: {path}")
            return existing
        _exclusive_json(path, record.model_dump(mode="json"))
        history = self.load_history()
        if any(item.round_index == record.round_index for item in history.rounds):
            raise AgentStateError(f"Round {record.round_index} is already indexed")
        history.rounds.append(record)
        history.updated_at = datetime.now(UTC)
        _atomic_json(self.history_path, history.model_dump(mode="json"))
        return record

    def _append_attempt(self, attempt: AttemptIdentity) -> None:
        history = self.load_history()
        history.attempts.append(attempt)
        history.updated_at = datetime.now(UTC)
        _atomic_json(self.history_path, history.model_dump(mode="json"))


def _logical_directory(
    run_dir: Path,
    kind: Literal["baseline", "candidate"],
    round_index: int,
    candidate_index: int | None,
) -> Path:
    if kind == "baseline":
        if round_index != 0 or candidate_index is not None:
            raise AgentStateError("Baseline attempt requires round 0 and no candidate index")
        return run_dir / "02_assembly/baseline"
    if kind != "candidate":
        raise AgentStateError(f"Unsupported attempt kind: {kind}")
    candidate = _required_candidate(candidate_index)
    if not 1 <= round_index <= 3:
        raise AgentStateError("Candidate round must be between 1 and 3")
    return run_dir / f"02_assembly/round_{round_index:02d}/candidate_{candidate:02d}"


def _identity_from_directory(
    run: RunIdentity,
    kind: Literal["baseline", "candidate"],
    round_index: int,
    candidate_index: int | None,
    directory: Path,
) -> AttemptIdentity:
    index = int(directory.name.removeprefix("attempt_"))
    return AttemptIdentity(
        run_uuid=run.run_uuid,
        kind=kind,
        round_index=round_index,
        candidate_index=candidate_index,
        attempt_index=index,
        run_id=(
            "baseline"
            if kind == "baseline"
            else candidate_run_id(round_index, _required_candidate(candidate_index))
        ),
        attempt_id=attempt_id(index),
    )


def _required_candidate(candidate_index: int | None) -> int:
    if candidate_index is None:
        raise AgentStateError("Candidate attempt requires candidate_index")
    return candidate_index


def _artifact_record(role: str, path: Path) -> ArtifactRecord:
    if not path.is_file():
        raise AgentStateError(f"Cannot record missing attempt artifact: {path}")
    stat = path.stat()
    return ArtifactRecord(
        role=role,
        path=path,
        sha256=_sha256(path),
        bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def _exclusive_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
