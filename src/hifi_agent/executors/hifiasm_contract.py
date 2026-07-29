"""Bidirectional command contract for approved hifiasm candidate parameters."""

from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from hifi_agent.agent.models import AssemblyConfig, AssemblyParameters
from hifi_agent.exceptions import ToolExecutionError


@dataclass(frozen=True)
class HifiasmCommandContract:
    """A successful comparison of approved and realized hifiasm parameters."""

    status: Literal["PASS"]
    rendered_parameter_argv: tuple[str, ...]
    realized_command_argv: tuple[str, ...]
    realized_parameters: AssemblyParameters
    input_reads: tuple[str, ...]
    threads: int
    output_prefix: str


def render_hifiasm_parameter_argv(parameters: AssemblyParameters) -> tuple[str, ...]:
    """Render the complete whitelisted parameter vector for a candidate run."""
    argv = ["-l", str(parameters.purge_level), "-s", str(parameters.purge_similarity)]
    if parameters.hom_cov is not None:
        argv.extend(["--hom-cov", str(parameters.hom_cov)])
    if parameters.disable_post_join:
        argv.append("-u0")
    rendered = tuple(argv)
    realized = parse_hifiasm_parameter_argv(rendered)
    if realized != parameters:
        raise ToolExecutionError(
            "Rendered hifiasm parameters do not round-trip to the approved configuration"
        )
    return rendered


def parse_hifiasm_parameter_argv(argv: Sequence[str]) -> AssemblyParameters:
    """Parse a parameter-only argv and reject unknown, duplicate, or malformed flags."""
    values: dict[str, int | float | bool | None] = {
        "purge_level": 3,
        "purge_similarity": 0.55,
        "hom_cov": None,
        "disable_post_join": False,
    }
    seen: set[str] = set()
    index = 0
    while index < len(argv):
        flag = argv[index]
        if flag in seen:
            raise ToolExecutionError(f"Duplicate hifiasm parameter flag: {flag}")
        seen.add(flag)
        if flag == "-u0":
            values["disable_post_join"] = True
            index += 1
            continue
        field_and_type = {
            "-l": ("purge_level", int),
            "-s": ("purge_similarity", float),
            "--hom-cov": ("hom_cov", int),
        }.get(flag)
        if field_and_type is None:
            raise ToolExecutionError(f"Unapproved hifiasm parameter flag: {flag}")
        if index + 1 >= len(argv):
            raise ToolExecutionError(f"Missing value for hifiasm parameter flag: {flag}")
        raw_value = argv[index + 1]
        field, converter = field_and_type
        try:
            values[field] = converter(raw_value)
        except ValueError as exc:
            raise ToolExecutionError(
                f"Invalid value `{raw_value}` for hifiasm parameter flag {flag}"
            ) from exc
        index += 2
    try:
        return AssemblyParameters.model_validate(values)
    except ValidationError as exc:
        raise ToolExecutionError(f"Realized hifiasm parameters violate the schema: {exc}") from exc


def parse_hifiasm_command(
    command_text: str,
) -> tuple[AssemblyParameters, tuple[str, ...], tuple[str, ...]]:
    """Parse one recorded hifiasm command into parameters, full argv, and input reads."""
    try:
        argv = tuple(shlex.split(command_text))
    except ValueError as exc:
        raise ToolExecutionError(
            f"Recorded hifiasm command is not valid shell argv: {exc}"
        ) from exc
    if not argv or Path(argv[0]).name != "hifiasm":
        raise ToolExecutionError("Recorded assembly command does not invoke hifiasm")

    parameter_argv: list[str] = []
    input_reads: list[str] = []
    seen_runtime_flags: set[str] = set()
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in {"-o", "-t"}:
            if token in seen_runtime_flags:
                raise ToolExecutionError(f"Duplicate hifiasm runtime flag: {token}")
            seen_runtime_flags.add(token)
            if index + 1 >= len(argv):
                raise ToolExecutionError(f"Missing value for hifiasm runtime flag: {token}")
            index += 2
            continue
        if token in {"-l", "-s", "--hom-cov"}:
            if index + 1 >= len(argv):
                raise ToolExecutionError(f"Missing value for hifiasm parameter flag: {token}")
            parameter_argv.extend([token, argv[index + 1]])
            index += 2
            continue
        if token == "-u0":
            parameter_argv.append(token)
            index += 1
            continue
        if token.startswith("-"):
            raise ToolExecutionError(f"Unapproved hifiasm command flag: {token}")
        input_reads.append(token)
        index += 1

    if not input_reads:
        raise ToolExecutionError("Recorded hifiasm command contains no input reads")
    return parse_hifiasm_parameter_argv(parameter_argv), argv, tuple(input_reads)


