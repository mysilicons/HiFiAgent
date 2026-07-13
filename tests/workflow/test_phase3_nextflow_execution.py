import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_JAVA_HOME = Path("/home/gw/software/jdk21")
LOCAL_JAVA_CMD = LOCAL_JAVA_HOME / "bin" / "java"


def test_phase3_nextflow_smoke_execution(tmp_path: Path) -> None:
    nextflow = shutil.which("nextflow") or "/home/gw/software/nextflow"
    if not Path(nextflow).exists():
        pytest.skip("Nextflow is not installed in this environment.")
    if not LOCAL_JAVA_CMD.exists():
        pytest.skip("Java 21 is not available in this environment.")

    reads = tmp_path / "reads.fastq"
    reads.write_text(
        "@read1\nACGTACGTACGTACGTACGTACGTACGTACGT\n+\nIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII\n"
    )
    reads_manifest = tmp_path / "reads.list"
    reads_manifest.write_text(f"{reads}\n")
    outdir = tmp_path / "out"

    env = os.environ.copy()
    env["JAVA_HOME"] = str(LOCAL_JAVA_HOME)
    env["JAVA_CMD"] = str(LOCAL_JAVA_CMD)

    command = [
        nextflow,
        "run",
        str(PROJECT_ROOT / "workflow" / "main.nf"),
        "-c",
        str(PROJECT_ROOT / "workflow" / "nextflow.config"),
        "-profile",
        "local",
        "--sample_id",
        "tiny_sample",
        "--reads_manifest",
        str(reads_manifest),
        "--outdir",
        str(outdir),
        "--expected_genome_size",
        "100",
        "--run_assembly",
        "false",
    ]

    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)

    assert (outdir / "00_metadata" / "run_manifest.json").is_file()
    assert (outdir / "01_pre_qc" / "fastq_probe" / "fastq_probe.tsv").is_file()
    assert (outdir / "01_pre_qc" / "seqkit" / "seqkit_stats.tsv").is_file()
    assert (outdir / "01_pre_qc" / "nanoplot" / "NanoStats.txt").is_file()
    assert (outdir / "01_pre_qc" / "kmer" / "kmer_histogram.tsv").is_file()
    assert (outdir / "01_pre_qc" / "kmer" / "kmer_metrics.json").is_file()
    assert (outdir / "01_pre_qc" / "raw_metrics.json").is_file()
    assert (outdir / "logs" / "trace.txt").is_file()
    assert (outdir / "logs" / "timeline.html").is_file()
    assert (outdir / "logs" / "report.html").is_file()
    assert (outdir / "logs" / "dag.html").is_file()
