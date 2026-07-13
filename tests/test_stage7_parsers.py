import gzip
import json
from pathlib import Path

import pytest

from hifi_agent.parsers.busco import (
    infer_busco_lineage,
    parse_busco_dataset_metadata,
    parse_busco_summary,
)
from hifi_agent.parsers.mapping import parse_mapped_fraction, parse_window_coverage
from hifi_agent.parsers.merqury import parse_merqury_metrics
from hifi_agent.parsers.quast import parse_quast_report
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.workflow_tools import main as workflow_tools_main


def test_parse_quast_reference_metrics(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    report.write_text(
        "Assembly\tbaseline\n"
        "# contigs\t215\n"
        "Largest contig\t3,233,620\n"
        "Total length\t22,812,604\n"
        "N50\t1,247,647\n"
        "L50\t6\n"
        "# misassemblies\t163\n"
        "# local misassemblies\t51\n"
        "Genome fraction (%)\t99.401\n"
        "Duplication ratio\t1.389\n"
    )

    parsed = parse_quast_report(report)

    assert parsed["assembly_size"] == 22_812_604
    assert parsed["contig_n50"] == 1_247_647
    assert parsed["misassemblies"] == 163
    assert parsed["genome_fraction"] == pytest.approx(99.401)


def test_parse_busco_keeps_complete_and_duplicated_separate(tmp_path: Path) -> None:
    summary = tmp_path / "short_summary.txt"
    summary.write_text("C:98.2%[S:94.1%,D:4.1%],F:0.8%,M:1.0%,n:2137\n")

    parsed = parse_busco_summary(summary)

    assert parsed == {
        "complete": 98.2,
        "single": 94.1,
        "duplicated": 4.1,
        "fragmented": 0.8,
        "missing": 1.0,
    }


def test_busco_auto_lineage_and_dataset_version_are_recorded(tmp_path: Path) -> None:
    summary = tmp_path / "short_summary.specific.saccharomycetes_odb12.baseline.txt"
    summary.write_text("C:98.2%[S:94.1%,D:4.1%],F:0.8%,M:1.0%,n:2137\n")
    download_path = tmp_path / "downloads"
    dataset = download_path / "saccharomycetes_odb12"
    dataset.mkdir(parents=True)
    (dataset / "dataset.cfg").write_text(
        "creation_date=2024-01-08\nnumber_of_buscos=2137\n"
        "orthodb_version=12.1\ndataset_version=02\n"
    )

    lineage = infer_busco_lineage(summary)
    metadata = parse_busco_dataset_metadata(download_path, lineage)

    assert lineage == "saccharomycetes_odb12"
    assert metadata["odb_version"] == 12
    assert metadata["creation_date"] == "2024-01-08"
    assert metadata["number_of_buscos"] == 2137
    assert metadata["orthodb_version"] == "12.1"
    assert metadata["dataset_version"] == "02"


def test_parse_merqury_qv_and_completeness(tmp_path: Path) -> None:
    qv = tmp_path / "baseline.qv"
    qv.write_text("baseline\t4016996\t22428196\t20.29\t0.009\n")
    completeness = tmp_path / "baseline.completeness.stats"
    completeness.write_text("baseline\tall\t9493050\t15515001\t61.1863\n")

    parsed = parse_merqury_metrics(qv, completeness)

    assert parsed["qv"] == pytest.approx(20.29)
    assert parsed["completeness"] == pytest.approx(61.1863)


def test_parse_mapping_fraction_and_window_statistics(tmp_path: Path) -> None:
    flagstat = tmp_path / "flagstat.txt"
    flagstat.write_text("31 + 0 in total\n20 + 0 mapped (95.00% : N/A)\n")
    windows = tmp_path / "coverage_windows.tsv"
    windows.write_text("ctg\t0\t100\t1000\nctg\t100\t200\t0\nctg\t200\t300\t3000\n")

    coverage = parse_window_coverage(windows)

    assert parse_mapped_fraction(flagstat) == pytest.approx(0.95)
    assert coverage["mean"] == pytest.approx(13.333333)
    assert coverage["median"] == pytest.approx(10)
    assert coverage["low_window_fraction"] == pytest.approx(1 / 3)
    assert coverage["high_window_fraction"] == pytest.approx(1 / 3)


def test_zero_median_coverage_uses_mean_for_anomaly_thresholds(tmp_path: Path) -> None:
    windows = tmp_path / "coverage_windows.tsv"
    windows.write_text("ctg\t0\t100\t0\nctg\t100\t200\t0\nctg\t200\t300\t3000\n")

    coverage = parse_window_coverage(windows)

    assert coverage["median"] == 0
    assert coverage["low_window_fraction"] == pytest.approx(2 / 3)
    assert coverage["high_window_fraction"] == pytest.approx(1 / 3)


def test_hifi_filter_applies_length_and_mean_qscore_thresholds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@keep\nACGT\n+\nIIII\n@short\nAC\n+\nII\n@lowq\nACGT\n+\n!!!!\n")
    output = tmp_path / "filtered.fastq.gz"
    summary = tmp_path / "filter.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "workflow_tools",
            "filter-hifi-reads",
            "--input",
            str(reads),
            "--output",
            str(output),
            "--summary",
            str(summary),
            "--min-read-length",
            "4",
            "--min-mean-qscore",
            "20",
        ],
    )

    workflow_tools_main()

    with gzip.open(output, "rt") as handle:
        assert handle.read() == "@keep\nACGT\n+\nIIII\n"
    values = json.loads(summary.read_text())
    assert values["input_read_count"] == 3
    assert values["retained_read_count"] == 1
    assert values["retained_read_fraction"] == pytest.approx(1 / 3)


