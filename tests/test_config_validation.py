import gzip
import json
from pathlib import Path

import pytest
import yaml

import hifi_agent.config as config_module
from hifi_agent.config import (
    validate_config_file,
    verify_recorded_input_checksums,
    verify_validation_receipt,
)
from hifi_agent.exceptions import InputValidationError
from hifi_agent.schemas.sample import ResourceConfig


def _fastq(path: Path) -> Path:
    path.write_text("@read1\nACGT\n+\nIIII\n")
    return path


def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "schema_id": "hifi-agent",
        "sample_id": "sample_01",
        "read_technology": "pacbio_hifi",
        "hifi_reads": [str(_fastq(tmp_path / "reads.fastq"))],
        "outdir": str(tmp_path / "results/sample_01"),
        "resources": {"max_threads": 4, "max_memory_gb": 16},
        "execution_budget": {"min_free_disk_gib": 0},
    }


def _write(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "sample.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _split_config(tmp_path: Path) -> tuple[Path, Path, Path]:
    config_root = tmp_path / "config"
    sample_root = config_root / "samples"
    data_root = tmp_path / "Data"
    sample_root.mkdir(parents=True)
    data_root.mkdir()
    reads = _fastq(data_root / "reads.fastq")
    runtime = config_root / "runtime.yaml"
    runtime.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent-runtime",
                "paths": {
                    "data_root": "../Data",
                    "output_root": "../results",
                    "cache_root": "../cache",
                },
                "resources": {"max_threads": 8, "max_memory_gb": 32},
                "execution_budget": {"min_free_disk_gib": 0},
                "tools": {"busco_cache": "busco"},
                "runtime": {"resume_mode": "auto", "retention": "standard"},
            },
            sort_keys=False,
        )
    )
    sample = sample_root / "sample.yaml"
    sample.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent-sample",
                "runtime_config": "../runtime.yaml",
                "sample_id": "sample_01",
                "read_technology": "pacbio_hifi",
                "hifi_reads": [reads.name],
                "species_name": "Test species",
                "expected_genome_size": 1000,
                "ploidy": 2,
            },
            sort_keys=False,
        )
    )
    return sample, runtime, reads


def test_native_validation_writes_all_identity_inputs(tmp_path: Path) -> None:
    result = validate_config_file(_write(tmp_path, _config(tmp_path)))

    assert result.resolved_config.is_file()
    assert result.input_checksums.is_file()
    assert result.input_manifest.is_file()
    assert result.validation_receipt.is_file()
    manifest = json.loads(result.input_manifest.read_text())
    receipt = json.loads(result.validation_receipt.read_text())
    assert manifest["schema_id"] == "hifi-agent"
    assert receipt["schema_id"] == "hifi-agent"
    assert receipt["read_technology_source"] == "USER_DECLARED_NOT_INFERRED"


def test_split_configuration_resolves_non_overlapping_roots_and_sources(tmp_path: Path) -> None:
    sample, runtime, reads = _split_config(tmp_path)

    result = validate_config_file(sample)

    assert result.config.hifi_reads == [reads.resolve()]
    assert result.config.outdir == (tmp_path / "results/sample_01").resolve()
    assert result.config.tools.busco_lineage_dir == (tmp_path / "cache/busco").resolve()
    assert result.config.resources.max_threads == 8
    assert result.config.runtime.resume_mode == "auto"
    assert result.config.runtime.retention == "standard"
    assert result.source_config == sample.resolve()
    assert result.runtime_source_config == runtime.resolve()
    assert result.field_sources["species_name"] == "sample"
    assert result.field_sources["resources.max_threads"] == "runtime"
    assert result.sample_config_snapshot.read_bytes() == sample.read_bytes()
    assert result.runtime_config_snapshot is not None
    assert result.runtime_config_snapshot.read_bytes() == runtime.read_bytes()
    verify_validation_receipt(result.config, result.validation_receipt)


