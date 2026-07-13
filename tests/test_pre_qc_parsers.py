import json
from pathlib import Path

import pytest

from hifi_agent.parsers.genomescope import parse_genomescope_report, parse_genomescope_stdout
from hifi_agent.parsers.hifiasm_log import parse_hifiasm_log, parse_time_report
from hifi_agent.parsers.kmer import parse_kmer_histogram
from hifi_agent.parsers.nanoplot import parse_nanostats
from hifi_agent.parsers.seqkit import parse_seqkit_stats
from hifi_agent.workflow_tools import main as workflow_tools_main


def test_parse_seqkit_stats_types_and_weighted_fields(tmp_path: Path) -> None:
    stats = tmp_path / "seqkit_stats.tsv"
    stats.write_text(
        "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len\t"
        "Q1\tQ2\tQ3\tsum_gap\tN50\tN50_num\tQ20(%)\tQ30(%)\tAvgQual\tGC(%)\tsum_n\n"
        "a.fastq\tFASTQ\tDNA\t2\t10\t4\t5.0\t6\t4\t5\t6\t0\t6\t1\t100\t100\t30\t40\t0\n"
        "b.fastq\tFASTQ\tDNA\t1\t20\t20\t20.0\t20\t20\t20\t20\t0\t20\t1\t100\t100\t20\t50\t0\n"
    )

    parsed = parse_seqkit_stats(stats)

    assert parsed.file_count == 2
    assert parsed.read_count == 3
    assert parsed.total_bases == 30
    assert parsed.mean_length == 10
    assert parsed.gc_percent == 46.666666666666664
    assert parsed.mean_qscore == 23.333333333333332
    assert parsed.read_n50 == 6
    assert "SEQKIT_MULTI_FILE_N50_IS_MIN_ROW_N50_APPROXIMATION" in parsed.warnings


def test_parse_nanostats_key_value_table(tmp_path: Path) -> None:
    nanostats = tmp_path / "NanoStats.txt"
    nanostats.write_text(
        "Metrics\tdataset\nnumber_of_reads\t3\nnumber_of_bases\t42.0\nmean_qscore\t31.5\n"
    )

    parsed = parse_nanostats(nanostats)

    assert parsed["number_of_reads"] == 3
    assert parsed["number_of_bases"] == 42
    assert parsed["mean_qscore"] == 31.5


def test_parse_kmer_histogram_is_reproducible(tmp_path: Path) -> None:
    histogram = tmp_path / "hist.tsv"
    histogram.write_text("depth\tcount\n1\t10\n2\t3\n5\t1\n")

    first = parse_kmer_histogram(histogram)
    second = parse_kmer_histogram(histogram)

    assert first == second
    assert first.distinct_kmers == 14
    assert first.total_kmer_observations == 21
    assert first.peak_depth == 1


def test_parse_kmer_histogram_flags_no_clear_non_error_peak(tmp_path: Path) -> None:
    histogram = tmp_path / "hist.tsv"
    histogram.write_text("1 10\n")

    parsed = parse_kmer_histogram(histogram)

    assert "KMER_NO_CLEAR_PEAK" in parsed.warnings


def test_parse_kmer_histogram_flags_multiple_comparable_peaks(tmp_path: Path) -> None:
    histogram = tmp_path / "hist.tsv"
    histogram.write_text("1 100\n2 10\n3 20\n4 10\n7 18\n8 4\n")

    parsed = parse_kmer_histogram(histogram)

    assert "KMER_MULTIPLE_COMPARABLE_PEAKS" in parsed.warnings


def test_parse_genomescope_stdout_and_report(tmp_path: Path) -> None:
    report = tmp_path / "summary.txt"
    report.write_text(
        "property                      min               max\n"
        "Genome Haploid Length         6,495,907 bp      6,509,546 bp\n"
        "Genome Repeat Length          867,436 bp        869,257 bp\n"
        "Model Fit                     79.5499%          88.387%\n"
    )

    stdout = "Model converged het:0.207 kcov:308 err:0.00877 model fit:1.35 len:6502719"

    parsed = {**parse_genomescope_report(report), **parse_genomescope_stdout(stdout)}

    assert parsed["genome_size"] == 6502719
    assert parsed["heterozygosity"] == 0.207
    assert parsed["kmer_coverage"] == 308
    assert parsed["error_rate"] == 0.00877
    assert parsed["model_fit"] == 1.35
    assert parsed["repeat_fraction"] == pytest.approx(0.1335, rel=0.01)


def test_parse_hifiasm_log_finds_threshold_and_resource_summary(tmp_path: Path) -> None:
    stderr = tmp_path / "hifiasm.stderr"
    stderr.write_text(
        "[M::purge_dups] homozygous read coverage threshold: 37\n"
        "[M::main] Version: 0.25.0-r726\n"
        "[M::main] Real time: 12.5 sec; CPU: 40.0 sec; Peak RSS: 16.008 GB\n"
    )
    time_report = tmp_path / "hifiasm.time.txt"
    time_report.write_text(
        "Elapsed (wall clock) time (h:mm:ss or m:ss): 0:12.50\n"
        "Maximum resident set size (kbytes): 123456\n"
    )

    parsed = parse_hifiasm_log(stderr)
    parsed_time = parse_time_report(time_report)

    assert parsed.homozygous_coverage_threshold == 37
    assert parsed.version == "0.25.0-r726"
    assert parsed.real_time_seconds == 12.5
    assert parsed.cpu_seconds == 40
    assert parsed.peak_rss_gb == 16.008
    assert parsed.warnings == ()
    assert parsed_time["maximum_resident_set_size_kbytes"] == 123456


