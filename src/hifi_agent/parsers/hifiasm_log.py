"""Parser for hifiasm stderr and runtime reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HOM_COV_PATTERNS = (
    re.compile(
        r"homozygous\s+read\s+coverage\s+threshold:\s*(?P<value>-?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    re.compile(r"hom(?:ozygous)?[-_\s]*cov(?:erage)?.*?(?P<value>\d+(?:\.\d+)?)", re.IGNORECASE),
)
HIFIASM_MAIN_VERSION_PATTERN = re.compile(r"\[M::main\]\s+Version:\s*(?P<value>\S+)")
HIFIASM_MAIN_RUNTIME_PATTERN = re.compile(
    r"\[M::main\]\s+Real time:\s*(?P<real>[0-9.]+)\s+sec;\s+"
    r"CPU:\s*(?P<cpu>[0-9.]+)\s+sec;\s+Peak RSS:\s*(?P<rss>[0-9.]+)\s+GB"
)


@dataclass(frozen=True)
class HifiasmLogSummary:
    """Structured values parsed from hifiasm stderr."""

    homozygous_coverage_threshold: int | float | None
    version: str | None
    real_time_seconds: float | None
    cpu_seconds: float | None
    peak_rss_gb: float | None
    warnings: tuple[str, ...]


def parse_hifiasm_log(path: Path) -> HifiasmLogSummary:
    """Parse hifiasm stderr for coverage threshold, version, and resource lines."""
    text = path.read_text(errors="replace") if path.is_file() else ""
    warnings: list[str] = []

    hom_cov = _parse_hom_cov(text)
    if hom_cov is None:
        warnings.append("HIFIASM_HOM_COV_THRESHOLD_NOT_FOUND")

    version_match = HIFIASM_MAIN_VERSION_PATTERN.search(text)
    runtime_match = HIFIASM_MAIN_RUNTIME_PATTERN.search(text)

    return HifiasmLogSummary(
        homozygous_coverage_threshold=hom_cov,
        version=version_match.group("value") if version_match else None,
        real_time_seconds=_optional_float(runtime_match, "real") if runtime_match else None,
        cpu_seconds=_optional_float(runtime_match, "cpu") if runtime_match else None,
        peak_rss_gb=_optional_float(runtime_match, "rss") if runtime_match else None,
        warnings=tuple(warnings),
    )


def parse_time_report(path: Path) -> dict[str, str | int | float | None]:
    """Parse `/usr/bin/time -v` output used around hifiasm."""
    if not path.is_file():
        return {}

    values: dict[str, str | int | float | None] = {}
    with path.open(errors="replace") as handle:
        for raw_line in handle:
            if ":" not in raw_line:
                continue
            key, value = raw_line.strip().split(":", 1)
            normalized = key.strip().lower().replace(" ", "_").replace("(", "").replace(")", "")
            values[normalized] = _coerce_time_value(value.strip())
    return values


def _parse_hom_cov(text: str) -> int | float | None:
    for pattern in HOM_COV_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        value = float(match.group("value"))
        return int(value) if value.is_integer() else value
    return None


def _optional_float(match: re.Match[str], group: str) -> float:
    return float(match.group(group))


def _coerce_time_value(value: str) -> str | int | float | None:
    if value == "":
        return None
    try:
        numeric = float(value)
    except ValueError:
        return value
    return int(numeric) if numeric.is_integer() else numeric
