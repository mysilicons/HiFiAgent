import hashlib
import zipfile
from pathlib import Path

import pytest
import yaml

from hifi_agent.acceptance import (
    _verify_source_config_binding,
    _verify_wheel_source,
    load_dataset,
    resolve_dataset,
)
from hifi_agent.exceptions import InputValidationError
from hifi_agent.orchestration.runtime_config import resolve_runtime_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "drosophila_melanogaster_srr33554835"


def test_frozen_drosophila_registry_has_complete_governance_fields() -> None:
    record = load_dataset(PROJECT_ROOT / "benchmark/datasets.yaml", DATASET_ID)

    assert record.accession == "SRR33554835"
    assert record.read_technology == "pacbio_hifi"
    assert record.bytes == 34_915_862_206
    assert record.read_count == 2_430_495
    assert record.total_bases == 17_357_574_041
    assert record.expected_genome_size == 180_000_000
    assert record.busco_lineage == "diptera_odb12"
    assert record.reference is None
    assert record.approved_usage


def test_dataset_resolution_requires_explicit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del tmp_path
    monkeypatch.delenv("HIFI_AGENT_DATA_ROOT", raising=False)

    with pytest.raises(InputValidationError, match="is not set"):
        resolve_dataset(PROJECT_ROOT / "benchmark/datasets.yaml", DATASET_ID)


def test_wheel_gate_requires_byte_identical_current_sources(tmp_path: Path) -> None:
    wheel = tmp_path / "hifi_agent-3.0.0-py3-none-any.whl"
    sources = sorted((PROJECT_ROOT / "src/hifi_agent").rglob("*.py"))
    with zipfile.ZipFile(wheel, "w") as archive:
        for source in sources:
            archive.write(source, source.relative_to(PROJECT_ROOT / "src").as_posix())
        archive.writestr(
            "hifi_agent-3.0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: hifi-agent\nVersion: 3.0.0\n",
        )

    _verify_wheel_source(wheel, "3.0.0")

    corrupt = tmp_path / "hifi_agent-3.0.0-corrupt-py3-none-any.whl"
    with zipfile.ZipFile(corrupt, "w") as archive:
        for source in sources:
            name = source.relative_to(PROJECT_ROOT / "src").as_posix()
            content = "changed\n" if name == "hifi_agent/constants.py" else source.read_bytes()
            archive.writestr(name, content)
        archive.writestr(
            "hifi_agent-3.0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: hifi-agent\nVersion: 3.0.0\n",
        )
    with pytest.raises(InputValidationError, match="source bytes"):
        _verify_wheel_source(corrupt, "3.0.0")


def test_source_config_must_reproduce_run_effective_config(tmp_path: Path) -> None:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    run_dir = tmp_path / "run"
    config = tmp_path / "sample.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent",
                "sample_id": "sample",
                "read_technology": "pacbio_hifi",
                "hifi_reads": [str(reads)],
                "outdir": str(run_dir),
                "optimization": {"enabled": False},
                "execution_budget": {"min_free_disk_gib": 0},
            }
        )
    )
    runtime = resolve_runtime_config(config, write_outputs=True)
    effective_sha256 = hashlib.sha256(runtime.effective_config_path.read_bytes()).hexdigest()
    _verify_source_config_binding(
        config,
        expected_effective_sha256=effective_sha256,
        run_dir=run_dir,
    )

    wrong = hashlib.sha256(b"different config").hexdigest()
    with pytest.raises(InputValidationError, match="does not reproduce"):
        _verify_source_config_binding(
            config,
            expected_effective_sha256=wrong,
            run_dir=run_dir,
        )
