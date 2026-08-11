#!/usr/bin/env python3
"""Executable portable toolchain used across real subprocess/file boundaries."""

from __future__ import annotations

import json
import sys
from pathlib import Path

VERSIONS = {
    "java": 'openjdk version "21.0.6"',
    "nextflow": "nextflow version 25.04.7 build 5940",
    "hifiasm": "hifiasm 0.25.0-r726",
    "gfatools": "gfatools 0.5",
    "seqkit": "seqkit 2.10.1",
    "NanoPlot": "NanoPlot 1.47.1",
    "meryl": "meryl 1.3",
    "quast.py": "QUAST v5.3.0",
    "busco": "BUSCO 6.0.0",
    "merqury.sh": "Merqury 1.3",
    "minimap2": "2.30-r1287",
    "samtools": "samtools 1.22.1",
    "Rscript": "R scripting front-end version 4.4.2",
    "genomescope2": "GenomeScope 2.0",
    "bedtools": "bedtools 2.31.1",
}


def _value(arguments: list[str], option: str) -> str:
    try:
        return arguments[arguments.index(option) + 1]
    except (ValueError, IndexError) as exc:
        raise SystemExit(f"portable fixture missing required option {option}") from exc


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _run_pre_qc(arguments: list[str]) -> int:
    run_dir = Path(_value(arguments, "--outdir"))
    raw = run_dir / "01_pre_qc/raw_metrics.json"
    meryl = run_dir / "01_pre_qc/kmer/read.meryl"
    histogram = run_dir / "01_pre_qc/kmer/kmer_histogram.tsv"
    _write_json(
        raw,
        {
            "schema_id": "hifi-agent",
            "sample_id": _value(arguments, "--sample_id"),
            "read_count": 1,
            "read_bases": 8,
            "kmer_source": "same_data_advisory",
        },
    )
    meryl.mkdir(parents=True, exist_ok=True)
    (meryl / "fixture.meryl").write_text("portable-meryl-db\n")
    histogram.parent.mkdir(parents=True, exist_ok=True)
    histogram.write_text("coverage\tfrequency\n1\t1\n")
    return 0


def _round_number(run_id: str) -> int:
    if not run_id.startswith("round_"):
        return 0
    try:
        return int(run_id.split("_")[1])
    except (IndexError, ValueError):
        return 0


def _run_assembly(arguments: list[str]) -> int:
    sample_id = _value(arguments, "--sample_id")
    run_id = _value(arguments, "--assembly_run_id")
    assembly_root = Path(_value(arguments, "--assembly_publish_dir"))
    post_qc_root = Path(_value(arguments, "--post_qc_publish_dir"))
    workflow_root = Path(_value(arguments, "--outdir"))

    if sample_id == "fixture-tool-failure" and run_id == "baseline":
        return 2
    if sample_id == "fixture-resume" and run_id == "round_02_candidate_01":
        marker = workflow_root / ".portable_interrupted_once"
        if "-resume" not in arguments and not marker.exists():
            cache = workflow_root / ".nextflow/cache"
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "fixture-session").write_text("resume-evidence\n")
            marker.write_text("exit-143\n")
            return 143

    reads = [
        line
        for line in Path(_value(arguments, "--reads_manifest")).read_text().splitlines()
        if line
    ]
    purge_level = _value(arguments, "--hifiasm_purge_level")
    purge_similarity = _value(arguments, "--hifiasm_purge_similarity")
    threads = _value(arguments, "--max_threads")
    command = [
        "hifiasm",
        "-o",
        f"fixture.{run_id}",
        "-t",
        threads,
        "-l",
        purge_level,
        "-s",
        purge_similarity,
    ]
    if "--hifiasm_hom_cov" in arguments:
        command.extend(["--hom-cov", _value(arguments, "--hifiasm_hom_cov")])
    if _value(arguments, "--hifiasm_disable_post_join") == "true":
        command.append("-u0")
    command.extend(reads)

    metadata = assembly_root / "metadata"
    fasta = assembly_root / f"fasta/{run_id}.primary.fa"
    metadata.mkdir(parents=True, exist_ok=True)
    fasta.parent.mkdir(parents=True, exist_ok=True)
    (metadata / "hifiasm_command.txt").write_text(" ".join(command) + "\n")
    (metadata / "hifiasm.version.txt").write_text(VERSIONS["hifiasm"] + "\n")
    (metadata / "gfatools.version.txt").write_text(VERSIONS["gfatools"] + "\n")
    _write_json(metadata / "assembly_manifest.json", {"cpu_seconds": 3.6, "peak_rss_gb": 0.01})
    fasta.write_text(">portable_contig\nACGTACGT\n")

    round_index = _round_number(run_id)
    busco_complete = 94.0 + (1.5 * round_index)
    contig_n50 = 1_000
    if sample_id == "fixture-human-review" and run_id == "round_01_candidate_02":
        busco_complete = 94.0
        contig_n50 = 1_200
    metrics = {
        "schema_id": "hifi-agent",
        "run_id": run_id,
        "assembly_size": 10_000,
        "contig_count": 10,
        "contig_n50": contig_n50,
        "busco_complete": busco_complete,
        "busco_duplicated": 8.0,
        "kmer_completeness": 96.0,
        "kmer_qv": 40.0,
        "mapped_read_fraction": 0.99,
        "coverage_mean": 30.0,
        "coverage_cv": 0.20,
        "tool_versions": {"fixture": "hifi-agent"},
        "source_files": {"portable_fixture": "generated"},
    }
    _write_json(post_qc_root / "assembly_metrics.json", metrics)
    (workflow_root / "logs").mkdir(parents=True, exist_ok=True)
    (workflow_root / "logs/portable-nextflow.log").write_text(f"completed {run_id}\n")
    return 0


def main() -> int:
    tool = Path(sys.argv[0]).name
    arguments = sys.argv[1:]
    if tool != "nextflow" or not arguments or arguments[0] != "run":
        print(VERSIONS.get(tool, f"{tool} portable fixture 3.0"))
        return 0
    if "-entry" in arguments and _value(arguments, "-entry") == "ASSEMBLY_ATTEMPT":
        return _run_assembly(arguments)
    return _run_pre_qc(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
