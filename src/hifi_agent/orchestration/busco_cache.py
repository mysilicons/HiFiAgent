"""Prepare one governed BUSCO lineage in a shared, lock-protected cache."""

from __future__ import annotations

import fcntl
import subprocess
from collections.abc import Callable
from pathlib import Path

from hifi_agent.exceptions import ToolExecutionError
from hifi_agent.schemas.sample import SampleConfig
from hifi_agent.tool_resolution import (
    declared_subprocess_environment,
    resolve_configured_tool,
)

DownloadRunner = Callable[[list[str], Path, dict[str, str]], int]


def prepare_busco_lineage(
    sample: SampleConfig,
    *,
    runner: DownloadRunner | None = None,
) -> Path | None:
    """Download a missing declared lineage once, then return its dataset directory."""
    lineage = sample.busco_lineage
    cache = sample.tools.busco_lineage_dir
    if lineage is None or cache is None:
        return None
    existing = _dataset_path(cache, lineage)
    if existing is not None:
        return existing
    if not sample.tools.download_missing_busco:
        raise ToolExecutionError(
            f"BUSCO lineage `{lineage}` is absent from the configured cache: {cache}"
        )

    cache.mkdir(parents=True, exist_ok=True)
    lock_path = cache / f".{lineage}.download.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing = _dataset_path(cache, lineage)
        if existing is not None:
            return existing
        executable = resolve_configured_tool("busco", "busco", sample)
        if executable is None:
            raise ToolExecutionError("BUSCO executable is unavailable for lineage download")
        command = [
            str(executable),
            "--download",
            lineage,
            "--download_path",
            str(cache),
        ]
        active_runner = runner or _run_download
        status = active_runner(command, cache, declared_subprocess_environment(sample))
        if status != 0:
            raise ToolExecutionError(
                f"BUSCO lineage download failed with exit code {status}: {lineage}"
            )
        downloaded = _dataset_path(cache, lineage)
        if downloaded is None or not (downloaded / "dataset.cfg").is_file():
            raise ToolExecutionError(
                f"BUSCO reported success but lineage metadata is missing: {lineage}"
            )
        return downloaded


def _run_download(command: list[str], cwd: Path, environment: dict[str, str]) -> int:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        text=True,
    )
    return completed.returncode


def _dataset_path(cache: Path, lineage: str) -> Path | None:
    for candidate in (cache / lineage, cache / "lineages" / lineage):
        if candidate.is_dir() and (candidate / "dataset.cfg").is_file():
            return candidate.resolve()
    return None
