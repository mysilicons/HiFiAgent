"""Parser for minimal GenomeScope summary outputs."""

from __future__ import annotations

from pathlib import Path


def parse_genomescope_report(path: Path) -> dict[str, str | float | int | None]:
    """Parse GenomeScope `summary.txt` ranges for derived report fields."""
    values: dict[str, str | float | int | None] = {}
    haploid_length = _parse_range_midpoint(path, "Genome Haploid Length")
    repeat_length = _parse_range_midpoint(path, "Genome Repeat Length")
    model_fit = _parse_range_midpoint(path, "Model Fit")

    if haploid_length is not None:
        values["genome_size"] = round(haploid_length)
    if repeat_length is not None and haploid_length is not None and haploid_length != 0:
        values["repeat_fraction"] = repeat_length / haploid_length
    if model_fit is not None:
        values["model_fit"] = model_fit
    return values


def parse_genomescope_summary(path: Path) -> dict[str, str | float | int | None]:
    """Parse key/value GenomeScope summary text produced by the workflow."""
    values: dict[str, str | float | int | None] = {}
    with path.open() as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.lower().startswith("key\t"):
                continue
            if "\t" not in line:
                continue
            key, value = line.split("\t", 1)
            values[key] = _coerce_value(value)
    return values


def parse_genomescope_stdout(text: str) -> dict[str, str | float | int | None]:
    """Parse the concise GenomeScope convergence line from stdout/stderr."""
    values: dict[str, str | float | int | None] = {}
    for token in text.replace("\n", " ").split():
        if ":" not in token:
            continue
        key, value = token.split(":", 1)
        normalized = {
            "het": "heterozygosity",
            "len": "genome_size",
            "kcov": "kmer_coverage",
            "err": "error_rate",
            "fit": "model_fit",
        }.get(key)
        if normalized is not None:
            values[normalized] = _coerce_value(value)
    return values


def _parse_range_midpoint(path: Path, label: str) -> float | None:
    if not path.is_file():
        return None
    with path.open() as handle:
        for line in handle:
            if not line.startswith(label):
                continue
            values = [_parse_report_number(part) for part in line[len(label) :].split()]
            numeric_values = [value for value in values if value is not None]
            if not numeric_values:
                return None
            return sum(numeric_values[:2]) / min(len(numeric_values), 2)
    return None


def _parse_report_number(value: str) -> float | None:
    cleaned = value.strip().replace(",", "").removesuffix("%")
    if cleaned in {"", "bp"}:
        return None
    try:
        numeric = float(cleaned)
    except ValueError:
        return None
    if value.strip().endswith("%"):
        return numeric / 100
    return numeric


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
