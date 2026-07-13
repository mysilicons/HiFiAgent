"""Parsers and summaries for k-mer histogram outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KmerHistogramSummary:
    """Deterministic summary of a k-mer multiplicity histogram."""

    distinct_kmers: int
    total_kmer_observations: int
    peak_depth: int | None
    peak_count: int | None
    warnings: tuple[str, ...]


def parse_kmer_histogram(path: Path) -> KmerHistogramSummary:
    """Parse two-column `depth count` k-mer histogram text."""
    depth_counts: list[tuple[int, int]] = []
    distinct_kmers = 0
    total_observations = 0
    peak_depth: int | None = None
    peak_count: int | None = None
    warnings: list[str] = []

    with path.open() as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.lower().startswith("depth"):
                continue
            parts = line.split()
            if len(parts) < 2:
                warnings.append(f"KMER_HISTOGRAM_BAD_LINE_{line_number}")
                continue
            try:
                depth = int(parts[0])
                count = int(parts[1])
            except ValueError:
                warnings.append(f"KMER_HISTOGRAM_BAD_LINE_{line_number}")
                continue
            if depth <= 0 or count < 0:
                warnings.append(f"KMER_HISTOGRAM_INVALID_VALUE_{line_number}")
                continue
            depth_counts.append((depth, count))
            distinct_kmers += count
            total_observations += depth * count
            if peak_count is None or count > peak_count:
                peak_depth = depth
                peak_count = count

    if distinct_kmers == 0:
        warnings.append("KMER_HISTOGRAM_EMPTY")
    warnings.extend(_peak_shape_warnings(depth_counts))

    return KmerHistogramSummary(
        distinct_kmers=distinct_kmers,
        total_kmer_observations=total_observations,
        peak_depth=peak_depth,
        peak_count=peak_count,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _peak_shape_warnings(depth_counts: list[tuple[int, int]]) -> list[str]:
    if not depth_counts:
        return []

    warnings: list[str] = []
    local_peaks = _local_peaks(dict(depth_counts))
    non_error_peaks = [(depth, count) for depth, count in local_peaks if depth > 1]
    if not non_error_peaks:
        warnings.append("KMER_NO_CLEAR_PEAK")
        return warnings

    top_non_error_count = max(count for _depth, count in non_error_peaks)
    comparable_peaks = [
        (depth, count)
        for depth, count in non_error_peaks
        if top_non_error_count > 0 and count >= top_non_error_count * 0.75
    ]
    if len(comparable_peaks) > 1:
        warnings.append("KMER_MULTIPLE_COMPARABLE_PEAKS")
    return warnings


def _local_peaks(depth_to_count: dict[int, int]) -> list[tuple[int, int]]:
    peaks: list[tuple[int, int]] = []
    for depth in sorted(depth_to_count):
        count = depth_to_count[depth]
        left = depth_to_count.get(depth - 1, -1)
        right = depth_to_count.get(depth + 1, -1)
        if count > 0 and count >= left and count >= right and (count > left or count > right):
            peaks.append((depth, count))
    return peaks
