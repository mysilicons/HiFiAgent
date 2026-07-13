"""Parsers for read-mapping and window coverage summaries."""

import math
import re
import statistics
from pathlib import Path

MAPPED_PERCENT = re.compile(r"^\d+\s+\+\s+\d+\s+mapped\s+\((?P<percent>[0-9.]+)%")


def parse_mapped_fraction(path: Path) -> float | None:
    """Parse the overall mapped fraction from `samtools flagstat` output."""
    if not path.is_file():
        return None
    for line in path.read_text(errors="replace").splitlines():
        match = MAPPED_PERCENT.search(line.strip())
        if match is not None:
            return float(match.group("percent")) / 100
    return None


def parse_window_coverage(path: Path) -> dict[str, float | None]:
    """Compute mean, median, CV, and relative low/high window fractions."""
    coverage: list[float] = []
    total_depth = 0.0
    total_length = 0
    if path.is_file():
        with path.open() as handle:
            for raw_line in handle:
                parts = raw_line.strip().split("\t")
                if len(parts) < 4:
                    continue
                try:
                    length = int(parts[2]) - int(parts[1])
                    depth_sum = float(parts[-1])
                except ValueError:
                    continue
                if length > 0:
                    coverage.append(depth_sum / length)
                    total_depth += depth_sum
                    total_length += length

    if not coverage:
        return {
            "mean": None,
            "median": None,
            "cv": None,
            "low_window_fraction": None,
            "high_window_fraction": None,
        }

    mean = total_depth / total_length
    median = statistics.median(coverage)
    cv = statistics.pstdev(coverage) / mean if mean > 0 else None
    coverage_baseline = median if median > 0 else mean
    low_threshold = coverage_baseline * 0.25
    high_threshold = coverage_baseline * 2.0
    return {
        "mean": mean,
        "median": median,
        "cv": cv,
        "low_window_fraction": math.fsum(value < low_threshold for value in coverage)
        / len(coverage),
        "high_window_fraction": math.fsum(value > high_threshold for value in coverage)
        / len(coverage),
    }