def test_split_configuration_rejects_ownership_violations_and_path_escape(
    tmp_path: Path,
) -> None:
    sample, runtime, _reads = _split_config(tmp_path)
    sample_data = yaml.safe_load(sample.read_text())
    sample_data["resources"] = {"max_threads": 2}
    sample.write_text(yaml.safe_dump(sample_data))
    with pytest.raises(InputValidationError, match="resources"):
        validate_config_file(sample, write_outputs=False)

    sample_data.pop("resources")
    sample_data["hifi_reads"] = ["../outside.fastq"]
    sample.write_text(yaml.safe_dump(sample_data))
    with pytest.raises(InputValidationError, match="relative to runtime data_root"):
        validate_config_file(sample, write_outputs=False)

    sample_data["hifi_reads"] = ["reads.fastq"]
    sample.write_text(yaml.safe_dump(sample_data))
    runtime_data = yaml.safe_load(runtime.read_text())
    runtime_data["species_name"] = "wrong owner"
    runtime.write_text(yaml.safe_dump(runtime_data))
    with pytest.raises(InputValidationError, match="species_name"):
        validate_config_file(sample, write_outputs=False)


def test_split_configuration_reports_missing_runtime_file(tmp_path: Path) -> None:
    sample, runtime, _reads = _split_config(tmp_path)
    runtime.unlink()

    with pytest.raises(InputValidationError, match="Runtime configuration does not exist"):
        validate_config_file(sample, write_outputs=False)


def test_each_unique_input_is_hashed_once_per_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample, _runtime, reads = _split_config(tmp_path)
    sample_data = yaml.safe_load(sample.read_text())
    sample_data["kmer_reads"] = [reads.name]
    sample.write_text(yaml.safe_dump(sample_data))
    original = config_module._sha256
    calls: list[Path] = []

    def tracked(path: Path) -> str:
        if path.resolve() == reads.resolve():
            calls.append(path.resolve())
        return original(path)

    monkeypatch.setattr(config_module, "_sha256", tracked)

    result = validate_config_file(sample)

    assert calls == [reads.resolve()]
    assert len(json.loads(result.input_manifest.read_text())["entries"]) == 2


def test_single_read_string_is_normalized_to_a_list(tmp_path: Path) -> None:
    data = _config(tmp_path)
    data["hifi_reads"] = str(tmp_path / "reads.fastq")
    result = validate_config_file(_write(tmp_path, data), write_outputs=False)
    assert result.config.hifi_reads == [tmp_path / "reads.fastq"]


@pytest.mark.parametrize("missing", ["schema_id", "read_technology"])
def test_native_declarations_are_required(tmp_path: Path, missing: str) -> None:
    data = _config(tmp_path)
    data.pop(missing)
    with pytest.raises(InputValidationError, match=missing):
        validate_config_file(_write(tmp_path, data), write_outputs=False)


def test_unknown_top_level_field_is_rejected(tmp_path: Path) -> None:
    data = _config(tmp_path)
    data["unknown_setting"] = {"enabled": True}
    with pytest.raises(InputValidationError, match="unknown_setting"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)


@pytest.mark.parametrize("unsupported_schema", ["hifi_agent", "assembly-agent", "unsupported"])
def test_noncanonical_schemas_are_rejected(tmp_path: Path, unsupported_schema: str) -> None:
    data = _config(tmp_path)
    data["schema_id"] = unsupported_schema
    with pytest.raises(InputValidationError, match="schema_id"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)


@pytest.mark.parametrize("old_field", ["reads", "threads", "memory_gb", "run_version"])
def test_removed_configuration_fields_are_rejected(tmp_path: Path, old_field: str) -> None:
    data = _config(tmp_path)
    data[old_field] = "removed"
    with pytest.raises(InputValidationError, match=old_field):
        validate_config_file(_write(tmp_path, data), write_outputs=False)