def test_parse_hifiasm_log_warns_when_threshold_missing(tmp_path: Path) -> None:
    stderr = tmp_path / "hifiasm.stderr"
    stderr.write_text("[M::main] Version: 0.25.0-r726\n")

    parsed = parse_hifiasm_log(stderr)

    assert parsed.homozygous_coverage_threshold is None
    assert "HIFIASM_HOM_COV_THRESHOLD_NOT_FOUND" in parsed.warnings


def test_raw_metrics_coverage_with_expected_genome_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seqkit = tmp_path / "seqkit.tsv"
    seqkit.write_text(
        "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len\t"
        "Q1\tQ2\tQ3\tsum_gap\tN50\tN50_num\tQ20(%)\tQ30(%)\tAvgQual\tGC(%)\tsum_n\n"
        "a.fastq\tFASTQ\tDNA\t2\t100\t40\t50.0\t60\t40\t50\t60\t0\t60\t1\t100\t100\t30\t40\t0\n"
    )
    nanostats = tmp_path / "NanoStats.txt"
    nanostats.write_text("Metrics\tdataset\nnumber_of_reads\t2\n")
    kmer_metrics = tmp_path / "kmer_metrics.json"
    kmer_metrics.write_text(
        json.dumps({"kmer_source": "same_data_advisory", "peak_depth": 2, "warnings": []})
    )
    output = tmp_path / "raw_metrics.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "workflow_tools",
            "raw-metrics",
            "--sample-id",
            "sample",
            "--seqkit-stats",
            str(seqkit),
            "--nanostats",
            str(nanostats),
            "--kmer-metrics",
            str(kmer_metrics),
            "--expected-genome-size",
            "50",
            "--output",
            str(output),
        ],
    )

    workflow_tools_main()

    data = json.loads(output.read_text())
    assert data["estimated_coverage"] == 2
    assert data["estimated_genome_size"] == 50


def test_raw_metrics_coverage_null_without_genome_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seqkit = tmp_path / "seqkit.tsv"
    seqkit.write_text(
        "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len\t"
        "Q1\tQ2\tQ3\tsum_gap\tN50\tN50_num\tQ20(%)\tQ30(%)\tAvgQual\tGC(%)\tsum_n\n"
        "a.fastq\tFASTQ\tDNA\t2\t100\t40\t50.0\t60\t40\t50\t60\t0\t60\t1\t100\t100\t-\t40\t0\n"
    )
    nanostats = tmp_path / "NanoStats.txt"
    nanostats.write_text("key\tvalue\n")
    kmer_metrics = tmp_path / "kmer_metrics.json"
    kmer_metrics.write_text(json.dumps({"kmer_source": "same_data_advisory", "warnings": []}))
    output = tmp_path / "raw_metrics.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "workflow_tools",
            "raw-metrics",
            "--sample-id",
            "sample",
            "--seqkit-stats",
            str(seqkit),
            "--nanostats",
            str(nanostats),
            "--kmer-metrics",
            str(kmer_metrics),
            "--expected-genome-size",
            "",
            "--output",
            str(output),
        ],
    )

    workflow_tools_main()

    data = json.loads(output.read_text())
    assert data["estimated_coverage"] is None
    assert data["mean_qscore"] is None
    assert "COVERAGE_NOT_CALCULATED_NO_GENOME_SIZE" in data["warnings"]
    assert "MEAN_QSCORE_UNAVAILABLE" in data["warnings"]


def test_raw_metrics_coverage_uses_genomescope_size_when_expected_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seqkit = tmp_path / "seqkit.tsv"
    seqkit.write_text(
        "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len\t"
        "Q1\tQ2\tQ3\tsum_gap\tN50\tN50_num\tQ20(%)\tQ30(%)\tAvgQual\tGC(%)\tsum_n\n"
        "a.fastq\tFASTQ\tDNA\t2\t100\t40\t50.0\t60\t40\t50\t60\t0\t60\t1\t100\t100\t30\t40\t0\n"
    )
    nanostats = tmp_path / "NanoStats.txt"
    nanostats.write_text("Metrics\tdataset\nnumber_of_reads\t2\n")
    kmer_metrics = tmp_path / "kmer_metrics.json"
    kmer_metrics.write_text(
        json.dumps(
            {
                "kmer_source": "same_data_advisory",
                "genomescope_genome_size": 25,
                "warnings": [],
            }
        )
    )
    output = tmp_path / "raw_metrics.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "workflow_tools",
            "raw-metrics",
            "--sample-id",
            "sample",
            "--seqkit-stats",
            str(seqkit),
            "--nanostats",
            str(nanostats),
            "--kmer-metrics",
            str(kmer_metrics),
            "--expected-genome-size",
            "",
            "--output",
            str(output),
        ],
    )

    workflow_tools_main()

    data = json.loads(output.read_text())
    assert data["estimated_genome_size"] == 25
    assert data["estimated_genome_size_source"] == "genomescope"
    assert data["estimated_coverage"] == 4
    assert "COVERAGE_NOT_CALCULATED_NO_GENOME_SIZE" not in data["warnings"]
