"""Declared tool resolution shared by preflight and workflow execution."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from hifi_agent.schemas.sample import SampleConfig, ToolName

Resolver = Callable[[str], str | None]


def resolve_configured_tool(
    name: ToolName,
    command: str,
    config: SampleConfig,
    *,
    resolver: Resolver = shutil.which,
) -> Path | None:
    """Resolve an override, active-environment tool, or injected test resolver."""
    override = config.tools.executable_overrides.get(name)
    if override is not None:
        return override.resolve() if override.is_file() and os.access(override, os.X_OK) else None
    if resolver is shutil.which:
        environment_prefix = os.environ.get("CONDA_PREFIX")
        if environment_prefix:
            candidate = Path(environment_prefix) / "bin" / command
            return (
                candidate.resolve()
                if candidate.is_file() and os.access(candidate, os.X_OK)
                else None
            )
    resolved = resolver(command)
    return Path(resolved).resolve() if resolved else None


def declared_subprocess_environment(config: SampleConfig) -> dict[str, str]:
    """Build a child environment that cannot fall through to personal tool directories."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    override_dirs = [
        str(path.resolve().parent) for path in config.tools.executable_overrides.values()
    ]
    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        search_path = [*override_dirs, str(Path(prefix) / "bin")]
        search_path.extend(
            path for path in ("/usr/local/bin", "/usr/bin", "/bin") if Path(path).is_dir()
        )
    else:
        search_path = [*override_dirs, *os.environ.get("PATH", "").split(os.pathsep)]
    environment["PATH"] = os.pathsep.join(dict.fromkeys(search_path))
    return environment
