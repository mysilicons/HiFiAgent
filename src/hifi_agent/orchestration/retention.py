"""Post-verification retention for recoverable workflow scratch data."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hifi_agent.exceptions import AgentStateError
from hifi_agent.orchestration.runtime_models import RunPhase
from hifi_agent.orchestration.verifier import VerificationReport


class RetentionReceipt(BaseModel):
    """Auditable record of scratch directories removed after verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    status: Literal["PASS"] = "PASS"
    policy: Literal["standard"] = "standard"
    applied_at: datetime
    removed_paths: tuple[Path, ...] = ()
    freed_bytes: int = Field(ge=0)


def apply_retention(
    run_dir: Path,
    *,
    policy: Literal["full", "standard"],
    state: RunPhase,
) -> RetentionReceipt | None:
    """Remove only unregistered work caches after a verified terminal result."""
    if policy == "full":
        return None
    root = run_dir.resolve()
    receipt_path = root / "00_metadata/retention_receipt.json"
    if receipt_path.is_file():
        try:
            return RetentionReceipt.model_validate_json(receipt_path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"Retention receipt is invalid: {receipt_path}: {exc}") from exc
    if state != RunPhase.TERMINAL:
        raise AgentStateError("Standard retention requires a terminal run state")

    verification_path = root / "06_report/verification_report.json"
    try:
        verification = VerificationReport.model_validate_json(verification_path.read_text())
    except (OSError, ValidationError) as exc:
        raise AgentStateError(
            f"Standard retention requires a valid verification report: {exc}"
        ) from exc
    if verification.status != "PASS" or not verification.deep:
        raise AgentStateError("Standard retention requires a PASS deep-verification report")

    targets = _retention_targets(root)
    removed: list[Path] = []
    freed_bytes = 0
    for target in targets:
        _require_safe_target(root, target)
        if not target.exists():
            continue
        if not target.is_dir() or target.is_symlink():
            raise AgentStateError(f"Refusing to remove unsafe retention target: {target}")
        freed_bytes += _directory_size(target)
        shutil.rmtree(target)
        removed.append(target.relative_to(root))

    receipt = RetentionReceipt(
        applied_at=datetime.now(UTC),
        removed_paths=tuple(removed),
        freed_bytes=freed_bytes,
    )
    _atomic_json(receipt_path, receipt.model_dump(mode="json"))
    return receipt


def _retention_targets(root: Path) -> tuple[Path, ...]:
    assembly_root = root / "02_assembly"
    assembly_work = tuple(
        sorted(
            (path for path in assembly_root.glob("**/workflow/work") if path.is_dir()),
            key=lambda item: str(item),
        )
    )
    return (root / "01_pre_qc/work", *assembly_work)


def _require_safe_target(root: Path, target: Path) -> None:
    resolved = target.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise AgentStateError(f"Retention target escapes the run directory: {target}") from exc
    if relative == Path("01_pre_qc/work"):
        return
    parts = relative.parts
    if len(parts) >= 4 and parts[0] == "02_assembly" and parts[-2:] == ("workflow", "work"):
        return
    raise AgentStateError(f"Retention target is outside the allowlist: {target}")


def _directory_size(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            total += entry.stat().st_size
    return total


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)
