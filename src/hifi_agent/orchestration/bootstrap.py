"""Pre-identity failure receipts for current bootstrap diagnostics."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from hifi_agent.exceptions import HiFiAgentError


class BootstrapFailureReceipt(BaseModel):
    """Failure evidence written before immutable run identity exists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    status: Literal["FAIL"] = "FAIL"
    failed_at: datetime
    stage: Literal["INPUT_VALIDATION", "ENVIRONMENT_PREFLIGHT", "CONTROLLER_BOOTSTRAP"]
    config_path: Path
    error_type: str
    error: str
    exit_code: int
    reason_codes: list[str] = Field(min_length=1)
    identity_created: Literal[False] = False


def write_bootstrap_failure(
    config_path: Path,
    error: HiFiAgentError,
    *,
    stage: Literal["INPUT_VALIDATION", "ENVIRONMENT_PREFLIGHT", "CONTROLLER_BOOTSTRAP"],
    metadata_dir: Path | None = None,
) -> Path | None:
    """Best-effort receipt creation that never masks the original bootstrap error."""
    destination = metadata_dir or _infer_metadata_dir(config_path)
    if destination is None:
        return None
    try:
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / "bootstrap_failure.json"
        receipt = BootstrapFailureReceipt(
            failed_at=datetime.now(UTC),
            stage=stage,
            config_path=config_path.resolve(),
            error_type=type(error).__name__,
            error=str(error),
            exit_code=int(error.exit_code),
            reason_codes=[f"BOOTSTRAP_{stage}_FAILED"],
        )
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(receipt.model_dump_json(indent=2) + "\n")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(output)
    except (OSError, ValueError, yaml.YAMLError):
        return None
    return output


def _infer_metadata_dir(config_path: Path) -> Path | None:
    try:
        payload = yaml.safe_load(config_path.read_text())
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(payload, Mapping):
        return None
    outdir_value = payload.get("outdir")
    if isinstance(outdir_value, str):
        outdir = Path(outdir_value)
        if not outdir.is_absolute():
            outdir = config_path.parent / outdir
        return _safe_metadata_dir(outdir)
    if payload.get("schema_id") != "hifi-agent-sample":
        return None
    runtime_value = payload.get("runtime_config")
    sample_id = payload.get("output_name") or payload.get("sample_id")
    if not isinstance(runtime_value, str) or not isinstance(sample_id, str):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", sample_id):
        return None
    runtime_path = Path(runtime_value)
    if not runtime_path.is_absolute():
        runtime_path = config_path.parent / runtime_path
    try:
        runtime = yaml.safe_load(runtime_path.read_text())
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(runtime, Mapping):
        return None
    paths = runtime.get("paths")
    if not isinstance(paths, Mapping) or not isinstance(paths.get("output_root"), str):
        return None
    output_root = Path(paths["output_root"])
    if not output_root.is_absolute():
        output_root = runtime_path.parent / output_root
    return _safe_metadata_dir(output_root / sample_id)


def _safe_metadata_dir(outdir: Path) -> Path | None:
    resolved = outdir.resolve()
    if resolved == Path(resolved.anchor):
        return None
    return resolved / "00_metadata"
