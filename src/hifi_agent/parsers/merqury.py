"""Parser for Merqury QV and completeness tables."""

from pathlib import Path


def parse_merqury_metrics(qv_path: Path, completeness_path: Path) -> dict[str, float | None]:
    """Parse assembly-wide Merqury QV and k-mer completeness percentages."""
    return {
        "qv": _last_float(qv_path, column=3),
        "completeness": _last_float(completeness_path, column=4),
    }


def _last_float(path: Path, *, column: int) -> float | None:
    if not path.is_file():
        return None
    parsed: float | None = None
    with path.open() as handle:
        for raw_line in handle:
            parts = raw_line.strip().split()
            if len(parts) <= column:
                continue
            try:
                parsed = float(parts[column])
            except ValueError:
                continue
    return parsed
