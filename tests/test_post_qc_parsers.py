import gzip
import json
from pathlib import Path

import pytest

from hifi_agent.parsers.busco import (
    infer_busco_lineage,
    parse_busco_dataset_metadata,
    parse_busco_summary,
)
from hifi_agent.parsers.gfa import gfa_segments_to_fasta
from hifi_agent.parsers.mapping import parse_mapped_fraction, parse_window_coverage
from hifi_agent.parsers.merqury import parse_merqury_metrics
from hifi_agent.parsers.quast import parse_quast_report
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.workflow_tools import main as workflow_tools_main


def test_quast_busco_merqury_and_mapping_parsers_preserve_scientific_types(
    tmp_path: Path,
) -> None:
    quast = tmp_path / "report.tsv"
    quast.write_text(
        "Assembly\tbaseline\n"
        "# contigs\t215\nLargest contig\t3,233,620\nTotal length\t22,812,604\n"
        "N50\t1,247,647\nL50\t6\n# misassemblies\t163\n"
        "# local misassemblies\t51\nGenome fraction (%)\t99.401\n"
        "Duplication ratio\t1.389\n"
    )
    busco = tmp_path / "short_summary.txt"
    busco.write_text("C:98.2%[S:94.1%,D:4.1%],F:0.8%,M:1.0%,n:2137\n")
    qv = tmp_path / "baseline.qv"
    qv.write_text("baseline\t4016996\t22428196\t20.29\t0.009\n")
    completeness = tmp_path / "baseline.completeness.stats"
    completeness.write_text("baseline\tall\t9493050\t15515001\t61.1863\n")
    flagstat = tmp_path / "flagstat.txt"
    flagstat.write_text("31 + 0 in total\n20 + 0 mapped (95.00% : N/A)\n")
    windows = tmp_path / "coverage_windows.tsv"
    windows.write_text("ctg\t0\t100\t1000\nctg\t100\t200\t0\nctg\t200\t300\t3000\n")

    quast_values = parse_quast_report(quast)
    assert quast_values["assembly_size"] == 22_812_604
    assert quast_values["contig_n50"] == 1_247_647
    assert quast_values["misassemblies"] == 163
    assert quast_values["genome_fraction"] == pytest.approx(99.401)
    assert parse_busco_summary(busco) == {
        "complete": 98.2,
        "single": 94.1,
        "duplicated": 4.1,
        "fragmented": 0.8,
        "missing": 1.0,
    }
    assert parse_merqury_metrics(qv, completeness) == {
        "qv": 20.29,
        "completeness": 61.1863,
    }
    coverage = parse_window_coverage(windows)
    assert parse_mapped_fraction(flagstat) == pytest.approx(0.95)
    assert coverage["mean"] == pytest.approx(13.333333)
    assert coverage["median"] == pytest.approx(10)
    assert coverage["low_window_fraction"] == pytest.approx(1 / 3)
    assert coverage["high_window_fraction"] == pytest.approx(1 / 3)


def test_busco_lineage_dataset_and_zero_median_coverage_edges(tmp_path: Path) -> None:
    summary = tmp_path / "short_summary.specific.saccharomycetes_odb12.baseline.txt"
    summary.write_text("C:98.2%[S:94.1%,D:4.1%],F:0.8%,M:1.0%,n:2137\n")
    downloads = tmp_path / "downloads"
    dataset = downloads / "saccharomycetes_odb12"
    dataset.mkdir(parents=True)
    (dataset / "dataset.cfg").write_text(
        "creation_date=2024-01-08\nnumber_of_buscos=2137\n"
        "orthodb_version=12.1\ndataset_version=02\n"
    )
    lineage = infer_busco_lineage(summary)
    metadata = parse_busco_dataset_metadata(downloads, lineage)
    assert lineage == "saccharomycetes_odb12"
    assert metadata == {
        "lineage": "saccharomycetes_odb12",
        "odb_version": 12,
        "creation_date": "2024-01-08",
        "number_of_buscos": 2137,
        "orthodb_version": "12.1",
        "dataset_version": "02",
        "dataset_config": str(dataset / "dataset.cfg"),
    }

    windows = tmp_path / "zero_median.tsv"
    windows.write_text("ctg\t0\t100\t0\nctg\t100\t200\t0\nctg\t200\t300\t3000\n")
    coverage = parse_window_coverage(windows)
    assert coverage["median"] == 0
    assert coverage["low_window_fraction"] == pytest.approx(2 / 3)
    assert coverage["high_window_fraction"] == pytest.approx(1 / 3)


def test_literal_gfa_conversion_is_deterministic_and_rejects_missing_sequence(
    tmp_path: Path,
) -> None:
    gfa = tmp_path / "assembly.gfa"
    fasta = tmp_path / "assembly.fa"
    gfa.write_text("H\tVN:Z:1.0\nS\tcontig1\tACGT\nS\tcontig2\tTTAA\n")
    assert gfa_segments_to_fasta(gfa, fasta) == 2
    assert fasta.read_text() == ">contig1\nACGT\n>contig2\nTTAA\n"
    gfa.write_text("S\tcontig1\t*\n")
    with pytest.raises(ValueError, match="Invalid literal GFA"):
        gfa_segments_to_fasta(gfa, fasta)


def test_hifi_filter_applies_length_and_qscore_and_writes_summary(
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
    assert values["schema_id"] == "hifi-agent"
    assert values["input_read_count"] == 3
    assert values["retained_read_count"] == 1
    assert values["retained_read_fraction"] == pytest.approx(1 / 3)


def test_assembly_metrics_aggregates_tool_failures_nulls_and_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = {
        "quast": {
            "schema_id": "hifi-agent",
            "tool": "quast",
            "status": "success",
            "version": "QUAST 5.3.0",
            "metrics": {"assembly_size": 120, "contig_count": 2, "contig_n50": 80},
            "limitations": ["QUAST_REFERENCE_FREE_NO_MISASSEMBLY_METRICS"],
        },
        "busco": {
            "schema_id": "hifi-agent",
            "tool": "busco",
            "status": "failed",
            "version": "BUSCO 6.0.0",
            "metrics": {},
            "limitations": [],
        },
        "merqury": {
            "schema_id": "hifi-agent",
            "tool": "merqury",
            "status": "success",
            "version": "Merqury 1.3",
            "kmer_source": "same_data_advisory",
            "metrics": {"qv": 35.5, "completeness": 97.2},
            "limitations": ["MERQURY_SAME_HIFI_DATA_NOT_INDEPENDENT"],
        },
        "mapping": {
            "schema_id": "hifi-agent",
            "tool": "mapping",
            "status": "success",
            "versions": {
                "minimap2": "2.30",
                "samtools": "1.22.1",
                "coverage": "2.31.1",
            },
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
    assert metrics.tool_versions["minimap2"] == "2.30"
