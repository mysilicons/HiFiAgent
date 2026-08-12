"""Immutable current run identity persistence and resume drift receipts."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from hifi_agent.exceptions import AgentStateError
from hifi_agent.orchestration.runtime_models import RunIdentity, sha256_file


class IdentityDriftItem(BaseModel):
    """One immutable-snapshot mismatch found during resume."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    path: Path | None
    expected_sha256: str | None
    observed_sha256: str | None
    reason_code: str


class IdentityDriftReceipt(BaseModel):
    """Machine-readable refusal to resume a drifted current run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    status: Literal["FAIL"] = "FAIL"
    run_uuid: str
    checked_at: datetime
    drift: list[IdentityDriftItem]


class IdentityStore:
    """Create once and verify the current identity against canonical snapshots."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.metadata_dir = self.run_dir / "00_metadata"
        self.identity_path = self.metadata_dir / "run_identity.json"
        self.drift_path = self.metadata_dir / "identity_drift_receipt.json"

    def initialize(self, identity: RunIdentity) -> RunIdentity:
        """Persist identity exactly once."""
        if identity.run_dir.resolve() != self.run_dir:
            raise AgentStateError("current identity run_dir differs from its target directory")
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        try:
            _exclusive_json(self.identity_path, identity.model_dump(mode="json"))
        except FileExistsError as exc:
            raise AgentStateError(
                f"current run identity already exists: {self.identity_path}"
            ) from exc
        return identity

    def load(self) -> RunIdentity:
        """Load a strictly typed identity."""
        try:
            identity = RunIdentity.model_validate_json(self.identity_path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(
                f"current run identity is invalid: {self.identity_path}: {exc}"
            ) from exc
        if identity.run_dir.resolve() != self.run_dir:
            raise AgentStateError("current identity run_dir differs from its filesystem root")
        return identity

    def verify_snapshots(
        self,
        *,
        resolved_config: Path | None = None,
        effective_config: Path | None = None,
        input_manifest: Path | None = None,
        environment_manifest: Path | None = None,
        comparison_policy: Path | None = None,
        rag_index: Path | None = None,
        write_drift_receipt: bool = False,
    ) -> RunIdentity:
        """Verify immutable inputs and optionally materialize a resume refusal receipt."""
        identity = self.load()
        checks = (
            (
                "sample_config_sha256",
                self.metadata_dir / "sample_config_snapshot.yaml",
                identity.sample_config_sha256,
            ),
            (
                "runtime_config_sha256",
                self.metadata_dir / "runtime_config_snapshot.yaml",
                identity.runtime_config_sha256,
            ),
            (
                "config_sha256",
                resolved_config or self.metadata_dir / "resolved_config.yaml",
                identity.config_sha256,
            ),
            (
                "effective_config_sha256",
                effective_config or self.metadata_dir / "effective_config.json",
                identity.effective_config_sha256,
            ),
            (
                "input_manifest_sha256",
                input_manifest or self.metadata_dir / "input_manifest.json",
                identity.input_manifest_sha256,
            ),
            (
                "environment_manifest_sha256",
                environment_manifest or self.metadata_dir / "environment_manifest.json",
                identity.environment_manifest_sha256,
            ),
            (
                "comparison_policy_sha256",
                comparison_policy or self.run_dir / "04_decisions/comparison_policy_snapshot.yaml",
                identity.comparison_policy_sha256,
            ),
        )
        drift: list[IdentityDriftItem] = []
        for field, path, expected in checks:
            if expected is None:
                continue
            item = _check_snapshot(field, path, expected)
            if item is not None:
                drift.append(item)
        if identity.rag_index_sha256 is not None:
            effective_rag_index = rag_index or self.run_dir / "04_decisions/rag_index_snapshot.json"
            item = _check_snapshot(
                "rag_index_sha256", effective_rag_index, identity.rag_index_sha256
            )
            if item is not None:
                drift.append(item)
        if drift:
            receipt = IdentityDriftReceipt(
                run_uuid=identity.run_uuid,
                checked_at=datetime.now(UTC),
                drift=drift,
            )
            if write_drift_receipt:
                _atomic_json(self.drift_path, receipt.model_dump(mode="json"))
            fields = ", ".join(item.field for item in drift)
            raise AgentStateError(f"current immutable identity snapshot drift detected: {fields}")
        return identity


def _check_snapshot(
    field: str,
    path: Path,
    expected: str,
) -> IdentityDriftItem | None:
    if not path.is_file():
        return IdentityDriftItem(
            field=field,
            path=path,
            expected_sha256=expected,
            observed_sha256=None,
            reason_code="IDENTITY_SNAPSHOT_MISSING",
        )
    observed = sha256_file(path)
    if observed != expected:
        return IdentityDriftItem(
            field=field,
            path=path,
            expected_sha256=expected,
            observed_sha256=observed,
            reason_code="IDENTITY_SNAPSHOT_SHA256_MISMATCH",
        )
    return None


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


def _atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)
