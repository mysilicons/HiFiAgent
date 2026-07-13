"""Nextflow execution wrapper for validated workflow runs."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from hifi_agent.config import verify_recorded_input_checksums, verify_validation_receipt
from hifi_agent.exceptions import ToolExecutionError
from hifi_agent.schemas.sample import SampleConfig

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_ENTRY = PROJECT_ROOT / "workflow" / "main.nf"
WORKFLOW_CONFIG = PROJECT_ROOT / "workflow" / "nextflow.config"
LOCAL_JAVA_HOME = Path("/home/gw/software/jdk21")
LOCAL_JAVA_CMD = LOCAL_JAVA_HOME / "bin" / "java"


@dataclass(frozen=True)
class NextflowRunResult:
    """Metadata for a submitted Nextflow workflow run."""

    command: tuple[str, ...]
    outdir: Path
    reads_manifest: Path


def run_phase3_workflow(config: SampleConfig, *, resume: bool = False) -> NextflowRunResult:
    """Run the validated Nextflow workflow through assembly and post-QC."""
    nextflow = _find_nextflow()
    reads_manifest = _write_path_manifest(
        config.outdir / "00_metadata" / "hifi_reads.list", config.hifi_reads
    )
    kmer_paths = config.kmer_reads or config.hifi_reads
    kmer_reads_manifest = _write_path_manifest(
        config.outdir / "00_metadata" / "kmer_reads.list", kmer_paths
    )
    kmer_source = "independent_high_confidence" if config.kmer_reads else "same_data_advisory"
    validation_receipt = config.outdir / "00_metadata" / "validation_receipt.json"
    verify_validation_receipt(config, validation_receipt)
    bin_reuse_manifest = _write_hifiasm_bin_reuse_manifest(
        config.outdir / "00_metadata" / "hifiasm_bin_reuse_candidates.tsv",
        config.outdir / "02_assembly" / "baseline" / "bins",
        f"{config.sample_id}.baseline",
    )

    command = [
        nextflow,
        "run",
        str(WORKFLOW_ENTRY),
        "-c",
        str(WORKFLOW_CONFIG),
        "-profile",
        "local",
    ]
    if resume:
        command.append("-resume")

    command.extend(
        [
            "--sample_id",
            config.sample_id,
            "--reads_manifest",
            str(reads_manifest),
            "--outdir",
            str(config.outdir),
            "--validation_receipt",
            str(validation_receipt),
            "--bin_reuse_manifest",
            str(bin_reuse_manifest),
            "--expected_genome_size",
            str(config.expected_genome_size or ""),
            "--kmer_k",
            str(config.kmer.k),
            "--kmer_low_coverage_peak_threshold",
            str(config.kmer.low_coverage_peak_threshold),
            "--kmer_reads_manifest",
            str(kmer_reads_manifest),
            "--kmer_source",
            kmer_source,
            "--reference_genome",
            str(config.reference_genome or ""),
            "--busco_lineage",
            config.busco_lineage or "",
            "--mapping_min_read_length",
            str(config.mapping_qc.min_read_length),
            "--mapping_min_mean_qscore",
            str(config.mapping_qc.min_mean_qscore),
            "--coverage_window_size",
            str(config.mapping_qc.coverage_window_size),
            "--max_threads",
            str(config.resources.max_threads),
            "--max_memory_gb",
            str(config.resources.max_memory_gb),
        ]
    )

    try:
        subprocess.run(command, cwd=PROJECT_ROOT, env=_nextflow_environment(), check=True)
    except subprocess.CalledProcessError as exc:
        raise ToolExecutionError(
            f"Nextflow workflow failed with exit code {exc.returncode}: {' '.join(command)}"
        ) from exc

    return NextflowRunResult(
        command=tuple(command),
        outdir=config.outdir,
        reads_manifest=reads_manifest,
    )


def run_post_qc_workflow(run_dir: Path, *, resume: bool = True) -> NextflowRunResult:
    """Evaluate an existing baseline assembly without rerunning pre-QC or hifiasm."""
    resolved_config = run_dir / "00_metadata" / "resolved_config.yaml"
    reads_manifest = run_dir / "00_metadata" / "hifi_reads.list"
    assembly_fasta = run_dir / "02_assembly" / "baseline" / "fasta" / "baseline.primary.fa"
    assembly_manifest = run_dir / "02_assembly" / "baseline" / "metadata" / "assembly_manifest.json"
    meryl_db = run_dir / "01_pre_qc" / "kmer" / "read.meryl"
    kmer_histogram = run_dir / "01_pre_qc" / "kmer" / "kmer_histogram.tsv"
    validation_receipt = run_dir / "00_metadata" / "validation_receipt.json"
    required = (
        resolved_config,
        validation_receipt,
        reads_manifest,
        assembly_fasta,
        assembly_manifest,
        meryl_db,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ToolExecutionError(f"Post-QC input(s) missing: {', '.join(missing)}")

    raw_config = yaml.safe_load(resolved_config.read_text())
    if not isinstance(raw_config, dict):
        raise ToolExecutionError(f"Resolved config is not a YAML mapping: {resolved_config}")
    config = SampleConfig.model_validate(raw_config)
    verify_validation_receipt(config, validation_receipt)
    verify_recorded_input_checksums(run_dir / "00_metadata" / "input_checksums.tsv")
    nextflow = _find_nextflow()
    kmer_source = "independent_high_confidence" if config.kmer_reads else "same_data_advisory"
    command = [
        nextflow,
        "run",
        str(WORKFLOW_ENTRY),
        "-c",
        str(WORKFLOW_CONFIG),
        "-profile",
        "local",
        "-entry",
        "POST_QC_ONLY",
    ]
    if resume:
        command.append("-resume")
    command.extend(
        [
            "--sample_id",
            config.sample_id,
            "--reads_manifest",
            str(reads_manifest),
            "--kmer_source",
            kmer_source,
            "--outdir",
            str(run_dir),
            "--validation_receipt",
            str(validation_receipt),
            "--expected_genome_size",
            str(config.expected_genome_size or ""),
            "--reference_genome",
            str(config.reference_genome or ""),
            "--busco_lineage",
            config.busco_lineage or "",
            "--mapping_min_read_length",
            str(config.mapping_qc.min_read_length),
            "--mapping_min_mean_qscore",
            str(config.mapping_qc.min_mean_qscore),
            "--coverage_window_size",
            str(config.mapping_qc.coverage_window_size),
            "--max_threads",
            str(config.resources.max_threads),
            "--max_memory_gb",
            str(config.resources.max_memory_gb),
            "--assembly_fasta",
            str(assembly_fasta),
            "--assembly_manifest",
            str(assembly_manifest),
            "--meryl_db",
            str(meryl_db),
            "--kmer_histogram",
            str(kmer_histogram),
        ]
    )
    try:
        subprocess.run(command, cwd=PROJECT_ROOT, env=_nextflow_environment(), check=True)
    except subprocess.CalledProcessError as exc:
        raise ToolExecutionError(
            f"Post-QC workflow failed with exit code {exc.returncode}: {' '.join(command)}"
        ) from exc
    return NextflowRunResult(tuple(command), run_dir, reads_manifest)


def _find_nextflow() -> str:
    nextflow = shutil.which("nextflow")
    if nextflow is not None:
        return nextflow

    local_nextflow = Path("/home/gw/software/nextflow")
    if local_nextflow.is_file():
        return str(local_nextflow)

    raise ToolExecutionError("Nextflow executable was not found on PATH.")


def _write_path_manifest(output: Path, paths: list[Path]) -> Path:
    """Write one absolute input path per line for Nextflow staging."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as handle:
        for read_path in paths:
            handle.write(str(read_path))
            handle.write("\n")
    return output


def _write_hifiasm_bin_reuse_manifest(
    output: Path,
    published_bins: Path,
    prefix: str,
) -> Path:
    """Record compatible same-prefix hifiasm bins as declared workflow input."""
    output.parent.mkdir(parents=True, exist_ok=True)
    candidates = sorted(published_bins.glob(f"{prefix}*.bin")) if published_bins.is_dir() else []
    with output.open("w") as handle:
        handle.write("path\tsha256\tbytes\n")
        for candidate in candidates:
            digest = hashlib.sha256()
            with candidate.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            handle.write(
                f"{candidate.resolve()}\t{digest.hexdigest()}\t{candidate.stat().st_size}\n"
            )
    return output


def _nextflow_environment() -> dict[str, str]:
    env = os.environ.copy()
    if LOCAL_JAVA_CMD.is_file():
        env["JAVA_HOME"] = str(LOCAL_JAVA_HOME)
        env["JAVA_CMD"] = str(LOCAL_JAVA_CMD)
    return env
