"""Explicit current tool resolution and environment preflight without host fallbacks."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hifi_agent.constants import __version__
from hifi_agent.exceptions import ToolExecutionError
from hifi_agent.schemas.sample import SampleConfig, ToolName
from hifi_agent.tool_resolution import resolve_configured_tool

PreflightStatus = Literal["PASS", "WARNING", "FAIL"]
Resolver = Callable[[str], str | None]
Runner = Callable[[Sequence[str]], tuple[int, str]]


class ToolCheck(BaseModel):
    """One resolved executable and its observed version evidence."""

    model_config = ConfigDict(extra="forbid")

    name: ToolName
    command_name: str
    required: bool
    executable: Path | None = None
    version: str | None = None
    expected_version: str | None = None
    status: PreflightStatus
    reason_codes: list[str] = Field(default_factory=list)


class BuscoLineageRecord(BaseModel):
    """Checksum-bound offline BUSCO lineage selected for every assembly attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lineage: str
    download_path: Path
    dataset_path: Path
    dataset_config: Path
    dataset_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    creation_date: str
    ortho_db_version: str
    dataset_version: str
    busco_count: int = Field(gt=0)
    species_count: int = Field(gt=0)


class EnvironmentManifest(BaseModel):
    """Complete current preflight snapshot used before immutable run identity creation."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    created_at: datetime
    status: PreflightStatus
    platform: str
    architecture: str
    python_version: str
    hifi_agent_version: str
    cpu_count: int
    total_memory_gib: float
    requested_threads: int
    requested_memory_gb: int
    minimum_free_disk_gib: float
    temporary_directory: Path
    temporary_directory_writable: bool
    outdir_probe: Path
    outdir_parent_writable: bool
    free_disk_gib: float
    coverage_backend: Literal["mosdepth", "bedtools"] | None = None
    busco_lineage: BuscoLineageRecord | None = None
    tools: list[ToolCheck]
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class _ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ToolName
    command: str
    version_args: list[str]
    expected: str | None
    required: bool = True


_TOOL_SPECS = (
    _ToolSpec(name="java", command="java", version_args=["-version"], expected="21"),
    _ToolSpec(
        name="nextflow",
        command="nextflow",
        version_args=["-version"],
        expected="25.04.7",
    ),
    _ToolSpec(name="hifiasm", command="hifiasm", version_args=["--version"], expected="0.25.0"),
    _ToolSpec(name="gfatools", command="gfatools", version_args=["version"], expected=None),
    _ToolSpec(name="seqkit", command="seqkit", version_args=["version"], expected="2.10.1"),
    _ToolSpec(name="nanoplot", command="NanoPlot", version_args=["--version"], expected="1.47.1"),
    _ToolSpec(name="meryl", command="meryl", version_args=["--version"], expected="1.3"),
    _ToolSpec(name="quast", command="quast.py", version_args=["--version"], expected="5.3.0"),
    _ToolSpec(name="busco", command="busco", version_args=["--version"], expected="6.0.0"),
    _ToolSpec(
        name="merqury",
        command="merqury.sh",
        version_args=["--help"],
        expected="1.3",
    ),
    _ToolSpec(name="minimap2", command="minimap2", version_args=["--version"], expected="2.30"),
    _ToolSpec(name="samtools", command="samtools", version_args=["--version"], expected="1.22.1"),
    _ToolSpec(name="rscript", command="Rscript", version_args=["--version"], expected=None),
    _ToolSpec(
        name="genomescope",
        command="genomescope2",
        version_args=["--version"],
        expected="2.0",
        required=False,
    ),
)


def run_environment_preflight(
    config: SampleConfig,
    *,
    resolver: Resolver = shutil.which,
    runner: Runner | None = None,
) -> EnvironmentManifest:
    """Resolve every declared tool, check versions, disk, and requested coverage backend."""
    active_runner = runner or _run_version_command
    checks = [
        _check_tool(spec, config=config, resolver=resolver, runner=active_runner)
        for spec in _TOOL_SPECS
    ]
    coverage, coverage_check = _check_coverage_backend(
        config,
        resolver=resolver,
        runner=active_runner,
    )
    checks.append(coverage_check)
    errors = [reason for check in checks if check.status == "FAIL" for reason in check.reason_codes]
    warnings = [
        reason for check in checks if check.status == "WARNING" for reason in check.reason_codes
    ]
    probe = _nearest_existing_parent(config.outdir)
    outdir_writable = os.access(probe, os.W_OK)
    temporary_directory = Path(tempfile.gettempdir()).resolve()
    temporary_writable = temporary_directory.is_dir() and os.access(temporary_directory, os.W_OK)
    usage = shutil.disk_usage(probe)
    free_gib = usage.free / (1024**3)
    cpu_count = os.cpu_count() or 1
    total_memory_gib = _total_memory_gib()
    if free_gib < _minimum_disk(config):
        errors.append("FREE_DISK_BELOW_CONFIGURED_MINIMUM")
    if config.resources.max_threads > cpu_count:
        errors.append("REQUESTED_THREADS_EXCEED_HOST_CPU_COUNT")
    if config.resources.max_memory_gb > total_memory_gib:
        errors.append("REQUESTED_MEMORY_EXCEEDS_HOST_MEMORY")
    if not outdir_writable:
        errors.append("OUTDIR_PARENT_NOT_WRITABLE")
    if not temporary_writable:
        errors.append("TEMPORARY_DIRECTORY_NOT_WRITABLE")
    if config.outdir.resolve() == Path(config.outdir.anchor):
        errors.append("UNSAFE_OUTDIR_ROOT")
    lineage = config.tools.busco_lineage_dir
    lineage_record: BuscoLineageRecord | None = None
    if config.busco_lineage and lineage is not None and not lineage.is_dir():
        if config.tools.download_missing_busco:
            warnings.append("BUSCO_LINEAGE_DOWNLOAD_PENDING")
        else:
            errors.append("BUSCO_LINEAGE_DIR_NOT_FOUND")
    elif config.busco_lineage and lineage is not None:
        dataset = _busco_dataset_path(lineage, config.busco_lineage)
        dataset_config = dataset / "dataset.cfg" if dataset is not None else None
        if dataset is None or dataset_config is None or not dataset_config.is_file():
            if config.tools.download_missing_busco:
                warnings.append("BUSCO_LINEAGE_DOWNLOAD_PENDING")
            else:
                errors.append("BUSCO_LINEAGE_DATASET_NOT_FOUND")
        else:
            try:
                metadata = _parse_busco_dataset_config(dataset_config)
                lineage_record = BuscoLineageRecord(
                    lineage=config.busco_lineage,
                    download_path=lineage,
                    dataset_path=dataset,
                    dataset_config=dataset_config,
                    dataset_config_sha256=_sha256(dataset_config),
                    dataset_sha256=_sha256_directory(dataset),
                    creation_date=_required_dataset_value(metadata, "creation_date"),
                    ortho_db_version=_required_dataset_value(metadata, "OrthoDB_version"),
                    dataset_version=_required_dataset_value(metadata, "dataset_version"),
                    busco_count=int(_required_dataset_value(metadata, "number_of_BUSCOs")),
                    species_count=int(_required_dataset_value(metadata, "number_of_species")),
                )
            except (OSError, ValueError):
                errors.append("BUSCO_LINEAGE_METADATA_INVALID")
    elif config.busco_lineage and lineage is None:
        warnings.append("BUSCO_LINEAGE_DOWNLOAD_REQUIRED")
    status: PreflightStatus = "FAIL" if errors else ("WARNING" if warnings else "PASS")
    return EnvironmentManifest(
        created_at=datetime.now(UTC),
        status=status,
        platform=platform.platform(),
        architecture=platform.machine(),
        python_version=platform.python_version(),
        hifi_agent_version=__version__,
        cpu_count=cpu_count,
        total_memory_gib=round(total_memory_gib, 3),
        requested_threads=config.resources.max_threads,
        requested_memory_gb=config.resources.max_memory_gb,
        minimum_free_disk_gib=config.execution_budget.min_free_disk_gib,
        temporary_directory=temporary_directory,
        temporary_directory_writable=temporary_writable,
        outdir_probe=probe,
        outdir_parent_writable=outdir_writable,
        free_disk_gib=round(free_gib, 3),
        coverage_backend=coverage,
        busco_lineage=lineage_record,
        tools=checks,
        warnings=warnings,
        errors=errors,
    )


def require_environment_preflight(manifest: EnvironmentManifest) -> None:
    """Raise a normalized failure when required preflight checks do not pass."""
    if manifest.status == "FAIL":
        raise ToolExecutionError(
            "current environment preflight failed: " + ", ".join(manifest.errors)
        )


def materialize_environment_manifest(
    manifest: EnvironmentManifest,
    output: Path,
) -> Path:
    """Atomically persist the exact preflight snapshot used by run identity."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(manifest.model_dump_json(indent=2) + "\n")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(output)
    return output


