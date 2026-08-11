"""Pre-identity failure receipts for current bootstrap diagnostics."""

from __future__ import annotations

import os
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
    if not isinstance(payload, dict) or not isinstance(payload.get("outdir"), str):
        return None
    outdir = Path(payload["outdir"])
    if not outdir.is_absolute():
        outdir = config_path.parent / outdir
    resolved = outdir.resolve()
    if resolved == Path(resolved.anchor):
        return None
    return resolved / "00_metadata"