def validate_hifiasm_command_contract(
    approved: AssemblyConfig,
    command_path: Path,
) -> HifiasmCommandContract:
    """Validate a recorded command against the complete approved candidate parameters."""
    if not command_path.is_file():
        raise ToolExecutionError(f"Recorded hifiasm command is missing: {command_path}")
    rendered = render_hifiasm_parameter_argv(approved.parameters)
    try:
        realized, command_argv, input_reads = parse_hifiasm_command(command_path.read_text())
    except ToolExecutionError as exc:
        raise ToolExecutionError(f"PARAMETER_CONTRACT_VIOLATION: {exc}") from exc
    threads = _runtime_integer(command_argv, "-t")
    output_prefix = _runtime_string(command_argv, "-o")
    expected_reads = tuple(path.name for path in approved.input_reads)
    realized_reads = tuple(Path(path).name for path in input_reads)
    differences: dict[str, object] = {**_parameter_differences(approved.parameters, realized)}
    if threads != approved.threads:
        differences["threads"] = {"approved": approved.threads, "realized": threads}
    if not output_prefix.endswith(f".{approved.run_id}"):
        differences["output_prefix"] = {
            "approved_suffix": f".{approved.run_id}",
            "realized": output_prefix,
        }
    if realized_reads != expected_reads:
        differences["input_reads"] = {
            "approved": list(expected_reads),
            "realized": list(realized_reads),
        }
    if differences:
        raise ToolExecutionError(
            "PARAMETER_CONTRACT_VIOLATION: approved and realized hifiasm command differ: "
            f"{differences}"
        )
    return HifiasmCommandContract(
        status="PASS",
        rendered_parameter_argv=rendered,
        realized_command_argv=command_argv,
        realized_parameters=realized,
        input_reads=input_reads,
        threads=threads,
        output_prefix=output_prefix,
    )


def write_hifiasm_contract_artifacts(
    approved: AssemblyConfig,
    metadata_dir: Path,
    *,
    command_path: Path | None = None,
) -> HifiasmCommandContract | None:
    """Write requested/approved/rendered artifacts and optionally finalize against a command."""
    metadata_dir.mkdir(parents=True, exist_ok=True)
    rendered = render_hifiasm_parameter_argv(approved.parameters)
    _write_json(metadata_dir / "requested_config.json", approved.model_dump(mode="json"))
    _write_json(metadata_dir / "approved_config.json", approved.model_dump(mode="json"))
    _write_json(
        metadata_dir / "rendered_argv.json",
        {
            "schema_version": "1.0",
            "parameter_argv": list(rendered),
            "threads": approved.threads,
            "output_prefix_suffix": f".{approved.run_id}",
            "input_read_names": [path.name for path in approved.input_reads],
        },
    )
    if command_path is None:
        return None

    try:
        result = validate_hifiasm_command_contract(approved, command_path)
    except ToolExecutionError as exc:
        _write_json(
            metadata_dir / "parameter_contract_check.json",
            {
                "schema_version": "1.0",
                "status": "FAIL",
                "reason_code": "PARAMETER_CONTRACT_VIOLATION",
                "error": str(exc),
                "approved_parameters": approved.parameters.model_dump(mode="json"),
            },
        )
        raise
    _write_json(
        metadata_dir / "realized_parameters.json",
        {
            "schema_version": "1.0",
            "parameters": result.realized_parameters.model_dump(mode="json"),
            "command_argv": list(result.realized_command_argv),
            "input_reads": list(result.input_reads),
            "threads": result.threads,
            "output_prefix": result.output_prefix,
        },
    )
    _write_json(
        metadata_dir / "parameter_contract_check.json",
        {
            "schema_version": "1.0",
            "status": "PASS",
            "reason_code": "APPROVED_PARAMETERS_MATCH_REALIZED_COMMAND",
            "approved_parameters": approved.parameters.model_dump(mode="json"),
            "realized_parameters": result.realized_parameters.model_dump(mode="json"),
            "differences": [],
        },
    )
    return result


def _parameter_differences(
    approved: AssemblyParameters,
    realized: AssemblyParameters,
) -> dict[str, dict[str, int | float | bool | None]]:
    approved_values = approved.model_dump(mode="json")
    realized_values = realized.model_dump(mode="json")
    return {
        field: {"approved": approved_values[field], "realized": realized_values[field]}
        for field in approved_values
        if approved_values[field] != realized_values[field]
    }


def _runtime_string(argv: tuple[str, ...], flag: str) -> str:
    try:
        index = argv.index(flag)
        return argv[index + 1]
    except (ValueError, IndexError) as exc:
        raise ToolExecutionError(
            f"Recorded hifiasm command is missing runtime flag {flag}"
        ) from exc


def _runtime_integer(argv: tuple[str, ...], flag: str) -> int:
    value = _runtime_string(argv, flag)
    try:
        return int(value)
    except ValueError as exc:
        raise ToolExecutionError(
            f"Recorded hifiasm runtime flag {flag} has invalid integer value `{value}`"
        ) from exc


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