def _check_tool(
    spec: _ToolSpec,
    *,
    config: SampleConfig,
    resolver: Resolver,
    runner: Runner,
) -> ToolCheck:
    executable = resolve_configured_tool(
        spec.name,
        spec.command,
        config,
        resolver=resolver,
    )
    if executable is None:
        status: PreflightStatus = "FAIL" if spec.required else "WARNING"
        reason = f"TOOL_NOT_FOUND:{spec.name}"
        return ToolCheck(
            name=spec.name,
            command_name=spec.command,
            required=spec.required,
            expected_version=spec.expected,
            status=status,
            reason_codes=[reason],
        )
    code, output = runner([str(executable), *spec.version_args])
    observed = _version_evidence(output, spec.expected)
    if spec.name == "merqury" and spec.expected and not _contains_version(observed, spec.expected):
        package_version = _conda_package_version(executable, "merqury")
        if package_version is not None:
            observed = f"conda package merqury {package_version}"
    if spec.name == "merqury" and executable.exists():
        missing_assets = _missing_merqury_runtime_assets(executable)
        if missing_assets:
            return ToolCheck(
                name=spec.name,
                command_name=spec.command,
                required=spec.required,
                executable=executable,
                version=observed,
                expected_version=spec.expected,
                status="FAIL",
                reason_codes=["MERQURY_RUNTIME_ASSETS_MISSING:" + ",".join(missing_assets)],
            )
    if spec.name == "rscript":
        package_code, _ = runner(
            [
                str(executable),
                "-e",
                (
                    "packages <- c('argparse','ggplot2','scales'); "
                    "ok <- vapply(packages, requireNamespace, logical(1), quietly=TRUE); "
                    "if (!all(ok)) stop(paste(packages[!ok], collapse=','))"
                ),
            ]
        )
        if package_code != 0:
            return ToolCheck(
                name=spec.name,
                command_name=spec.command,
                required=spec.required,
                executable=executable,
                version=observed,
                expected_version=spec.expected,
                status="FAIL",
                reason_codes=["R_REQUIRED_PACKAGES_UNAVAILABLE"],
            )
    if code != 0 and spec.name not in {"merqury", "genomescope"}:
        return ToolCheck(
            name=spec.name,
            command_name=spec.command,
            required=spec.required,
            executable=executable,
            version=observed,
            expected_version=spec.expected,
            status="FAIL" if spec.required else "WARNING",
            reason_codes=[f"TOOL_VERSION_COMMAND_FAILED:{spec.name}"],
        )
    mismatch = _version_mismatch(spec.name, observed, spec.expected)
    if mismatch:
        return ToolCheck(
            name=spec.name,
            command_name=spec.command,
            required=spec.required,
            executable=executable,
            version=observed,
            expected_version=spec.expected,
            status="FAIL" if spec.required else "WARNING",
            reason_codes=[f"TOOL_VERSION_MISMATCH:{spec.name}"],
        )
    reasons = [] if observed else [f"TOOL_VERSION_NOT_REPORTED:{spec.name}"]
    return ToolCheck(
        name=spec.name,
        command_name=spec.command,
        required=spec.required,
        executable=executable,
        version=observed,
        expected_version=spec.expected,
        status="WARNING" if reasons else "PASS",
        reason_codes=reasons,
    )


