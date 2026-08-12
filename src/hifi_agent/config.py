"""Configuration loading, input validation, and metadata outputs."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ValidationError

from hifi_agent.exceptions import InputValidationError
from hifi_agent.schemas.configuration import RuntimeFileConfig, SampleFileConfig
from hifi_agent.schemas.sample import (
    ExecutionBudgetConfig,
    KmerConfig,
    MappingQcConfig,
    OptimizationConfig,
    ResourceConfig,
    RuntimeBehaviorConfig,
    SampleConfig,
    ToolchainConfig,
)

UNSUPPORTED_INPUT_FIELDS = frozenset(
    {
        "hi_c_reads",
        "hic_reads",
        "hic",
        "ont_reads",
        "ultra_long_reads",
        "ultralong_reads",
        "trio_reads",
        "parental_reads",
    }
)

FASTQ_SUFFIXES = (
    ".fastq",
    ".fq",
    ".fastq.gz",
    ".fq.gz",
)

CHECKSUM_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ConfigValidationResult:
    """Result of a successful config validation run."""

    config: SampleConfig
    metadata_dir: Path
    resolved_config: Path
    input_checksums: Path
    input_manifest: Path
    validation_receipt: Path
    sample_config_snapshot: Path
    runtime_config_snapshot: Path | None
    source_config: Path
    runtime_source_config: Path | None
    field_sources: dict[str, Literal["sample", "runtime", "config", "default"]]


@dataclass(frozen=True)
class _ConfigBundle:
    """One external configuration pair compiled to the canonical internal model."""

    config: SampleConfig
    sample_bytes: bytes
    runtime_bytes: bytes | None
    runtime_path: Path | None
    field_sources: dict[str, Literal["sample", "runtime", "config", "default"]]


@dataclass(frozen=True)
class _InputDigest:
    """One role/path entry backed by a digest calculated once per unique file."""

    role: str
    path: Path
    sha256: str
    bytes: int


def validate_config_file(
    config_path: Path,
    *,
    write_outputs: bool = True,
) -> ConfigValidationResult:
    """Load, validate, and optionally materialize metadata for a sample config."""
    source_config = config_path.resolve()
    bundle = _load_config_bundle(source_config)
    resolved_config = _resolve_config_paths(bundle.config, source_config.parent)
    validate_sample_inputs(resolved_config)

    metadata_dir = resolved_config.outdir / "00_metadata"
    resolved_config_path = metadata_dir / "resolved_config.yaml"
    input_checksums_path = metadata_dir / "input_checksums.tsv"
    input_manifest_path = metadata_dir / "input_manifest.json"
    validation_receipt_path = metadata_dir / "validation_receipt.json"
    sample_snapshot_path = metadata_dir / "sample_config_snapshot.yaml"
    runtime_snapshot_path = (
        metadata_dir / "runtime_config_snapshot.yaml" if bundle.runtime_bytes is not None else None
    )

    if write_outputs:
        metadata_dir.mkdir(parents=True, exist_ok=True)
        _atomic_bytes(sample_snapshot_path, bundle.sample_bytes)
        if runtime_snapshot_path is not None and bundle.runtime_bytes is not None:
            _atomic_bytes(runtime_snapshot_path, bundle.runtime_bytes)
        _write_resolved_config(resolved_config, resolved_config_path)
        input_digests = _collect_input_digests(resolved_config)
        _write_input_checksums(input_digests, input_checksums_path)
        _write_input_manifest(resolved_config, input_digests, input_manifest_path)
        _write_validation_receipt(
            resolved_config,
            resolved_config_path,
            input_checksums_path,
            input_manifest_path,
            validation_receipt_path,
            sample_config_snapshot=sample_snapshot_path,
            runtime_config_snapshot=runtime_snapshot_path,
        )

    return ConfigValidationResult(
        config=resolved_config,
        metadata_dir=metadata_dir,
        resolved_config=resolved_config_path,
        input_checksums=input_checksums_path,
        input_manifest=input_manifest_path,
        validation_receipt=validation_receipt_path,
        sample_config_snapshot=sample_snapshot_path,
        runtime_config_snapshot=runtime_snapshot_path,
        source_config=source_config,
        runtime_source_config=bundle.runtime_path,
        field_sources=bundle.field_sources,
    )


def _load_config_bundle(config_path: Path) -> _ConfigBundle:
    raw, sample_bytes = _read_yaml_mapping(config_path, label="sample configuration")
    _reject_unsupported_input_fields(raw)
    if raw.get("schema_id") == "hifi-agent-sample":
        return _compile_split_configuration(config_path, raw, sample_bytes)
    try:
        config = SampleConfig.model_validate(raw)
    except ValidationError as exc:
        raise InputValidationError(_format_pydantic_errors(exc)) from exc
    return _ConfigBundle(
        config=config,
        sample_bytes=sample_bytes,
        runtime_bytes=None,
        runtime_path=None,
        field_sources=_flat_field_sources(raw),
    )


def _compile_split_configuration(
    sample_path: Path,
    raw_sample: Mapping[str, Any],
    sample_bytes: bytes,
) -> _ConfigBundle:
    """Compile the non-overlapping sample/runtime pair into one canonical config."""
    try:
        sample = SampleFileConfig.model_validate(raw_sample)
    except ValidationError as exc:
        raise InputValidationError(_format_pydantic_errors(exc)) from exc
    runtime_path = _resolve_path(sample.runtime_config, sample_path.parent)
    raw_runtime, runtime_bytes = _read_yaml_mapping(
        runtime_path,
        label="runtime configuration",
    )
    try:
        runtime = RuntimeFileConfig.model_validate(raw_runtime)
    except ValidationError as exc:
        raise InputValidationError(_format_pydantic_errors(exc)) from exc

    runtime_base = runtime_path.parent
    data_root = _resolve_path(runtime.paths.data_root, runtime_base)
    output_root = _resolve_path(runtime.paths.output_root, runtime_base)
    cache_root = _resolve_path(runtime.paths.cache_root, runtime_base)
    output_name = sample.output_name or sample.sample_id
    if not re.fullmatch(r"[A-Za-z0-9_-]+", output_name):
        raise InputValidationError(
            "Sample configuration field `output_name` must use only letters, numbers, "
            "underscores, and hyphens"
        )

    hifi_reads = [
        _resolve_sample_input(path, data_root, field_name="hifi_reads")
        for path in sample.hifi_reads
    ]
    kmer_reads = (
        [
            _resolve_sample_input(path, data_root, field_name="kmer_reads")
            for path in sample.kmer_reads
        ]
        if sample.kmer_reads is not None
        else None
    )
    reference = (
        _resolve_sample_input(sample.reference_genome, data_root, field_name="reference_genome")
        if sample.reference_genome is not None
        else None
    )
    executable_overrides = {
        name: _resolve_path(path, runtime_base)
        for name, path in runtime.tools.executable_overrides.items()
    }
    busco_cache = (
        runtime.tools.busco_cache.resolve()
        if runtime.tools.busco_cache.is_absolute()
        else (cache_root / runtime.tools.busco_cache).resolve()
    )
    tools = ToolchainConfig(
        executable_overrides=executable_overrides,
        busco_lineage_dir=busco_cache,
        download_missing_busco=runtime.tools.download_missing_busco,
        coverage_backend=runtime.tools.coverage_backend,
    )
    optimization = runtime.optimization.model_copy(
        update={
            "llm_replay_transcript": (
                _resolve_path(runtime.optimization.llm_replay_transcript, runtime_base)
                if runtime.optimization.llm_replay_transcript is not None
                else None
            )
        }
    )
    try:
        compiled = SampleConfig(
            schema_id="hifi-agent",
            sample_id=sample.sample_id,
            read_technology=sample.read_technology,
            hifi_reads=hifi_reads,
            outdir=(output_root / output_name).resolve(),
            species_name=sample.species_name,
            expected_genome_size=sample.expected_genome_size,
            ploidy=sample.ploidy,
            inbred=sample.inbred,
            busco_lineage=sample.busco_lineage,
            kmer_reads=kmer_reads,
            reference_genome=reference,
            resources=runtime.resources,
            optimization=optimization,
            execution_budget=runtime.execution_budget,
            tools=tools,
            kmer=runtime.kmer,
            mapping_qc=runtime.mapping_qc,
            runtime=runtime.runtime,
        )
    except ValidationError as exc:
        raise InputValidationError(_format_pydantic_errors(exc)) from exc
    return _ConfigBundle(
        config=compiled,
        sample_bytes=sample_bytes,
        runtime_bytes=runtime_bytes,
        runtime_path=runtime_path,
        field_sources=_split_field_sources(raw_sample, raw_runtime),
    )


def _resolve_sample_input(path: Path, data_root: Path, *, field_name: str) -> Path:
    if path.is_absolute() or ".." in path.parts:
        raise InputValidationError(
            f"Sample configuration field `{field_name}` must be relative to runtime data_root"
        )
    resolved = (data_root / path).resolve()
    try:
        resolved.relative_to(data_root)
    except ValueError as exc:
        raise InputValidationError(
            f"Sample configuration field `{field_name}` escapes runtime data_root"
        ) from exc
    return resolved


def _read_yaml_mapping(path: Path, *, label: str) -> tuple[Mapping[str, Any], bytes]:
    if not path.is_file():
        raise InputValidationError(f"{label.capitalize()} does not exist: {path}")
    try:
        raw_bytes = path.read_bytes()
        data = yaml.safe_load(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise InputValidationError(f"Unable to read {label}: {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise InputValidationError(f"{label.capitalize()} must contain a YAML mapping: {path}")
    return cast(Mapping[str, Any], data), raw_bytes


def _flat_field_sources(
    raw: Mapping[str, Any],
) -> dict[str, Literal["sample", "runtime", "config", "default"]]:
    sources: dict[str, Literal["sample", "runtime", "config", "default"]] = {}
    nested_types: dict[str, type[BaseModel]] = {
        "resources": ResourceConfig,
        "optimization": OptimizationConfig,
        "execution_budget": ExecutionBudgetConfig,
        "tools": ToolchainConfig,
        "kmer": KmerConfig,
        "mapping_qc": MappingQcConfig,
        "runtime": RuntimeBehaviorConfig,
    }
    for field in SampleConfig.model_fields:
        value = raw.get(field)
        if isinstance(value, Mapping):
            model_type = nested_types.get(field)
            if model_type is not None:
                for nested in model_type.model_fields:
                    sources[f"{field}.{nested}"] = "config" if nested in value else "default"
                continue
        sources[field] = "config" if field in raw else "default"
    return sources


def _split_field_sources(
    sample: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Literal["sample", "runtime", "config", "default"]]:
    sources: dict[str, Literal["sample", "runtime", "config", "default"]] = {
        field: "sample" if field in sample else "default"
        for field in (
            "schema_id",
            "sample_id",
            "read_technology",
            "hifi_reads",
            "species_name",
            "expected_genome_size",
            "ploidy",
            "inbred",
            "busco_lineage",
            "kmer_reads",
            "reference_genome",
        )
    }
    sources["outdir"] = "runtime"
    sources["input_root_env"] = "default"
    nested_sections = (
        "resources",
        "optimization",
        "execution_budget",
        "kmer",
        "mapping_qc",
        "runtime",
    )
    parsed_runtime = RuntimeFileConfig.model_validate(runtime)
    for section in nested_sections:
        model = getattr(parsed_runtime, section)
        raw_section = runtime.get(section)
        raw_mapping = raw_section if isinstance(raw_section, Mapping) else {}
        for field in model.__class__.model_fields:
            sources[f"{section}.{field}"] = "runtime" if field in raw_mapping else "default"
    raw_tools = runtime.get("tools")
    tool_mapping = raw_tools if isinstance(raw_tools, Mapping) else {}
    for field in ToolchainConfig.model_fields:
        external_name = "busco_cache" if field == "busco_lineage_dir" else field
        sources[f"tools.{field}"] = "runtime" if external_name in tool_mapping else "default"
    return sources


def validate_sample_inputs(config: SampleConfig) -> None:
    """Validate filesystem, compression, and minimal FASTQ constraints."""
    input_paths = list(_iter_input_paths(config))
    _validate_outdir_does_not_contain_inputs(config.outdir, input_paths)

    for read_path in config.hifi_reads:
        _validate_read_path(read_path)
        if read_path.suffix == ".gz":
            _validate_gzip_integrity(read_path)
        _validate_fastq_first_record(read_path)

    if config.kmer_reads is not None:
        for read_path in config.kmer_reads:
            _validate_read_path(read_path, field_name="kmer_reads")
            if read_path.suffix == ".gz":
                _validate_gzip_integrity(read_path)
            _validate_fastq_first_record(read_path, field_name="kmer_reads")
    if config.reference_genome is not None:
        _validate_existing_file(config.reference_genome, field_name="reference_genome")
    if config.optimization.llm_replay_transcript is not None:
        _validate_existing_file(
            config.optimization.llm_replay_transcript,
            field_name="optimization.llm_replay_transcript",
        )


def verify_validation_receipt(config: SampleConfig, receipt_path: Path) -> None:
    """Verify that the validation receipt still matches its metadata artifacts."""
    if not receipt_path.is_file():
        raise InputValidationError(f"Validated workflow receipt is missing: {receipt_path}")
    try:
        data = json.loads(receipt_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise InputValidationError(
            f"Validation receipt is unreadable: {receipt_path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise InputValidationError(f"Validation receipt must contain a JSON object: {receipt_path}")
    if data.get("status") != "PASS" or data.get("sample_id") != config.sample_id:
        raise InputValidationError(
            f"Validation receipt does not authorize sample `{config.sample_id}`: {receipt_path}"
        )
    artifacts: list[tuple[str, str]] = [
        ("resolved_config", "resolved_config_sha256"),
        ("input_checksums", "input_checksums_sha256"),
        ("input_manifest", "input_manifest_sha256"),
        ("sample_config_snapshot", "sample_config_snapshot_sha256"),
    ]
    if "runtime_config_snapshot" in data:
        artifacts.append(("runtime_config_snapshot", "runtime_config_snapshot_sha256"))
    for path_key, digest_key in artifacts:
        artifact_value = data.get(path_key)
        expected_digest = data.get(digest_key)
        if not isinstance(artifact_value, str) or not isinstance(expected_digest, str):
            raise InputValidationError(f"Validation receipt field `{path_key}` is invalid")
        artifact = Path(artifact_value)
        if not artifact.is_file() or _sha256(artifact) != expected_digest:
            raise InputValidationError(
                f"Validation receipt artifact `{path_key}` is missing or changed: {artifact}"
            )


def verify_recorded_input_checksums(input_checksums_path: Path) -> None:
    """Re-hash recorded inputs before evaluating an existing run directory."""
    if not input_checksums_path.is_file():
        raise InputValidationError(f"Input checksum manifest is missing: {input_checksums_path}")
    lines = input_checksums_path.read_text().splitlines()
    if not lines or lines[0] != "role\tpath\tsha256\tbytes":
        raise InputValidationError(
            f"Input checksum manifest header is invalid: {input_checksums_path}"
        )
    observed: dict[Path, tuple[str, str]] = {}
    for line_number, line in enumerate(lines[1:], start=2):
        parts = line.split("\t")
        if len(parts) != 4:
            raise InputValidationError(
                f"Input checksum manifest line {line_number} is invalid: {input_checksums_path}"
            )
        _role, path_value, expected_digest, expected_size = parts
        path = Path(path_value).resolve()
        current = observed.get(path)
        if current is None and path.is_file():
            current = (str(path.stat().st_size), _sha256(path))
            observed[path] = current
        if current is None or current[0] != expected_size or current[1] != expected_digest:
            raise InputValidationError(f"Validated input is missing or changed: {path}")


def _load_yaml_mapping(config_path: Path) -> Mapping[str, Any]:
    data, _raw = _read_yaml_mapping(config_path, label="configuration file")
    return data


def _reject_unsupported_input_fields(data: Mapping[str, Any]) -> None:
    unsupported = sorted(field for field in data if field in UNSUPPORTED_INPUT_FIELDS)
    if unsupported:
        fields = ", ".join(f"`{field}`" for field in unsupported)
        raise InputValidationError(
            f"Unsupported input field(s): {fields}. Hi-C, ONT, trio, and ultra-long inputs "
            "are outside the supported scope."
        )


def _format_pydantic_errors(exc: ValidationError) -> str:
    messages: list[str] = ["Sample configuration failed validation:"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        current_value = repr(error.get("input"))
        messages.append(f"- field `{location}` with value {current_value}: {error['msg']}")
    return "\n".join(messages)


def _resolve_config_paths(config: SampleConfig, base_dir: Path) -> SampleConfig:
    resolved_base = base_dir.resolve()
    input_base = _resolve_input_base(config, resolved_base)
    hifi_reads = [_resolve_input_path(path, input_base, config) for path in config.hifi_reads]
    kmer_reads = (
        [_resolve_input_path(path, input_base, config) for path in config.kmer_reads]
        if config.kmer_reads is not None
        else None
    )
    reference_genome = (
        _resolve_input_path(config.reference_genome, input_base, config)
        if config.reference_genome is not None
        else None
    )
    executable_overrides = {
        name: _resolve_path(path, resolved_base)
        for name, path in config.tools.executable_overrides.items()
    }
    busco_lineage_dir = (
        _resolve_path(config.tools.busco_lineage_dir, resolved_base)
        if config.tools.busco_lineage_dir is not None
        else None
    )
    tools = config.tools.model_copy(
        update={
            "executable_overrides": executable_overrides,
            "busco_lineage_dir": busco_lineage_dir,
        }
    )
    optimization = config.optimization.model_copy(
        update={
            "llm_replay_transcript": (
                _resolve_path(config.optimization.llm_replay_transcript, resolved_base)
                if config.optimization.llm_replay_transcript is not None
                else None
            )
        }
    )

    return config.model_copy(
        update={
            "hifi_reads": hifi_reads,
            "outdir": _resolve_path(config.outdir, resolved_base),
            "kmer_reads": kmer_reads,
            "reference_genome": reference_genome,
            "optimization": optimization,
            "tools": tools,
        }
    )


def _resolve_path(path: Path, base_dir: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def _resolve_input_base(config: SampleConfig, config_base: Path) -> Path:
    if config.input_root_env is None:
        return config_base
    value = os.environ.get(config.input_root_env)
    if not value:
        raise InputValidationError(
            f"Input root environment variable `{config.input_root_env}` is not set"
        )
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise InputValidationError(
            f"Input root environment variable `{config.input_root_env}` does not name a directory: "
            f"{root}"
        )
    return root


def _resolve_input_path(path: Path, input_base: Path, config: SampleConfig) -> Path:
    if config.input_root_env is None:
        return _resolve_path(path, input_base)
    if path.is_absolute() or ".." in path.parts:
        raise InputValidationError(
            f"Inputs using `{config.input_root_env}` must be safe relative paths: {path}"
        )
    resolved = (input_base / path).resolve()
    if not resolved.is_relative_to(input_base):
        raise InputValidationError(f"Input path escapes `{config.input_root_env}` root: {path}")
    return resolved


def _iter_input_paths(config: SampleConfig) -> Iterable[Path]:
    yield from config.hifi_reads
    if config.kmer_reads is not None:
        yield from config.kmer_reads
    if config.reference_genome is not None:
        yield config.reference_genome
    if config.optimization.llm_replay_transcript is not None:
        yield config.optimization.llm_replay_transcript


def _iter_optional_file_paths(config: SampleConfig) -> Iterable[Path]:
    if config.kmer_reads is not None:
        yield from config.kmer_reads
    if config.reference_genome is not None:
        yield config.reference_genome
    if config.optimization.llm_replay_transcript is not None:
        yield config.optimization.llm_replay_transcript


def _validate_outdir_does_not_contain_inputs(outdir: Path, input_paths: list[Path]) -> None:
    for input_path in input_paths:
        if input_path == outdir or input_path.is_relative_to(outdir):
            raise InputValidationError(
                f"Field `outdir` with value {outdir} would contain input file {input_path}; "
                "choose an output directory outside all input data directories."
            )


def _validate_read_path(read_path: Path, *, field_name: str = "hifi_reads") -> None:
    _validate_existing_file(read_path, field_name=field_name)
    if not any(str(read_path).endswith(suffix) for suffix in FASTQ_SUFFIXES):
        allowed = ", ".join(FASTQ_SUFFIXES)
        raise InputValidationError(
            f"Field `{field_name}` with value {read_path} must be FASTQ/FASTQ.GZ "
            f"with one of: {allowed}"
        )


def _validate_existing_file(path: Path, *, field_name: str) -> None:
    if not path.exists():
        raise InputValidationError(f"Field `{field_name}` references a missing file: {path}")
    if not path.is_file():
        raise InputValidationError(f"Field `{field_name}` must reference a file: {path}")


def _validate_gzip_integrity(read_path: Path) -> None:
    try:
        with gzip.open(read_path, "rb") as handle:
            while handle.read(CHECKSUM_CHUNK_SIZE):
                pass
    except OSError as exc:
        raise InputValidationError(
            f"Field `hifi_reads` contains a corrupted gzip file: {read_path}: {exc}"
        ) from exc


def _validate_fastq_first_record(read_path: Path, *, field_name: str = "hifi_reads") -> None:
    try:
        opener = gzip.open if read_path.suffix == ".gz" else Path.open
        with opener(read_path, "rt") as handle:
            lines = [handle.readline().rstrip("\n\r") for _ in range(4)]
    except OSError as exc:
        raise InputValidationError(f"Unable to read FASTQ file {read_path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise InputValidationError(
            f"FASTQ file is not readable as text: {read_path}: {exc}"
        ) from exc

    if any(line == "" for line in lines):
        raise InputValidationError(
            f"Field `{field_name}` with value {read_path} must contain at least "
            "one complete FASTQ record."
        )
    if not lines[0].startswith("@"):
        raise InputValidationError(
            f"Field `{field_name}` with value {read_path} has an invalid first FASTQ header."
        )
    if not lines[2].startswith("+"):
        raise InputValidationError(
            f"Field `{field_name}` with value {read_path} has an invalid first FASTQ separator."
        )
    if len(lines[1]) != len(lines[3]):
        raise InputValidationError(
            f"Field `{field_name}` with value {read_path} has sequence/quality length mismatch "
            "in the first FASTQ record."
        )


def _write_resolved_config(config: SampleConfig, output_path: Path) -> None:
    data = config.model_dump(mode="json")
    with output_path.open("w") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)


def _collect_input_digests(config: SampleConfig) -> list[_InputDigest]:
    cached: dict[Path, tuple[str, int]] = {}
    entries: list[_InputDigest] = []
    for role, path in _iter_checksum_inputs(config):
        resolved = path.resolve()
        digest = cached.get(resolved)
        if digest is None:
            digest = (_sha256(resolved), resolved.stat().st_size)
            cached[resolved] = digest
        entries.append(
            _InputDigest(
                role=role,
                path=resolved,
                sha256=digest[0],
                bytes=digest[1],
            )
        )
    return entries


def _write_input_checksums(entries: list[_InputDigest], output_path: Path) -> None:
    rows = [("role", "path", "sha256", "bytes")]
    rows.extend((entry.role, str(entry.path), entry.sha256, str(entry.bytes)) for entry in entries)

    with output_path.open("w") as handle:
        for row in rows:
            handle.write("\t".join(row))
            handle.write("\n")


def _write_input_manifest(
    config: SampleConfig,
    entries: list[_InputDigest],
    output_path: Path,
) -> None:
    payload_entries = [
        {
            "role": entry.role,
            "path": str(entry.path),
            "sha256": entry.sha256,
            "bytes": entry.bytes,
        }
        for entry in entries
    ]
    output_path.write_text(
        json.dumps(
            {
                "schema_id": "hifi-agent",
                "sample_id": config.sample_id,
                "entries": payload_entries,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _write_validation_receipt(
    config: SampleConfig,
    resolved_config_path: Path,
    input_checksums_path: Path,
    input_manifest_path: Path,
    output_path: Path,
    *,
    sample_config_snapshot: Path,
    runtime_config_snapshot: Path | None,
) -> None:
    """Write a deterministic receipt proving validation outputs were materialized."""
    data = {
        "schema_id": "hifi-agent",
        "status": "PASS",
        "sample_id": config.sample_id,
        "read_technology": config.read_technology,
        "read_technology_source": "USER_DECLARED_NOT_INFERRED",
        "resolved_config": str(resolved_config_path),
        "resolved_config_sha256": _sha256(resolved_config_path),
        "input_checksums": str(input_checksums_path),
        "input_checksums_sha256": _sha256(input_checksums_path),
        "input_manifest": str(input_manifest_path),
        "input_manifest_sha256": _sha256(input_manifest_path),
        "sample_config_snapshot": str(sample_config_snapshot),
        "sample_config_snapshot_sha256": _sha256(sample_config_snapshot),
    }
    if runtime_config_snapshot is not None:
        data["runtime_config_snapshot"] = str(runtime_config_snapshot)
        data["runtime_config_snapshot_sha256"] = _sha256(runtime_config_snapshot)
    with output_path.open("w") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _iter_checksum_inputs(config: SampleConfig) -> Iterable[tuple[str, Path]]:
    for path in config.hifi_reads:
        yield "hifi_reads", path
    if config.kmer_reads is not None:
        for path in config.kmer_reads:
            yield "kmer_reads", path
    if config.reference_genome is not None:
        yield "reference_genome", config.reference_genome
    if config.optimization.llm_replay_transcript is not None:
        yield "llm_replay_transcript", config.optimization.llm_replay_transcript


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHECKSUM_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)
