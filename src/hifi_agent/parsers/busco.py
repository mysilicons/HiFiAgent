"""Parser for BUSCO short summary output."""

import re
from pathlib import Path

BUSCO_SUMMARY = re.compile(
    r"C:(?P<complete>[0-9.]+)%\[S:(?P<single>[0-9.]+)%,D:(?P<duplicated>[0-9.]+)%\],"
    r"F:(?P<fragmented>[0-9.]+)%,M:(?P<missing>[0-9.]+)%"
)


def parse_busco_summary(path: Path) -> dict[str, float | None]:
    """Parse BUSCO C/S/D/F/M percentages from a short summary file."""
    metrics: dict[str, float | None] = {
        "complete": None,
        "single": None,
        "duplicated": None,
        "fragmented": None,
        "missing": None,
    }
    if not path.is_file():
        return metrics
    match = BUSCO_SUMMARY.search(path.read_text(errors="replace").replace(" ", ""))
    if match is None:
        return metrics
    return {key: float(value) for key, value in match.groupdict().items()}


def find_busco_summary(root: Path) -> Path | None:
    """Find the most specific BUSCO text summary below an output directory."""
    candidates = sorted(root.rglob("short_summary.specific.*.txt"))
    if not candidates:
        candidates = sorted(root.rglob("short_summary*.txt"))
    return candidates[0] if candidates else None
