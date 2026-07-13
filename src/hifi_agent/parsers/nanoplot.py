"""Parser for NanoPlot NanoStats-style key/value output."""

from __future__ import annotations

from pathlib import Path


def parse_nanostats(path: Path) -> dict[str, str | float | int | None]:
    """Parse a simple NanoStats key/value table without inspecting HTML output."""
    metrics: dict[str, str | float | int | None] = {}
    with path.open() as handle:
        for raw_line in handle:
            line = raw_line.strip()
            lowered = line.lower()
            if not line or lowered.startswith("metric\t") or lowered.startswith("metrics\t"):
                continue
            if "\t" in line:
                key, value = line.split("\t", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                continue
            metrics[_normalize_key(key)] = _coerce_value(value.strip())
    return metrics


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_").replace("-", "_")


def _coerce_value(value: str) -> str | float | int | None:
    if value in {"", "NA", "N/A", "null", "None"}:
        return None
    try:
        numeric = float(value)
    except ValueError:
        return value
    if numeric.is_integer():
        return int(numeric)
    return numeric
