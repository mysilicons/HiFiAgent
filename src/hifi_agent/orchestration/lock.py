"""Single-writer current run lock with explicit, auditable stale takeover."""

from __future__ import annotations

import json
import os
import platform
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from hifi_agent.exceptions import AgentStateError

ProcessAlive = Callable[[int], bool]


class RunLockRecord(BaseModel):
    """Immutable owner receipt stored in ``05_agent/run.lock``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    lock_id: str
    run_uuid: str
    pid: int
    hostname: str
    command: list[str]
    acquired_at: datetime
    takeover_of_lock_id: str | None = None


class RunLock:
    """Acquire exactly one writer for a current run directory."""

    def __init__(
        self,
        run_dir: Path,
        *,
        run_uuid: str,
        command: list[str],
        process_alive: ProcessAlive | None = None,
    ) -> None:
        self.directory = run_dir.resolve() / "05_agent"
        self.path = self.directory / "run.lock"
        self.run_uuid = run_uuid
        self.command = command
        self.process_alive = process_alive or _process_alive
        self.record: RunLockRecord | None = None

    def acquire(self, *, takeover_stale: bool = False) -> RunLockRecord:
        """Acquire the lock, rejecting live or unapproved stale owners."""
        self.directory.mkdir(parents=True, exist_ok=True)
        takeover: str | None = None
        if self.path.exists():
            existing = self._load()
            live = existing.hostname != platform.node() or self.process_alive(existing.pid)
            if live:
                raise AgentStateError(
                    f"current run is locked by pid={existing.pid} host={existing.hostname}"
                )
            if not takeover_stale:
                raise AgentStateError(
                    "current run has a stale lock; explicit takeover_stale=True is required"
                )
            takeover = existing.lock_id
            archived = self.directory / f"run.lock.stale.{existing.lock_id}.json"
            try:
                self.path.replace(archived)
            except OSError as exc:
                raise AgentStateError("Unable to archive the stale current lock") from exc
        record = RunLockRecord(
            lock_id=uuid.uuid4().hex,
            run_uuid=self.run_uuid,
            pid=os.getpid(),
            hostname=platform.node(),
            command=self.command,
            acquired_at=datetime.now(UTC),
            takeover_of_lock_id=takeover,
        )
        try:
            _exclusive_json(self.path, record.model_dump(mode="json"))
        except FileExistsError as exc:
            raise AgentStateError("Another writer acquired the current run lock") from exc
        self.record = record
        return record

    def release(self) -> None:
        """Release only the lock created by this instance."""
        if self.record is None:
            return
        existing = self._load()
        if existing.lock_id != self.record.lock_id:
            raise AgentStateError("Refusing to release a current lock owned by another writer")
        self.path.unlink()
        self.record = None

    def _load(self) -> RunLockRecord:
        try:
            return RunLockRecord.model_validate_json(self.path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"current run lock is invalid: {self.path}: {exc}") from exc

    def __enter__(self) -> RunLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.release()


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _exclusive_json(path: Path, payload: object) -> None:
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
