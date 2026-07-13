"""Parser for QUAST transposed TSV reports."""

import csv
from pathlib import Path


def parse_quast_report(path: Path) -> dict[str, int | float | None]:
    """Parse stable QUAST metrics while tolerating reference-free omissions."""
    metrics: dict[str, int | float | None] = {
        "assembly_size": None,
        "contig_count": None,
        "contig_n50": None,
        "contig_l50": None,
        "longest_contig": None,
        "misassemblies": None,
        "local_misassemblies": None,
        "genome_fraction": None,
        "duplication_ratio": None,
    }
    if not path.is_file():
        return metrics

    with path.open(newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    values = {row[0].strip(): row[1].strip() for row in rows if len(row) >= 2}
    integer_keys = {
        "assembly_size": "Total length",
        "contig_count": "# contigs",
        "contig_n50": "N50",
        "contig_l50": "L50",
        "longest_contig": "Largest contig",
        "misassemblies": "# misassemblies",
        "local_misassemblies": "# local misassemblies",
    }
    float_keys = {
        "genome_fraction": "Genome fraction (%)",
        "duplication_ratio": "Duplication ratio",
    }
    for target, source in integer_keys.items():
        metrics[target] = _optional_int(values.get(source))
    for target, source in float_keys.items():
        metrics[target] = _optional_float(values.get(source))
    return metrics


def _optional_int(value: str | None) -> int | None:
    if value is None or value in {"", "-"}:
        return None
    try:
        return int(float(value.replace(",", "")))
    except ValueError:
        return None


def _optional_float(value: str | None) -> float | None:
    if value is None or value in {"", "-"}:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None