@pytest.mark.parametrize("field", ["hi_c_reads", "ont_reads", "trio_reads"])
def test_out_of_scope_input_types_are_rejected(tmp_path: Path, field: str) -> None:
    data = _config(tmp_path)
    data[field] = ["reads.fastq"]
    with pytest.raises(InputValidationError, match="Unsupported input"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)


def test_missing_and_malformed_fastq_are_rejected(tmp_path: Path) -> None:
    data = _config(tmp_path)
    data["hifi_reads"] = [str(tmp_path / "missing.fastq")]
    with pytest.raises(InputValidationError, match="missing file"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)
    (tmp_path / "bad.fastq").write_text("read\nACGT\n+\nIIII\n")
    data["hifi_reads"] = [str(tmp_path / "bad.fastq")]
    with pytest.raises(InputValidationError, match="header"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)


def test_corrupt_gzip_is_rejected_and_valid_gzip_passes(tmp_path: Path) -> None:
    path = tmp_path / "reads.fastq.gz"
    path.write_bytes(b"bad")
    data = _config(tmp_path)
    data["hifi_reads"] = [str(path)]
    with pytest.raises(InputValidationError, match="corrupted gzip"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)
    with gzip.open(path, "wt") as handle:
        handle.write("@read\nACGT\n+\nIIII\n")
    assert validate_config_file(_write(tmp_path, data), write_outputs=False).config.hifi_reads


def test_receipts_detect_metadata_and_input_drift(tmp_path: Path) -> None:
    result = validate_config_file(_write(tmp_path, _config(tmp_path)))
    result.resolved_config.write_text("changed: true\n")
    with pytest.raises(InputValidationError, match="missing or changed"):
        verify_validation_receipt(result.config, result.validation_receipt)

    result = validate_config_file(_write(tmp_path, _config(tmp_path)))
    result.config.hifi_reads[0].write_text("@changed\nAAAA\n+\nIIII\n")
    with pytest.raises(InputValidationError, match="missing or changed"):
        verify_recorded_input_checksums(result.input_checksums)


def test_paths_and_resource_bounds_are_enforced(tmp_path: Path) -> None:
    assert ResourceConfig().max_threads == 480
    data = _config(tmp_path)
    data["sample_id"] = "bad/sample"
    with pytest.raises(InputValidationError, match="sample_id"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)
    data = _config(tmp_path)
    data["resources"] = {"max_threads": 0, "max_memory_gb": 16}
    with pytest.raises(InputValidationError, match="max_threads"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)
    data = _config(tmp_path)
    data["outdir"] = str(tmp_path)
    with pytest.raises(InputValidationError, match="would contain input"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)


def test_explicit_input_root_environment_resolves_portably(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "external-data"
    data_root.mkdir()
    reads = _fastq(data_root / "reads.fastq")
    monkeypatch.setenv("HIFI_AGENT_DATA_ROOT", str(data_root))
    data = _config(tmp_path)
    data["hifi_reads"] = ["reads.fastq"]
    data["input_root_env"] = "HIFI_AGENT_DATA_ROOT"

    result = validate_config_file(_write(tmp_path, data), write_outputs=False)

    assert result.config.hifi_reads == [reads.resolve()]


def test_explicit_input_root_rejects_missing_variable_and_path_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _config(tmp_path)
    data["hifi_reads"] = ["reads.fastq"]
    data["input_root_env"] = "HIFI_AGENT_DATA_ROOT"
    monkeypatch.delenv("HIFI_AGENT_DATA_ROOT", raising=False)
    with pytest.raises(InputValidationError, match="is not set"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)

    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setenv("HIFI_AGENT_DATA_ROOT", str(data_root))
    data["hifi_reads"] = ["../outside.fastq"]
    with pytest.raises(InputValidationError, match="safe relative paths"):
        validate_config_file(_write(tmp_path, data), write_outputs=False)