def _check_coverage_backend(
    config: SampleConfig,
    *,
    resolver: Resolver,
    runner: Runner,
) -> tuple[Literal["mosdepth", "bedtools"] | None, ToolCheck]:
    requested = config.tools.coverage_backend
    names: tuple[Literal["mosdepth", "bedtools"], ...]
    names = ("mosdepth", "bedtools") if requested == "auto" else (requested,)
    for name in names:
        command = name
        executable = resolve_configured_tool(name, command, config, resolver=resolver)
        if executable is None:
            continue
        args = ["--version"]
        code, output = runner([str(executable), *args])
        expected = "2.31.1" if name == "bedtools" else None
        version = _version_evidence(output, expected)
        if code == 0:
            mismatch = _version_mismatch(name, version, expected)
            return name, ToolCheck(
                name=name,
                command_name=command,
                required=True,
                executable=executable,
                version=version,
                expected_version=expected,
                status="FAIL" if mismatch else "PASS",
                reason_codes=[f"TOOL_VERSION_MISMATCH:{name}"] if mismatch else [],
            )
    missing_name: ToolName = "mosdepth" if requested == "mosdepth" else "bedtools"
    return None, ToolCheck(
        name=missing_name,
        command_name=str(requested),
        required=True,
        status="FAIL",
        reason_codes=["NO_SUPPORTED_COVERAGE_BACKEND"],
    )


