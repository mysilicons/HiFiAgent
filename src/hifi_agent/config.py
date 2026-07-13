"""Configuration loading, input validation, and phase 2 metadata outputs."""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from hifi_agent.exceptions import InputValidationError
from hifi_agent.schemas.sample import SampleConfig

UNSUPPORTED_V1_FIELDS = frozenset(
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


def validate_config_file(
    config_path: Path,
    *,
    write_outputs: bool = True,
) -> ConfigValidationResult:
    """Load, validate, and optionally materialize metadata for a sample config."""
    raw_config = _load_yaml_mapping(config_path)
    _reject_unsupported_v1_fields(raw_config)

    try:
        config = SampleConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise InputValidationError(_format_pydantic_errors(exc)) from exc

    resolved_config = _resolve_config_paths(config, config_path.parent)
    validate_sample_inputs(resolved_config)

    metadata_dir = resolved_config.outdir / "00_metadata"
    resolved_config_path = metadata_dir / "resolved_config.yaml"
    input_checksums_path = metadata_dir / "input_checksums.tsv"

    if write_outputs:
        metadata_dir.mkdir(parents=True, exist_ok=True)
        _write_resolved_config(resolved_config, resolved_config_path)
        _write_input_checksums(resolved_config, input_checksums_path)

    return ConfigValidationResult(
        config=resolved_config,
        metadata_dir=metadata_dir,
        resolved_config=resolved_config_path,
        input_checksums=input_checksums_path,
    )


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


def _load_yaml_mapping(config_path: Path) -> Mapping[str, Any]:
    if not config_path.is_file():
        raise InputValidationError(f"Config file does not exist: {config_path}")

    try:
        with config_path.open() as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise InputValidationError(f"Config file is not valid YAML: {config_path}: {exc}") from exc

    if not isinstance(data, Mapping):
        raise InputValidationError(f"Config file must contain a YAML mapping: {config_path}")

    return data


def _reject_unsupported_v1_fields(data: Mapping[str, Any]) -> None:
    unsupported = sorted(field for field in data if field in UNSUPPORTED_V1_FIELDS)
    if unsupported:
        fields = ", ".join(f"`{field}`" for field in unsupported)
        raise InputValidationError(
            f"Unsupported V1 field(s): {fields}. Hi-C, ONT, trio, and ultra-long inputs "
            "are outside the V1 scope."
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
    hifi_reads = [_resolve_path(path, resolved_base) for path in config.hifi_reads]
    kmer_reads = (
        [_resolve_path(path, resolved_base) for path in config.kmer_reads]
        if config.kmer_reads is not None
        else None
    )
    reference_genome = (
        _resolve_path(config.reference_genome, resolved_base)
        if config.reference_genome is not None
        else None
    )

    return config.model_copy(
        update={
            "hifi_reads": hifi_reads,
            "outdir": _resolve_path(config.outdir, resolved_base),
            "kmer_reads": kmer_reads,
            "reference_genome": reference_genome,
        }
    )


def _resolve_path(path: Path, base_dir: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def _iter_input_paths(config: SampleConfig) -> Iterable[Path]:
    yield from config.hifi_reads
    if config.kmer_reads is not None:
        yield from config.kmer_reads
    if config.reference_genome is not None:
        yield config.reference_genome


def _iter_optional_file_paths(config: SampleConfig) -> Iterable[Path]:
    if config.kmer_reads is not None:
        yield from config.kmer_reads
    if config.reference_genome is not None:
        yield config.reference_genome


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


def _write_input_checksums(config: SampleConfig, output_path: Path) -> None:
    rows = [("role", "path", "sha256", "bytes")]
    for role, path in _iter_checksum_inputs(config):
        rows.append((role, str(path), _sha256(path), str(path.stat().st_size)))

    with output_path.open("w") as handle:
        for row in rows:
            handle.write("\t".join(row))
            handle.write("\n")


def _iter_checksum_inputs(config: SampleConfig) -> Iterable[tuple[str, Path]]:
    for path in config.hifi_reads:
        yield "hifi_reads", path
    if config.kmer_reads is not None:
        for path in config.kmer_reads:
            yield "kmer_reads", path
    if config.reference_genome is not None:
        yield "reference_genome", config.reference_genome


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHECKSUM_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
