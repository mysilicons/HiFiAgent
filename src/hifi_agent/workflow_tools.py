"""Small deterministic helpers used by the Nextflow workflow processes."""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from hifi_agent.parsers.busco import (
    find_busco_summary,
    infer_busco_lineage,
    parse_busco_dataset_metadata,
    parse_busco_summary,
)
from hifi_agent.parsers.genomescope import (
    parse_genomescope_report,
    parse_genomescope_stdout,
    parse_genomescope_summary,
)
from hifi_agent.parsers.hifiasm_log import parse_hifiasm_log, parse_time_report
from hifi_agent.parsers.kmer import parse_kmer_histogram
from hifi_agent.parsers.mapping import parse_mapped_fraction, parse_window_coverage
from hifi_agent.parsers.merqury import parse_merqury_metrics
from hifi_agent.parsers.nanoplot import parse_nanostats
from hifi_agent.parsers.quast import parse_quast_report
from hifi_agent.parsers.seqkit import SeqkitStats, parse_seqkit_stats
from hifi_agent.schemas.metrics import AssemblyMetrics

KMER_SOURCE_SAME_DATA = "same_data_advisory"


def main() -> None:
    """Run workflow helper subcommands."""
    parser = argparse.ArgumentParser(prog="python -m hifi_agent.workflow_tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_genomescope = subparsers.add_parser("run-genomescope")
    run_genomescope.add_argument("--histogram", type=Path, required=True)
    run_genomescope.add_argument("--k", type=int, required=True)
    run_genomescope.add_argument("--output-dir", type=Path, required=True)
    run_genomescope.add_argument("--summary", type=Path, required=True)
    run_genomescope.set_defaults(func=_run_genomescope)

    kmer_metrics = subparsers.add_parser("kmer-metrics")
    kmer_metrics.add_argument("--sample-id", required=True)
    kmer_metrics.add_argument("--histogram", type=Path, required=True)
    kmer_metrics.add_argument("--genomescope-summary", type=Path, required=True)
    kmer_metrics.add_argument("--expected-genome-size", default="")
    kmer_metrics.add_argument("--kmer-source", default=KMER_SOURCE_SAME_DATA)
    kmer_metrics.add_argument("--low-coverage-peak-threshold", type=float, default=10.0)
    kmer_metrics.add_argument("--output", type=Path, required=True)
    kmer_metrics.set_defaults(func=_kmer_metrics)

    raw_metrics = subparsers.add_parser("raw-metrics")
    raw_metrics.add_argument("--sample-id", required=True)
    raw_metrics.add_argument("--seqkit-stats", type=Path, required=True)
    raw_metrics.add_argument("--nanostats", type=Path, required=True)
    raw_metrics.add_argument("--kmer-metrics", type=Path, required=True)
    raw_metrics.add_argument("--expected-genome-size", default="")
    raw_metrics.add_argument("--output", type=Path, required=True)
    raw_metrics.set_defaults(func=_raw_metrics)

    filter_reads = subparsers.add_parser("filter-hifi-reads")
    filter_reads.add_argument("--input", type=Path, nargs="+", required=True)
    filter_reads.add_argument("--output", type=Path, required=True)
    filter_reads.add_argument("--summary", type=Path, required=True)
    filter_reads.add_argument("--min-read-length", type=int, required=True)
    filter_reads.add_argument("--min-mean-qscore", type=float, required=True)
    filter_reads.set_defaults(func=_filter_hifi_reads)

    hifiasm_manifest = subparsers.add_parser("hifiasm-manifest")
    hifiasm_manifest.add_argument("--sample-id", required=True)
    hifiasm_manifest.add_argument("--run-id", required=True)
    hifiasm_manifest.add_argument("--prefix", required=True)
    hifiasm_manifest.add_argument("--command-file", type=Path, required=True)
    hifiasm_manifest.add_argument("--stdout", type=Path, required=True)
    hifiasm_manifest.add_argument("--stderr", type=Path, required=True)
    hifiasm_manifest.add_argument("--time-report", type=Path, required=True)
    hifiasm_manifest.add_argument("--reused-bins-record", type=Path, required=True)
    hifiasm_manifest.add_argument("--output", type=Path, required=True)
    hifiasm_manifest.set_defaults(func=_hifiasm_manifest)

    quast_metrics = subparsers.add_parser("quast-metrics")
    quast_metrics.add_argument("--report", type=Path, required=True)
    quast_metrics.add_argument("--status", type=int, required=True)
    quast_metrics.add_argument("--mode", required=True)
    quast_metrics.add_argument("--version-file", type=Path, required=True)
    quast_metrics.add_argument("--output", type=Path, required=True)
    quast_metrics.set_defaults(func=_quast_metrics)

    busco_metrics = subparsers.add_parser("busco-metrics")
    busco_metrics.add_argument("--root", type=Path, required=True)
    busco_metrics.add_argument("--status", type=int, required=True)
    busco_metrics.add_argument("--lineage", required=True)
    busco_metrics.add_argument("--download-path", type=Path, required=True)
    busco_metrics.add_argument("--version-file", type=Path, required=True)
    busco_metrics.add_argument("--output", type=Path, required=True)
    busco_metrics.set_defaults(func=_busco_metrics)

    merqury_metrics = subparsers.add_parser("merqury-metrics")
    merqury_metrics.add_argument("--qv", type=Path, required=True)
    merqury_metrics.add_argument("--completeness", type=Path, required=True)
    merqury_metrics.add_argument("--status", type=int, required=True)
    merqury_metrics.add_argument("--kmer-source", required=True)
    merqury_metrics.add_argument("--version-file", type=Path, required=True)
    merqury_metrics.add_argument("--output", type=Path, required=True)
    merqury_metrics.set_defaults(func=_merqury_metrics)

    mapping_metrics = subparsers.add_parser("mapping-metrics")
    mapping_metrics.add_argument("--flagstat", type=Path, required=True)
    mapping_metrics.add_argument("--windows", type=Path, required=True)
    mapping_metrics.add_argument("--status", type=int, required=True)
    mapping_metrics.add_argument("--preset", required=True)
    mapping_metrics.add_argument("--minimap2-version", type=Path, required=True)
    mapping_metrics.add_argument("--samtools-version", type=Path, required=True)
    mapping_metrics.add_argument("--coverage-tool-version", type=Path, required=True)
    mapping_metrics.add_argument("--filter-summary", type=Path, required=True)
    mapping_metrics.add_argument("--output", type=Path, required=True)
    mapping_metrics.set_defaults(func=_mapping_metrics)

    assembly_metrics = subparsers.add_parser("assembly-metrics")
    assembly_metrics.add_argument("--run-id", required=True)
    assembly_metrics.add_argument("--quast", type=Path, required=True)
    assembly_metrics.add_argument("--busco", type=Path, required=True)
    assembly_metrics.add_argument("--merqury", type=Path, required=True)
    assembly_metrics.add_argument("--mapping", type=Path, required=True)
    assembly_metrics.add_argument("--expected-genome-size", default="")
    assembly_metrics.add_argument("--output", type=Path, required=True)
    assembly_metrics.set_defaults(func=_assembly_metrics)

    args = parser.parse_args()
    args.func(args)


def _run_genomescope(args: argparse.Namespace) -> None:
    genomescope = shutil.which("genomescope.R")
    if genomescope is None and Path("/home/gw/software/genomescope2.0/genomescope.R").is_file():
        genomescope = "/home/gw/software/genomescope2.0/genomescope.R"
    if genomescope is None:
        _write_key_value_table(
            args.summary,
            {
                "model_status": "not_available",
                "genome_size": None,
                "heterozygosity": None,
                "repeat_fraction": None,
                "warning": "GENOMESCOPE_EXECUTABLE_NOT_FOUND",
            },
        )
        return

    args.output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "Rscript",
        genomescope,
        "-i",
        str(args.histogram),
        "-o",
        str(args.output_dir),
        "-k",
        str(args.k),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    (args.output_dir / "genomescope.stdout").write_text(completed.stdout)
    (args.output_dir / "genomescope.stderr").write_text(completed.stderr)

    if completed.returncode != 0:
        _write_key_value_table(
            args.summary,
            {
                "model_status": "failed",
                "genome_size": None,
                "heterozygosity": None,
                "repeat_fraction": None,
                "warning": "GENOMESCOPE_MODEL_FAILED",
                "exit_code": completed.returncode,
            },
        )
        return

    parsed = {
        **parse_genomescope_report(args.output_dir / "summary.txt"),
        **parse_genomescope_stdout(f"{completed.stdout}\n{completed.stderr}"),
    }
    _write_key_value_table(
        args.summary,
        {
            "model_status": "success",
            "genome_size": parsed.get("genome_size"),
            "heterozygosity": parsed.get("heterozygosity"),
            "repeat_fraction": parsed.get("repeat_fraction"),
            "kmer_coverage": parsed.get("kmer_coverage"),
            "error_rate": parsed.get("error_rate"),
            "model_fit": parsed.get("model_fit"),
            "warning": None,
        },
    )


def _kmer_metrics(args: argparse.Namespace) -> None:
    histogram = parse_kmer_histogram(args.histogram)
    genomescope = parse_genomescope_summary(args.genomescope_summary)
    expected_genome_size = _optional_int(args.expected_genome_size)
    genome_size_for_coverage = expected_genome_size or _optional_positive_int(
        genomescope.get("genome_size")
    )
    warnings = list(histogram.warnings)
    if histogram.peak_depth is None:
        warnings.append("KMER_NO_CLEAR_PEAK")
    elif histogram.peak_depth < args.low_coverage_peak_threshold:
        warnings.append("KMER_LOW_COVERAGE_PEAK")
    model_status = genomescope.get("model_status")
    summary_warning = genomescope.get("warning")
    if isinstance(summary_warning, str):
        warnings.append(summary_warning)
    if model_status == "failed":
        warnings.append("GENOMESCOPE_MODEL_FAILED")
    elif model_status != "success":
        warnings.append("GENOMESCOPE_MODEL_NOT_AVAILABLE")
    elif genomescope.get("genome_size") is None:
        warnings.append("GENOMESCOPE_MODEL_INCOMPLETE")

    data = {
        "sample_id": args.sample_id,
        "kmer_source": args.kmer_source,
        "histogram": str(args.histogram),
        "distinct_kmers": histogram.distinct_kmers,
        "total_kmer_observations": histogram.total_kmer_observations,
        "peak_depth": histogram.peak_depth,
        "peak_count": histogram.peak_count,
        "low_coverage_peak_threshold": args.low_coverage_peak_threshold,
        "genomescope_model_status": model_status,
        "genomescope_genome_size": genomescope.get("genome_size"),
        "genomescope_heterozygosity": genomescope.get("heterozygosity"),
        "genomescope_repeat_fraction": genomescope.get("repeat_fraction"),
        "genomescope_model_fit": genomescope.get("model_fit"),
        "genome_size_for_coverage": genome_size_for_coverage,
        "warnings": sorted(dict.fromkeys(warnings)),
    }
    _write_json(args.output, data)


def _raw_metrics(args: argparse.Namespace) -> None:
    seqkit = parse_seqkit_stats(args.seqkit_stats)
    nanostats = parse_nanostats(args.nanostats)
    kmer_metrics = _read_json(args.kmer_metrics)
    expected_genome_size = _optional_int(args.expected_genome_size)
    genome_size_for_coverage, genome_size_source = _select_genome_size_for_coverage(
        expected_genome_size,
        kmer_metrics,
    )
    estimated_coverage = (
        seqkit.total_bases / genome_size_for_coverage if genome_size_for_coverage else None
    )

    warnings = list(seqkit.warnings)
    warning = nanostats.get("warning")
    if isinstance(warning, str):
        warnings.append(warning)
    kmer_warnings = kmer_metrics.get("warnings", [])
    if isinstance(kmer_warnings, list):
        warnings.extend(str(item) for item in kmer_warnings)
    if genome_size_for_coverage is None:
        warnings.append("COVERAGE_NOT_CALCULATED_NO_GENOME_SIZE")
    if seqkit.mean_qscore is None:
        warnings.append("MEAN_QSCORE_UNAVAILABLE")

    data = {
        "sample_id": args.sample_id,
        "input_status": "PASS",
        "read_count": seqkit.read_count,
        "total_bases": seqkit.total_bases,
        "mean_read_length": seqkit.mean_length,
        "read_n50": seqkit.read_n50,
        "mean_qscore": seqkit.mean_qscore,
        "gc_percent": seqkit.gc_percent,
        "estimated_genome_size": genome_size_for_coverage,
        "estimated_genome_size_source": genome_size_source,
        "estimated_coverage": estimated_coverage,
        "kmer_source": kmer_metrics.get("kmer_source", KMER_SOURCE_SAME_DATA),
        "kmer_peak_depth": kmer_metrics.get("peak_depth"),
        "genomescope_model_status": kmer_metrics.get("genomescope_model_status"),
        "warnings": sorted(dict.fromkeys(warnings)),
        "tool_outputs": {
            "seqkit_stats": str(args.seqkit_stats),
            "nanostats": str(args.nanostats),
            "kmer_metrics": str(args.kmer_metrics),
        },
    }
    _validate_raw_metric_types(data, seqkit)
    _write_json(args.output, data)


def _filter_hifi_reads(args: argparse.Namespace) -> None:
    """Stream four-line FASTQ records through conservative length/quality filters."""
    input_count = 0
    input_bases = 0
    retained_count = 0
    retained_bases = 0
    filtered_short_count = 0
    filtered_low_quality_count = 0
    with gzip.open(args.output, "wt", compresslevel=1) as output:
        for input_path in args.input:
            opener = gzip.open if input_path.suffix == ".gz" else Path.open
            with opener(input_path, "rt") as source:
                while header := source.readline():
                    sequence = source.readline()
                    separator = source.readline()
                    quality = source.readline()
                    if not sequence or not separator or not quality:
                        raise ValueError(f"Incomplete FASTQ record in {input_path}")
                    sequence_text = sequence.rstrip("\r\n")
                    quality_text = quality.rstrip("\r\n")
                    if not header.startswith("@") or not separator.startswith("+"):
                        raise ValueError(f"Invalid FASTQ record in {input_path}")
                    if len(sequence_text) != len(quality_text):
                        raise ValueError(f"Sequence/quality length mismatch in {input_path}")
                    read_length = len(sequence_text)
                    mean_qscore = (
                        sum(ord(character) - 33 for character in quality_text) / read_length
                        if read_length
                        else 0.0
                    )
                    input_count += 1
                    input_bases += read_length
                    if read_length < args.min_read_length:
                        filtered_short_count += 1
                        continue
                    if mean_qscore < args.min_mean_qscore:
                        filtered_low_quality_count += 1
                        continue
                    output.write(header)
                    output.write(sequence)
                    output.write(separator)
                    output.write(quality)
                    retained_count += 1
                    retained_bases += read_length
    summary: dict[str, object] = {
        "input_read_count": input_count,
        "input_bases": input_bases,
        "retained_read_count": retained_count,
        "retained_bases": retained_bases,
        "filtered_short_read_count": filtered_short_count,
        "filtered_low_quality_read_count": filtered_low_quality_count,
        "min_read_length": args.min_read_length,
        "min_mean_qscore": args.min_mean_qscore,
        "retained_read_fraction": retained_count / input_count if input_count else None,
    }
    _write_json(args.summary, summary)


def _hifiasm_manifest(args: argparse.Namespace) -> None:
    log_summary = parse_hifiasm_log(args.stderr)
    time_report = parse_time_report(args.time_report)
    data = {
        "sample_id": args.sample_id,
        "run_id": args.run_id,
        "assembler": "hifiasm",
        "prefix": args.prefix,
        "command": args.command_file.read_text().strip(),
        "hifiasm_version": log_summary.version,
        "homozygous_coverage_threshold": log_summary.homozygous_coverage_threshold,
        "real_time_seconds": log_summary.real_time_seconds,
        "cpu_seconds": log_summary.cpu_seconds,
        "peak_rss_gb": log_summary.peak_rss_gb,
        "time_report": time_report,
        "stdout": str(args.stdout),
        "stderr": str(args.stderr),
        "gfa_outputs": _relative_files(args.output.parent, "gfa", "*.gfa"),
        "fasta_outputs": _relative_files(args.output.parent, "fasta", "*.fa"),
        "bin_outputs": _relative_files(args.output.parent, "bins", "*.bin"),
        "reused_bin_count": _count_reused_bins(args.reused_bins_record),
        "reused_bins_record": str(args.reused_bins_record),
        "warnings": list(log_summary.warnings),
    }
    _write_json(args.output, data)


def _quast_metrics(args: argparse.Namespace) -> None:
    parsed = parse_quast_report(args.report)
    success = args.status == 0 and parsed["assembly_size"] is not None
    limitations: list[str] = []
    if args.mode == "reference_free":
        limitations.append("QUAST_REFERENCE_FREE_NO_MISASSEMBLY_METRICS")
    _write_json(
        args.output,
        {
            "tool": "quast",
            "status": "success" if success else "failed",
            "exit_code": args.status,
            "mode": args.mode,
            "version": _first_line(args.version_file),
            "metrics": parsed,
            "limitations": limitations,
            "source": str(args.report),
        },
    )


def _busco_metrics(args: argparse.Namespace) -> None:
    summary = find_busco_summary(args.root)
    parsed = parse_busco_summary(summary) if summary is not None else parse_busco_summary(Path(""))
    success = args.status == 0 and parsed["complete"] is not None
    limitations = [] if args.lineage else ["BUSCO_LINEAGE_AUTO_RECOMMENDED"]
    actual_lineage = infer_busco_lineage(summary) or (args.lineage if args.lineage else None)
    dataset = parse_busco_dataset_metadata(args.download_path, actual_lineage)
    _write_json(
        args.output,
        {
            "tool": "busco",
            "status": "success" if success else "failed",
            "exit_code": args.status,
            "requested_lineage": args.lineage or None,
            "lineage": actual_lineage,
            "lineage_selection": "explicit" if args.lineage else "auto-lineage-euk",
            "dataset": dataset,
            "version": _first_line(args.version_file),
            "metrics": parsed,
            "limitations": limitations,
            "source": str(summary) if summary is not None else "",
        },
    )


def _merqury_metrics(args: argparse.Namespace) -> None:
    parsed = parse_merqury_metrics(args.qv, args.completeness)
    success = args.status == 0 and parsed["qv"] is not None
    limitations = (
        ["MERQURY_SAME_HIFI_DATA_NOT_INDEPENDENT"]
        if args.kmer_source == KMER_SOURCE_SAME_DATA
        else []
    )
    _write_json(
        args.output,
        {
            "tool": "merqury",
            "status": "success" if success else "failed",
            "exit_code": args.status,
            "kmer_source": args.kmer_source,
            "version": _first_line(args.version_file),
            "metrics": parsed,
            "limitations": limitations,
            "source": {"qv": str(args.qv), "completeness": str(args.completeness)},
        },
    )


def _mapping_metrics(args: argparse.Namespace) -> None:
    coverage = parse_window_coverage(args.windows)
    mapped_fraction = parse_mapped_fraction(args.flagstat)
    filter_summary = _read_json(args.filter_summary)
    success = args.status == 0 and mapped_fraction is not None
    _write_json(
        args.output,
        {
            "tool": "mapping",
            "status": "success" if success else "failed",
            "exit_code": args.status,
            "preset": args.preset,
            "versions": {
                "minimap2": _first_line(args.minimap2_version),
                "samtools": _first_line(args.samtools_version),
                "coverage": _first_line(args.coverage_tool_version),
            },
            "metrics": {
                "mapped_read_fraction": mapped_fraction,
                "input_read_count": filter_summary.get("input_read_count"),
                "retained_read_count": filter_summary.get("retained_read_count"),
                "retained_read_fraction": filter_summary.get("retained_read_fraction"),
                **coverage,
            },
            "filter": filter_summary,
            "limitations": ["MAPPING_FILTERED_HIFI_READS"],
            "source": {
                "flagstat": str(args.flagstat),
                "windows": str(args.windows),
                "filter_summary": str(args.filter_summary),
            },
        },
    )


def _assembly_metrics(args: argparse.Namespace) -> None:
    quast = _read_json(args.quast)
    busco = _read_json(args.busco)
    merqury = _read_json(args.merqury)
    mapping = _read_json(args.mapping)
    quast_values = _nested_dict(quast, "metrics")
    busco_values = _nested_dict(busco, "metrics")
    merqury_values = _nested_dict(merqury, "metrics")
    mapping_values = _nested_dict(mapping, "metrics")
    expected_genome_size = _optional_int(args.expected_genome_size)
    assembly_size = _typed_int(quast_values.get("assembly_size"))
    assembly_size_ratio = (
        assembly_size / expected_genome_size
        if assembly_size is not None and expected_genome_size is not None
        else None
    )
    tool_payloads = (quast, busco, merqury, mapping)
    tool_failures = [
        str(payload.get("tool")) for payload in tool_payloads if payload.get("status") != "success"
    ]
    limitation_values: set[str] = set()
    for payload in tool_payloads:
        payload_limitations = payload.get("limitations")
        if isinstance(payload_limitations, list):
            limitation_values.update(str(item) for item in payload_limitations)
    limitations = sorted(limitation_values)
    metrics = AssemblyMetrics(
        run_id=args.run_id,
        assembly_size=assembly_size,
        contig_count=_typed_int(quast_values.get("contig_count")),
        contig_n50=_typed_int(quast_values.get("contig_n50")),
        contig_l50=_typed_int(quast_values.get("contig_l50")),
        longest_contig=_typed_int(quast_values.get("longest_contig")),
        quast_misassemblies=_typed_int(quast_values.get("misassemblies")),
        quast_local_misassemblies=_typed_int(quast_values.get("local_misassemblies")),
        genome_fraction=_typed_float(quast_values.get("genome_fraction")),
        duplication_ratio=_typed_float(quast_values.get("duplication_ratio")),
        busco_complete=_typed_float(busco_values.get("complete")),
        busco_single=_typed_float(busco_values.get("single")),
        busco_duplicated=_typed_float(busco_values.get("duplicated")),
        busco_fragmented=_typed_float(busco_values.get("fragmented")),
        busco_missing=_typed_float(busco_values.get("missing")),
        kmer_qv=_typed_float(merqury_values.get("qv")),
        kmer_completeness=_typed_float(merqury_values.get("completeness")),
        mapped_read_fraction=_typed_float(mapping_values.get("mapped_read_fraction")),
        mapping_input_read_count=_typed_int(mapping_values.get("input_read_count")),
        mapping_retained_read_count=_typed_int(mapping_values.get("retained_read_count")),
        mapping_retained_read_fraction=_typed_float(mapping_values.get("retained_read_fraction")),
        coverage_mean=_typed_float(mapping_values.get("mean")),
        coverage_median=_typed_float(mapping_values.get("median")),
        coverage_cv=_typed_float(mapping_values.get("cv")),
        low_coverage_window_fraction=_typed_float(mapping_values.get("low_window_fraction")),
        high_coverage_window_fraction=_typed_float(mapping_values.get("high_window_fraction")),
        assembly_size_ratio=assembly_size_ratio,
        tool_failures=tool_failures,
        metric_limitations=limitations,
        metric_classes={
            "assembly_size": "fact",
            "contig_count": "fact",
            "contig_n50": "fact",
            "contig_l50": "fact",
            "longest_contig": "fact",
            "quast_misassemblies": "fact",
            "quast_local_misassemblies": "fact",
            "genome_fraction": "derived",
            "duplication_ratio": "derived",
            "busco_complete": "derived",
            "busco_single": "derived",
            "busco_duplicated": "derived",
            "busco_fragmented": "derived",
            "busco_missing": "derived",
            "kmer_qv": "derived",
            "kmer_completeness": "derived",
            "mapped_read_fraction": "derived",
            "mapping_input_read_count": "fact",
            "mapping_retained_read_count": "fact",
            "mapping_retained_read_fraction": "derived",
            "coverage_mean": "derived",
            "coverage_median": "derived",
            "coverage_cv": "derived",
            "low_coverage_window_fraction": "derived",
            "high_coverage_window_fraction": "derived",
            "assembly_size_ratio": "derived",
        },
        tool_versions={
            "quast": _optional_string(quast.get("version")),
            "busco": _optional_string(busco.get("version")),
            "merqury": _optional_string(merqury.get("version")),
            "minimap2": _optional_string(_nested_dict(mapping, "versions").get("minimap2")),
            "samtools": _optional_string(_nested_dict(mapping, "versions").get("samtools")),
            "coverage": _optional_string(_nested_dict(mapping, "versions").get("coverage")),
        },
        tool_metadata={
            "busco": {
                "requested_lineage": busco.get("requested_lineage"),
                "actual_lineage": busco.get("lineage"),
                "lineage_selection": busco.get("lineage_selection"),
                "dataset": busco.get("dataset"),
            },
            "merqury": {"kmer_source": merqury.get("kmer_source")},
            "mapping_filter": mapping.get("filter"),
        },
        source_files={
            "quast": "quast/quast_metrics.json",
            "busco": "busco/busco_metrics.json",
            "merqury": "merqury/merqury_metrics.json",
            "mapping": "mapping/mapping_metrics.json",
        },
    )
    _write_json(args.output, metrics.model_dump(mode="json"))


def _relative_files(base_dir: Path, subdir: str, pattern: str) -> list[str]:
    root = base_dir.parent / subdir
    return [str(path.relative_to(base_dir.parent)) for path in sorted(root.glob(pattern))]


def _count_reused_bins(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(
        1
        for line in path.read_text(errors="replace").splitlines()[1:]
        if line.rstrip().endswith("\treused")
    )


def _write_key_value_table(path: Path, rows: Mapping[str, object]) -> None:
    with path.open("w") as handle:
        handle.write("key\tvalue\n")
        for key, value in rows.items():
            handle.write(f"{key}\t{_format_optional(value)}\n")


def _format_optional(value: object) -> str:
    return "null" if value is None else str(value)


def _optional_int(value: str) -> int | None:
    normalized = str(value).strip().lower()
    if normalized in {"", "none", "null", "true", "false"}:
        return None
    return int(normalized)


def _select_genome_size_for_coverage(
    expected_genome_size: int | None,
    kmer_metrics: dict[str, object],
) -> tuple[int | None, str | None]:
    if expected_genome_size is not None:
        return expected_genome_size, "expected_genome_size"

    genomescope_genome_size = kmer_metrics.get("genomescope_genome_size")
    if isinstance(genomescope_genome_size, int):
        return genomescope_genome_size, "genomescope"
    if isinstance(genomescope_genome_size, float) and genomescope_genome_size > 0:
        return round(genomescope_genome_size), "genomescope"
    return None, None


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0:
        return round(value)
    return None


def _first_line(path: Path) -> str | None:
    if not path.is_file():
        return None
    lines = path.read_text(errors="replace").splitlines()
    return lines[0].strip() if lines else None


def _nested_dict(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _typed_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _typed_float(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _read_json(path: Path) -> dict[str, object]:
    with path.open() as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Expected object JSON in {path}")
    return data


def _write_json(path: Path, data: dict[str, object]) -> None:
    with path.open("w") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _validate_raw_metric_types(data: dict[str, object], seqkit: SeqkitStats) -> None:
    integer_fields = ("read_count", "total_bases")
    for field in integer_fields:
        if not isinstance(data[field], int):
            raise TypeError(f"{field} must be int")
    if seqkit.mean_qscore is None and data["mean_qscore"] is not None:
        raise TypeError("mean_qscore must be null when unavailable")


if __name__ == "__main__":
    main()
