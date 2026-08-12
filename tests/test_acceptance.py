import hashlib
import os
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
DATASET_ID = "acceptance_dataset"


def _dataset_registry(tmp_path: Path) -> tuple[Path, Path]:
    """Create a governed registry for neutral local acceptance bytes."""
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    registry = tmp_path / "datasets.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent",
                "registry_id": "acceptance-test-datasets",
                "datasets": [
                    {
                        "dataset_id": DATASET_ID,
                        "species": "Unspecified test taxon",
                        "taxon_id": 1,
                        "read_technology": "pacbio_hifi",
                        "accession": "LOCAL_TEST_INPUT",
                        "source_uri": "https://example.invalid/reads.fastq",
                        "source_archive": "local-test-fixture",
                        "usage_policy": "Test-only generated content",
                        "usage_policy_uri": "https://example.invalid/policy",
                        "approved_usage": ["software acceptance"],
                        "locator": {
                            "root_env": "HIFI_AGENT_TEST_DATA_ROOT",
                            "relative_path": reads.name,
                        },
                        "bytes": reads.stat().st_size,
                        "sha256": hashlib.sha256(reads.read_bytes()).hexdigest(),
                        "read_count": 1,
                        "total_bases": 4,
                        "expected_genome_size": 4,
                        "expected_genome_size_source": "generated fixture",
                        "ploidy": 1,
                        "inbred": None,
                        "reference": None,
                        "busco_lineage": "eukaryota_odb12",
                        "limitations": ["Not biological evidence"],
                    }
                ],
            }
        )
    )
    return registry, reads


def test_external_registry_has_complete_governance_fields(tmp_path: Path) -> None:
    registry, reads = _dataset_registry(tmp_path)
    record = load_dataset(registry, DATASET_ID)

    assert record.accession == "LOCAL_TEST_INPUT"
    assert record.read_technology == "pacbio_hifi"
    assert record.bytes == reads.stat().st_size
    assert record.read_count == 1
    assert record.total_bases == 4
    assert record.expected_genome_size == 4
    assert record.busco_lineage == "eukaryota_odb12"
    assert record.reference is None
    assert record.approved_usage


def test_dataset_resolution_requires_explicit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, _ = _dataset_registry(tmp_path)
    monkeypatch.delenv("HIFI_AGENT_DATA_ROOT", raising=False)
    monkeypatch.delenv("HIFI_AGENT_TEST_DATA_ROOT", raising=False)

    with pytest.raises(InputValidationError, match="is not set"):
        resolve_dataset(registry, DATASET_ID)


def test_dataset_resolution_hashes_external_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, reads = _dataset_registry(tmp_path)
    monkeypatch.setenv("HIFI_AGENT_TEST_DATA_ROOT", os.fspath(tmp_path))

    resolved = resolve_dataset(registry, DATASET_ID)

    assert resolved.path == reads.resolve()
    assert resolved.observed_bytes == reads.stat().st_size
    assert resolved.observed_sha256 == hashlib.sha256(reads.read_bytes()).hexdigest()


def test_wheel_gate_requires_byte_identical_current_sources(tmp_path: Path) -> None:
    wheel = tmp_path / "hifi_agent-3.0.0-py3-none-any.whl"
    package_root = PROJECT_ROOT / "src/hifi_agent"
    sources = sorted(package_root.rglob("*.py"))
    resources = sorted(
        path
        for path in (package_root / "data").rglob("*")
        if path.is_file() and path.suffix in {".config", ".json", ".nf", ".yaml"}
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        for source in [*sources, *resources]:
            archive.write(source, source.relative_to(PROJECT_ROOT / "src").as_posix())
        archive.writestr(
            "hifi_agent-3.0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: hifi-agent\nVersion: 3.0.0\n",
        )

    _verify_wheel_source(wheel, "3.0.0")

    corrupt = tmp_path / "hifi_agent-3.0.0-corrupt-py3-none-any.whl"
    with zipfile.ZipFile(corrupt, "w") as archive:
        for source in [*sources, *resources]:
            name = source.relative_to(PROJECT_ROOT / "src").as_posix()
            content = "changed\n" if name == "hifi_agent/constants.py" else source.read_bytes()
            archive.writestr(name, content)
        archive.writestr(
            "hifi_agent-3.0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: hifi-agent\nVersion: 3.0.0\n",
        )
    with pytest.raises(InputValidationError, match="source bytes"):
        _verify_wheel_source(corrupt, "3.0.0")

    missing_resource = tmp_path / "hifi_agent-3.0.0-missing-resource-py3-none-any.whl"
    omitted = "hifi_agent/data/workflow/main.nf"
    with zipfile.ZipFile(missing_resource, "w") as archive:
        for source in [*sources, *resources]:
            name = source.relative_to(PROJECT_ROOT / "src").as_posix()
            if name != omitted:
                archive.write(source, name)
        archive.writestr(
            "hifi_agent-3.0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: hifi-agent\nVersion: 3.0.0\n",
        )
    with pytest.raises(InputValidationError, match="missing production runtime resources"):
        _verify_wheel_source(missing_resource, "3.0.0")


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
