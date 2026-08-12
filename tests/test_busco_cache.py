from pathlib import Path

import pytest

from hifi_agent.exceptions import ToolExecutionError
from hifi_agent.orchestration.busco_cache import prepare_busco_lineage
from hifi_agent.schemas.sample import SampleConfig, ToolchainConfig


def _sample(tmp_path: Path, *, download: bool) -> SampleConfig:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    executable = tmp_path / "bin/busco"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    return SampleConfig(
        schema_id="hifi-agent",
        sample_id="sample",
        read_technology="pacbio_hifi",
        hifi_reads=[reads],
        outdir=tmp_path / "run",
        busco_lineage="diptera_odb12",
        tools=ToolchainConfig(
            executable_overrides={"busco": executable},
            busco_lineage_dir=tmp_path / "cache/busco",
            download_missing_busco=download,
        ),
    )


def test_missing_busco_lineage_is_downloaded_to_shared_cache_once(tmp_path: Path) -> None:
    sample = _sample(tmp_path, download=True)
    calls: list[list[str]] = []

    def runner(command: list[str], cwd: Path, environment: dict[str, str]) -> int:
        del environment
        calls.append(command)
        dataset = cwd / "diptera_odb12"
        dataset.mkdir()
        (dataset / "dataset.cfg").write_text("dataset_version=1\n")
        return 0

    first = prepare_busco_lineage(sample, runner=runner)
    second = prepare_busco_lineage(sample, runner=runner)

    assert first == (tmp_path / "cache/busco/diptera_odb12").resolve()
    assert second == first
    assert calls == [
        [
            str(sample.tools.executable_overrides["busco"]),
            "--download",
            "diptera_odb12",
            "--download_path",
            str(sample.tools.busco_lineage_dir),
        ]
    ]


def test_missing_busco_lineage_fails_when_download_is_disabled(tmp_path: Path) -> None:
    sample = _sample(tmp_path, download=False)

    with pytest.raises(ToolExecutionError, match="absent from the configured cache"):
        prepare_busco_lineage(sample)


def test_busco_download_success_requires_dataset_metadata(tmp_path: Path) -> None:
    sample = _sample(tmp_path, download=True)

    with pytest.raises(ToolExecutionError, match="metadata is missing"):
        prepare_busco_lineage(sample, runner=lambda _command, _cwd, _environment: 0)
