from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from hifi_agent.exceptions import ToolExecutionError
from hifi_agent.orchestration.environment import (
    materialize_environment_manifest,
    require_environment_preflight,
    run_environment_preflight,
)
from hifi_agent.orchestration.runtime_config import resolve_runtime_config
from hifi_agent.schemas.sample import SampleConfig
from hifi_agent.tool_resolution import declared_subprocess_environment


def _config(
    tmp_path: Path,
    *,
    override: dict[str, str] | None = None,
) -> SampleConfig:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    path = tmp_path / "sample.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent",
                "sample_id": "sample",
                "read_technology": "pacbio_hifi",
                "hifi_reads": [str(reads)],
                "outdir": str(tmp_path / "run"),
                "execution_budget": {"min_free_disk_gib": 0},
                "tools": {"executable_overrides": override or {}},
            }
        )
    )
    return resolve_runtime_config(path).effective.sample


def _resolver(command: str) -> str | None:
    return f"/tools/{command}"


def _runner(command: Sequence[str]) -> tuple[int, str]:
    name = Path(command[0]).name
    versions = {
        "java": 'openjdk version "21.0.8"',
        "nextflow": "nextflow version 25.04.7",
        "hifiasm": "0.25.0-r726",
        "gfatools": "gfatools 0.5",
        "seqkit": "seqkit 2.10.1",
        "NanoPlot": "NanoPlot 1.47.1",
        "meryl": "meryl 1.3",
        "quast.py": "QUAST v5.3.0",
        "busco": "BUSCO 6.0.0",
        "merqury.sh": "Merqury 1.3",
        "minimap2": "2.30-r1287",
        "samtools": "samtools 1.22.1",
        "Rscript": "R scripting front-end version 4.4",
        "genomescope2": "GenomeScope 2.0",
        "mosdepth": "mosdepth 0.3.10",
        "bedtools": "bedtools 2.31.1",
    }
    return 0, versions[name]


def test_preflight_resolves_declared_tools_and_coverage_backend(tmp_path: Path) -> None:
    manifest = run_environment_preflight(
        _config(tmp_path),
        resolver=_resolver,
        runner=_runner,
    )

    assert manifest.status == "PASS"
    assert manifest.coverage_backend == "mosdepth"
    assert all(check.executable is not None for check in manifest.tools)
    assert not manifest.errors


def test_java_version_drift_is_a_hard_preflight_failure(tmp_path: Path) -> None:
    def wrong_java(command: Sequence[str]) -> tuple[int, str]:
        if Path(command[0]).name == "java":
            return 0, 'openjdk version "25.0.2"'
        return _runner(command)

    manifest = run_environment_preflight(
        _config(tmp_path),
        resolver=_resolver,
        runner=wrong_java,
    )

    assert manifest.status == "FAIL"
    assert "TOOL_VERSION_MISMATCH:java" in manifest.errors
    with pytest.raises(ToolExecutionError, match="preflight failed"):
        require_environment_preflight(manifest)


def test_nextflow_version_drift_is_a_hard_preflight_failure(tmp_path: Path) -> None:
    def wrong_nextflow(command: Sequence[str]) -> tuple[int, str]:
        if Path(command[0]).name == "nextflow":
            return 0, "nextflow version 24.10.0"
        return _runner(command)

    manifest = run_environment_preflight(
        _config(tmp_path),
        resolver=_resolver,
        runner=wrong_nextflow,
    )

    assert manifest.status == "FAIL"
    assert "TOOL_VERSION_MISMATCH:nextflow" in manifest.errors


def test_missing_required_tool_does_not_use_a_personal_host_fallback(tmp_path: Path) -> None:
    manifest = run_environment_preflight(
        _config(tmp_path),
        resolver=lambda command: None if command == "nextflow" else _resolver(command),
        runner=_runner,
    )

    assert manifest.status == "FAIL"
    assert "TOOL_NOT_FOUND:nextflow" in manifest.errors


def test_explicit_executable_override_is_resolved_from_config(tmp_path: Path) -> None:
    nextflow = tmp_path / "bin" / "nextflow"
    nextflow.parent.mkdir()
    nextflow.write_text("#!/bin/sh\n")
    nextflow.chmod(0o755)
    config = _config(tmp_path, override={"nextflow": str(nextflow)})

    manifest = run_environment_preflight(config, resolver=_resolver, runner=_runner)

    check = next(item for item in manifest.tools if item.name == "nextflow")
    assert check.executable == nextflow.resolve()


