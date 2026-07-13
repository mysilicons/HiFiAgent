"""Parser for `seqkit stats -a -T` tabular output."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SeqkitStats:
    """Merged numeric fields parsed from one or more seqkit stats rows."""

    file_count: int
    read_count: int
    total_bases: int
    min_length: int | None
    mean_length: float | None
    max_length: int | None
    read_n50: int | None
    mean_qscore: float | None
    gc_percent: float | None
    warnings: tuple[str, ...]


def parse_seqkit_stats(path: Path) -> SeqkitStats:
    """Parse seqkit TSV output and merge rows by base-weighted fields where possible."""
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    warnings: list[str] = []
    if not rows:
        return SeqkitStats(0, 0, 0, None, None, None, None, None, None, ("SEQKIT_EMPTY",))

    read_count = sum(_as_int(row, "num_seqs", warnings) or 0 for row in rows)
    total_bases = sum(_as_int(row, "sum_len", warnings) or 0 for row in rows)
    file_count = len(rows)
    min_values = [_as_int(row, "min_len", warnings) for row in rows]
    max_values = [_as_int(row, "max_len", warnings) for row in rows]
    n50_values = [_as_int(row, "N50", warnings) for row in rows]

    gc_percent = _weighted_percent(rows, "GC(%)", "sum_len", warnings)
    mean_qscore = _weighted_percent(rows, "AvgQual", "sum_len", warnings)
    mean_length = (total_bases / read_count) if read_count else None

    if file_count > 1:
        warnings.append("SEQKIT_MULTI_FILE_N50_IS_MIN_ROW_N50_APPROXIMATION")

    return SeqkitStats(
        file_count=file_count,
        read_count=read_count,
        total_bases=total_bases,
        min_length=_min_present(min_values),
        mean_length=mean_length,
        max_length=_max_present(max_values),
        read_n50=_min_present(n50_values),
        mean_qscore=mean_qscore,
        gc_percent=gc_percent,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _as_int(row: dict[str, str], key: str, warnings: list[str]) -> int | None:
    value = row.get(key)
    if value is None or value in ("", "-"):
        warnings.append(f"SEQKIT_MISSING_{key}")
        return None
    try:
        return int(float(value.replace(",", "")))
    except ValueError:
        warnings.append(f"SEQKIT_INVALID_{key}")
        return None


def _as_float(row: dict[str, str], key: str, warnings: list[str]) -> float | None:
    value = row.get(key)
    if value is None or value in ("", "-"):
        warnings.append(f"SEQKIT_MISSING_{key}")
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        warnings.append(f"SEQKIT_INVALID_{key}")
        return None


def _weighted_percent(
    rows: list[dict[str, str]],
    value_key: str,
    weight_key: str,
    warnings: list[str],
) -> float | None:
    weighted_sum = 0.0
    total_weight = 0
    for row in rows:
        value = _as_float(row, value_key, warnings)
        weight = _as_int(row, weight_key, warnings)
        if value is None or weight is None:
            continue
        weighted_sum += value * weight
        total_weight += weight
    if total_weight == 0:
        return None
    return weighted_sum / total_weight


def _min_present(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _max_present(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None