def _version_mismatch(name: ToolName, observed: str | None, expected: str | None) -> bool:
    if observed is None or expected is None:
        return False
    if name == "java":
        match = re.search(r'version\s+"(?P<major>[0-9]+)', observed)
        return match is None or match.group("major") != expected
    return expected.lower() not in observed.lower()


def _run_version_command(command: Sequence[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=_version_command_environment(Path(command[0])),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return completed.returncode, "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    ).strip()


def _first_nonempty_line(value: str) -> str | None:
    return next((line.strip() for line in value.splitlines() if line.strip()), None)


def _version_command_environment(executable: Path) -> dict[str, str]:
    """Keep script shebang resolution inside the executable's own conda prefix."""
    environment = os.environ.copy()
    prefix = next(
        (parent for parent in executable.resolve().parents if (parent / "conda-meta").is_dir()),
        None,
    )
    if prefix is not None:
        system_paths = [
            path for path in ("/usr/local/bin", "/usr/bin", "/bin") if Path(path).is_dir()
        ]
        environment["PATH"] = os.pathsep.join([str(prefix / "bin"), *system_paths])
    return environment


def _version_evidence(value: str, expected: str | None) -> str | None:
    """Prefer the line containing the locked version over banners or usage text."""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if expected is not None:
        matching = next((line for line in lines if expected.lower() in line.lower()), None)
        if matching is not None:
            return matching
    return lines[0] if lines else None


def _contains_version(observed: str | None, expected: str) -> bool:
    return observed is not None and expected.lower() in observed.lower()


def _conda_package_version(executable: Path, package_name: str) -> str | None:
    """Read version evidence from the active executable's own conda metadata."""
    metadata = next(
        (
            parent / "conda-meta"
            for parent in executable.parents
            if (parent / "conda-meta").is_dir()
        ),
        None,
    )
    if metadata is None:
        return None
    candidates = sorted(metadata.glob(f"{package_name}-*.json"))
    for path in reversed(candidates):
        try:
            import json

            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        version = payload.get("version")
        if isinstance(version, str) and version:
            return version
    return None


def _missing_merqury_runtime_assets(executable: Path) -> list[str]:
    """Check assets sourced or executed by the resolved Merqury distribution."""
    root = executable.resolve().parent
    required = (
        Path("util/util.sh"),
        Path("eval/spectra-cn.sh"),
        Path("eval/qv.sh"),
    )
    return [path.as_posix() for path in required if not (root / path).is_file()]


def _total_memory_gib() -> float:
    """Return physical memory without adding a runtime dependency."""
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return 0.0
    return float(pages * page_size) / (1024**3)


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _minimum_disk(config: SampleConfig) -> float:
    return config.execution_budget.min_free_disk_gib


def _busco_dataset_path(download_path: Path, lineage: str) -> Path | None:
    for candidate in (download_path / lineage, download_path / "lineages" / lineage):
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_directory(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(_sha256(path).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _parse_busco_dataset_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _required_dataset_value(values: dict[str, str], key: str) -> str:
    value = values.get(key)
    if not value:
        raise ValueError(f"BUSCO dataset.cfg lacks required field: {key}")
    return value