def test_merqury_missing_runtime_assets_is_a_hard_preflight_failure(tmp_path: Path) -> None:
    merqury = tmp_path / "merqury" / "merqury.sh"
    merqury.parent.mkdir()
    merqury.write_text("#!/bin/sh\nexit 0\n")
    merqury.chmod(0o755)
    config = _config(tmp_path, override={"merqury": str(merqury)})

    manifest = run_environment_preflight(config, resolver=_resolver, runner=_runner)

    assert manifest.status == "FAIL"
    assert any(reason.startswith("MERQURY_RUNTIME_ASSETS_MISSING:") for reason in manifest.errors)


def test_missing_merqury_r_packages_is_a_hard_preflight_failure(tmp_path: Path) -> None:
    def missing_r_packages(command: Sequence[str]) -> tuple[int, str]:
        if Path(command[0]).name == "Rscript" and "-e" in command:
            return 1, "argparse is unavailable"
        return _runner(command)

    manifest = run_environment_preflight(
        _config(tmp_path),
        resolver=_resolver,
        runner=missing_r_packages,
    )

    assert manifest.status == "FAIL"
    assert "R_REQUIRED_PACKAGES_UNAVAILABLE" in manifest.errors


def test_environment_manifest_is_atomically_materialized(tmp_path: Path) -> None:
    manifest = run_environment_preflight(
        _config(tmp_path),
        resolver=_resolver,
        runner=_runner,
    )
    output = tmp_path / "run/00_metadata/environment_manifest.json"

    materialize_environment_manifest(manifest, output)

    assert output.is_file()
    assert '"schema_id": "hifi-agent"' in output.read_text()


def test_offline_busco_lineage_is_required_and_checksum_bound(tmp_path: Path) -> None:
    config = _config(tmp_path)
    download = tmp_path / "busco_downloads"
    dataset = download / "diptera_odb12"
    dataset.mkdir(parents=True)
    dataset_config = dataset / "dataset.cfg"
    dataset_config.write_text(
        "creation_date=2026-01-01\n"
        "OrthoDB_version=12.1\n"
        "dataset_version=02\n"
        "number_of_BUSCOs=100\n"
        "number_of_species=10\n"
    )
    configured = config.model_copy(
        update={
            "busco_lineage": "diptera_odb12",
            "tools": config.tools.model_copy(update={"busco_lineage_dir": download}),
        }
    )

    manifest = run_environment_preflight(configured, resolver=_resolver, runner=_runner)

    assert manifest.status == "PASS"
    assert manifest.busco_lineage is not None
    assert manifest.busco_lineage.dataset_path == dataset.resolve()
    assert len(manifest.busco_lineage.dataset_config_sha256) == 64
    assert len(manifest.busco_lineage.dataset_sha256) == 64
    assert manifest.busco_lineage.busco_count == 100

    dataset_config.unlink()
    failed = run_environment_preflight(configured, resolver=_resolver, runner=_runner)
    assert failed.status == "FAIL"
    assert "BUSCO_LINEAGE_DATASET_NOT_FOUND" in failed.errors


def test_missing_downloadable_busco_lineage_is_a_preparation_warning(tmp_path: Path) -> None:
    config = _config(tmp_path)
    configured = config.model_copy(
        update={
            "busco_lineage": "diptera_odb12",
            "tools": config.tools.model_copy(
                update={
                    "busco_lineage_dir": tmp_path / "busco-cache",
                    "download_missing_busco": True,
                }
            ),
        }
    )

    manifest = run_environment_preflight(configured, resolver=_resolver, runner=_runner)

    assert manifest.status == "WARNING"
    assert manifest.errors == []
    assert "BUSCO_LINEAGE_DOWNLOAD_PENDING" in manifest.warnings


def test_subprocess_pythonpath_is_repository_controlled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", "/tmp/untrusted-pythonpath")

    environment = declared_subprocess_environment(_config(tmp_path))

    assert environment["PYTHONPATH"] == str(Path(__file__).resolve().parents[1] / "src")
