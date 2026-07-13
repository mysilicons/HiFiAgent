"""Parser for BUSCO short summary output."""

import re
from pathlib import Path

BUSCO_SUMMARY = re.compile(
    r"C:(?P<complete>[0-9.]+)%\[S:(?P<single>[0-9.]+)%,D:(?P<duplicated>[0-9.]+)%\],"
    r"F:(?P<fragmented>[0-9.]+)%,M:(?P<missing>[0-9.]+)%"
)
BUSCO_LINEAGE_FROM_SUMMARY = re.compile(r"short_summary\.specific\.(?P<lineage>[^.]+)\.")
BUSCO_DATASET_VERSION = re.compile(r"_odb(?P<version>\d+)$")


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


def infer_busco_lineage(summary: Path | None) -> str | None:
    """Infer the actual BUSCO lineage from its specific summary filename or run directory."""
    if summary is None:
        return None
    match = BUSCO_LINEAGE_FROM_SUMMARY.search(summary.name)
    if match is not None:
        return match.group("lineage")
    for parent in summary.parents:
        if parent.name.startswith("run_"):
            return parent.name.removeprefix("run_")
    return None


def parse_busco_dataset_metadata(download_path: Path, lineage: str | None) -> dict[str, object]:
    """Read BUSCO dataset version and provenance metadata from `dataset.cfg`."""
    metadata: dict[str, object] = {
        "lineage": lineage,
        "odb_version": None,
        "orthodb_version": None,
        "dataset_version": None,
        "creation_date": None,
        "number_of_buscos": None,
        "dataset_config": None,
    }
    if lineage is None:
        return metadata
    version_match = BUSCO_DATASET_VERSION.search(lineage)
    if version_match is not None:
        metadata["odb_version"] = int(version_match.group("version"))
    candidates = (
        download_path / lineage / "dataset.cfg",
        download_path / "lineages" / lineage / "dataset.cfg",
    )
    dataset_config = next((path for path in candidates if path.is_file()), None)
    if dataset_config is None:
        return metadata
    metadata["dataset_config"] = str(dataset_config)
    values: dict[str, str] = {}
    for raw_line in dataset_config.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif "\t" in line:
            key, value = line.split("\t", 1)
        else:
            continue
        values[key.strip().lower()] = value.strip()
    metadata["creation_date"] = values.get("creation_date")
    metadata["orthodb_version"] = values.get("orthodb_version")
    metadata["dataset_version"] = values.get("dataset_version")
    number = values.get("number_of_buscos")
    if number is not None:
        try:
            metadata["number_of_buscos"] = int(number)
        except ValueError:
            pass
    return metadata
