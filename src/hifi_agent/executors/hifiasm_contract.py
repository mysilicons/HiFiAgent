"""Bidirectional current argv contract for all hifiasm attempts."""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hifi_agent.exceptions import ToolExecutionError
from hifi_agent.schemas.assembly import AssemblyConfig, AssemblyParameters


class RenderedArgv(BaseModel):
    """Tokenized, shell-free command rendered from an approved full config."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    argv: tuple[str, ...] = Field(min_length=2)


class RealizedParameters(BaseModel):
    """Parameters parsed back from the command actually recorded by the tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    parameters: AssemblyParameters
    threads: int = Field(ge=1)
    output_prefix: str = Field(min_length=1)
    input_reads: tuple[str, ...] = Field(min_length=1)
    realized_argv: tuple[str, ...] = Field(min_length=2)


class ParameterFieldCheck(BaseModel):
    """Approved/rendered/realized equality result for one parameter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    approved: bool | int | float | None
    rendered: bool | int | float | None
    realized: bool | int | float | None
    matches: bool


class ParameterContractCheck(BaseModel):
    """Field-level proof that execution matched the approved configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    status: Literal["PASS", "FAIL"]
    field_checks: tuple[ParameterFieldCheck, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1)


def render_hifiasm_parameter_argv(parameters: AssemblyParameters) -> tuple[str, ...]:
    """Render only whitelisted flags, omitting null and false values."""
    argv = ["-l", str(parameters.purge_level), "-s", str(parameters.purge_similarity)]
    if parameters.hom_cov is not None:
        argv.extend(["--hom-cov", str(parameters.hom_cov)])
    if parameters.disable_post_join:
        argv.append("-u0")
    rendered = tuple(argv)
    if parse_hifiasm_parameter_argv(rendered) != parameters:
        raise ToolExecutionError("Rendered hifiasm parameters do not round-trip")
    return rendered


def render_hifiasm_argv(
    config: AssemblyConfig,
    *,
    executable: str,
    output_prefix: str,
) -> RenderedArgv:
    """Render the exact token vector; callers must execute without a shell."""
    if not executable or "\x00" in executable or not output_prefix:
        raise ToolExecutionError("Invalid hifiasm executable or output prefix")
    argv = (
        executable,
        "-o",
        output_prefix,
        "-t",
        str(config.threads),
        *render_hifiasm_parameter_argv(config.parameters),
        *(str(path) for path in config.input_reads),
    )
    realized = parse_hifiasm_argv(argv)
    if realized.parameters != config.parameters or realized.threads != config.threads:
        raise ToolExecutionError("Rendered hifiasm argv does not match approved config")
    return RenderedArgv(argv=argv)


def parse_hifiasm_parameter_argv(argv: Sequence[str]) -> AssemblyParameters:
    """Reject unknown, duplicate, malformed, shell, path, and environment tokens."""
    values: dict[str, bool | int | float | None] = {
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
        if flag == "-u0":
            seen.add(flag)
            values["disable_post_join"] = True
            index += 1
            continue
        specification = {
            "-l": ("purge_level", int),
            "-s": ("purge_similarity", float),
            "--hom-cov": ("hom_cov", int),
        }.get(flag)
        if specification is None:
            raise ToolExecutionError(f"Unapproved hifiasm parameter token: {flag}")
        if index + 1 >= len(argv):
            raise ToolExecutionError(f"Missing value for hifiasm parameter flag: {flag}")
        raw = argv[index + 1]
        if _unsafe_parameter_token(raw):
            raise ToolExecutionError(f"Unsafe hifiasm parameter token: {raw}")
        field, converter = specification
        try:
            values[field] = converter(raw)
        except ValueError as exc:
            raise ToolExecutionError(f"Invalid value `{raw}` for {flag}") from exc
        seen.add(flag)
        index += 2
    try:
        return AssemblyParameters.model_validate(values)
    except ValidationError as exc:
        raise ToolExecutionError(
            f"Realized hifiasm parameters violate current schema: {exc}"
        ) from exc


def parse_hifiasm_argv(argv: Sequence[str]) -> RealizedParameters:
    """Parse one full argv without evaluating shell syntax."""
    tokens = tuple(argv)
    if not tokens or Path(tokens[0]).name != "hifiasm":
        raise ToolExecutionError("Recorded command does not invoke hifiasm")
    parameter_tokens: list[str] = []
    reads: list[str] = []
    output_prefix: str | None = None
    threads: int | None = None
    seen_runtime: set[str] = set()
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-o", "-t"}:
            if token in seen_runtime or index + 1 >= len(tokens):
                raise ToolExecutionError(f"Duplicate or incomplete runtime flag: {token}")
            value = tokens[index + 1]
            if token == "-o":
                output_prefix = value
            else:
                try:
                    threads = int(value)
                except ValueError as exc:
                    raise ToolExecutionError("Invalid hifiasm thread count") from exc
            seen_runtime.add(token)
            index += 2
            continue
        if token in {"-l", "-s", "--hom-cov"}:
            if index + 1 >= len(tokens):
                raise ToolExecutionError(f"Missing value for hifiasm parameter flag: {token}")
            parameter_tokens.extend((token, tokens[index + 1]))
            index += 2
            continue
        if token == "-u0":
            parameter_tokens.append(token)
            index += 1
            continue
        if token.startswith("-"):
            raise ToolExecutionError(f"Unapproved hifiasm command flag: {token}")
        reads.append(token)
        index += 1
    if output_prefix is None or threads is None or threads < 1 or not reads:
        raise ToolExecutionError("Recorded command lacks output, threads, or input reads")
    return RealizedParameters(
        parameters=parse_hifiasm_parameter_argv(parameter_tokens),
        threads=threads,
        output_prefix=output_prefix,
        input_reads=tuple(reads),
        realized_argv=tokens,
    )


def check_parameter_contract(
    approved: AssemblyConfig,
    rendered: RenderedArgv,
    realized: RealizedParameters,
) -> ParameterContractCheck:
    """Compare all approved, rendered, and realized parameter fields."""
    rendered_values = parse_hifiasm_argv(rendered.argv).parameters
    checks = tuple(
        ParameterFieldCheck(
            field=field,
            approved=getattr(approved.parameters, field),
            rendered=getattr(rendered_values, field),
            realized=getattr(realized.parameters, field),
            matches=(
                getattr(approved.parameters, field)
                == getattr(rendered_values, field)
                == getattr(realized.parameters, field)
            ),
        )
        for field in AssemblyParameters.model_fields
    )
    runtime_matches = approved.threads == realized.threads
    passed = all(item.matches for item in checks) and runtime_matches
    return ParameterContractCheck(
        status="PASS" if passed else "FAIL",
        field_checks=checks,
        reason_codes=(
            ("APPROVED_RENDERED_REALIZED_MATCH",) if passed else ("PARAMETER_CONTRACT_MISMATCH",)
        ),
    )


def display_command(argv: Sequence[str]) -> str:
    """Render a display-only command; this string must never be executed."""
    return shlex.join(argv)


def _unsafe_parameter_token(token: str) -> bool:
    return any(marker in token for marker in ("/", "\\", "$", "`", ";", "|", "&", "\n"))