def test_assembly_metrics_aggregates_failures_and_nulls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = {
        "quast": {
            "tool": "quast",
            "status": "success",
            "version": "QUAST 5.3.0",
            "metrics": {"assembly_size": 120, "contig_count": 2, "contig_n50": 80},
            "limitations": ["QUAST_REFERENCE_FREE_NO_MISASSEMBLY_METRICS"],
        },
        "busco": {
            "tool": "busco",
            "status": "failed",
            "version": "BUSCO 6.0.0",
            "metrics": {},
            "limitations": [],
        },
        "merqury": {
            "tool": "merqury",
            "status": "success",
            "version": "Merqury 1.3",
            "metrics": {"qv": 35.5, "completeness": 97.2},
            "limitations": ["MERQURY_SAME_HIFI_DATA_NOT_INDEPENDENT"],
        },
        "mapping": {
            "tool": "mapping",
            "status": "success",
            "versions": {"minimap2": "2.30", "samtools": "1.22.1", "coverage": "2.31.1"},
            "metrics": {"mapped_read_fraction": 0.99, "cv": 0.2},
            "limitations": [],
        },
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload))
        paths[name] = path
    output = tmp_path / "assembly_metrics.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "workflow_tools",
            "assembly-metrics",
            "--run-id",
            "baseline",
            "--quast",
            str(paths["quast"]),
            "--busco",
            str(paths["busco"]),
            "--merqury",
            str(paths["merqury"]),
            "--mapping",
            str(paths["mapping"]),
            "--expected-genome-size",
            "100",
            "--output",
            str(output),
        ],
    )

    workflow_tools_main()
    metrics = AssemblyMetrics.model_validate_json(output.read_text())

    assert metrics.assembly_size_ratio == pytest.approx(1.2)
    assert metrics.busco_complete is None
    assert metrics.tool_failures == ["busco"]
    assert "MERQURY_SAME_HIFI_DATA_NOT_INDEPENDENT" in metrics.metric_limitations
    expected_classified_fields = {
        name
        for name in AssemblyMetrics.model_fields
        if name
        not in {
            "schema_version",
            "run_id",
            "tool_failures",
            "metric_limitations",
            "metric_classes",
            "tool_versions",
            "tool_metadata",
            "source_files",
        }
    }
    assert set(metrics.metric_classes) == expected_classified_fields
