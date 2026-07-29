"""Nextflow execution wrapper for validated workflow runs."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from hifi_agent.agent.models import AssemblyConfig
from hifi_agent.config import verify_recorded_input_checksums, verify_validation_receipt
from hifi_agent.exceptions import ToolExecutionError
from hifi_agent.executors.hifiasm_contract import write_hifiasm_contract_artifacts
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
            "--kmer_k",
            str(config.kmer.k),
            "--kmer_low_coverage_peak_threshold",
            str(config.kmer.low_coverage_peak_threshold),
            "--kmer_reads_manifest",
            str(kmer_reads_manifest),
            "--kmer_source",
            kmer_source,
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
    _append_optional_nextflow_param(
        command,
        "--expected_genome_size",
        config.expected_genome_size,
    )
    _append_optional_nextflow_param(command, "--reference_genome", config.reference_genome)
    _append_optional_nextflow_param(command, "--busco_lineage", config.busco_lineage)

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
    _append_optional_nextflow_param(
        command,
        "--expected_genome_size",
        config.expected_genome_size,
    )
    _append_optional_nextflow_param(command, "--reference_genome", config.reference_genome)
    _append_optional_nextflow_param(command, "--busco_lineage", config.busco_lineage)
    try:
        subprocess.run(command, cwd=PROJECT_ROOT, env=_nextflow_environment(), check=True)
    except subprocess.CalledProcessError as exc:
        raise ToolExecutionError(
            f"Post-QC workflow failed with exit code {exc.returncode}: {' '.join(command)}"
        ) from exc
    return NextflowRunResult(tuple(command), run_dir, reads_manifest)


def run_candidate_workflow(
    run_dir: Path,
    candidate: AssemblyConfig,
    *,
    resume: bool = True,
) -> NextflowRunResult:
    """Run one whitelisted candidate plus the identical Stage 7 post-QC process set."""
    resolved_run = run_dir.resolve()
    if candidate.run_id == "baseline" or candidate.retry_kind != "PARAMETER_OPTIMIZATION":
        raise ToolExecutionError("Candidate workflow requires a non-baseline optimization config")
    resolved_config = resolved_run / "00_metadata/resolved_config.yaml"
    validation_receipt = resolved_run / "00_metadata/validation_receipt.json"
    reads_manifest = resolved_run / "00_metadata/hifi_reads.list"
    raw_metrics = resolved_run / "01_pre_qc/raw_metrics.json"
    meryl_db = resolved_run / "01_pre_qc/kmer/read.meryl"
    kmer_histogram = resolved_run / "01_pre_qc/kmer/kmer_histogram.tsv"
    baseline_bins = resolved_run / "02_assembly/baseline/bins"
    required = (
        resolved_config,
        validation_receipt,
        reads_manifest,
        raw_metrics,
        meryl_db,
        baseline_bins,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ToolExecutionError(f"Candidate workflow input(s) missing: {', '.join(missing)}")
    raw_config = yaml.safe_load(resolved_config.read_text())
    if not isinstance(raw_config, dict):
        raise ToolExecutionError(f"Resolved config is not a YAML mapping: {resolved_config}")
    config = SampleConfig.model_validate(raw_config)
    verify_validation_receipt(config, validation_receipt)
    verify_recorded_input_checksums(resolved_run / "00_metadata/input_checksums.tsv")
    if candidate.threads > config.resources.max_threads:
        raise ToolExecutionError("Candidate threads exceed validated resource limits")
    if candidate.input_reads != config.hifi_reads:
        raise ToolExecutionError("Candidate reads differ from the validated baseline inputs")

    reuse_manifest = _write_hifiasm_bin_reuse_manifest(
        resolved_run / "00_metadata" / f"{candidate.run_id}_bin_reuse.tsv",
        baseline_bins,
        f"{config.sample_id}.baseline",
    )
    if len(reuse_manifest.read_text().splitlines()) <= 1:
        raise ToolExecutionError("No compatible baseline hifiasm .bin files are available")
    candidate_metadata = resolved_run / "02_assembly" / candidate.run_id / "metadata"
    write_hifiasm_contract_artifacts(candidate, candidate_metadata)

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
        "CANDIDATE_ONLY",
    ]
    if resume:
        command.append("-resume")
    parameters = candidate.parameters
    command.extend(
        [
            "--sample_id",
            config.sample_id,
            "--assembly_run_id",
            candidate.run_id,
            "--hifiasm_purge_level",
            str(parameters.purge_level),
            "--hifiasm_purge_similarity",
            str(parameters.purge_similarity),
            "--hifiasm_disable_post_join",
            str(parameters.disable_post_join).lower(),
            "--reads_manifest",
            str(reads_manifest),
            "--raw_metrics",
            str(raw_metrics),
            "--bin_reuse_manifest",
            str(reuse_manifest),
            "--meryl_db",
            str(meryl_db),
            "--kmer_histogram",
            str(kmer_histogram),
            "--kmer_source",
            kmer_source,
            "--outdir",
            str(resolved_run),
            "--validation_receipt",
            str(validation_receipt),
            "--mapping_min_read_length",
            str(config.mapping_qc.min_read_length),
            "--mapping_min_mean_qscore",
            str(config.mapping_qc.min_mean_qscore),
            "--coverage_window_size",
            str(config.mapping_qc.coverage_window_size),
            "--max_threads",
            str(min(candidate.threads, config.resources.max_threads)),
            "--max_memory_gb",
            str(config.resources.max_memory_gb),
        ]
    )
    _append_optional_nextflow_param(
        command,
        "--expected_genome_size",
        config.expected_genome_size,
    )
    _append_optional_nextflow_param(command, "--hifiasm_hom_cov", parameters.hom_cov)
    _append_optional_nextflow_param(command, "--reference_genome", config.reference_genome)
    _append_optional_nextflow_param(command, "--busco_lineage", config.busco_lineage)
    try:
        subprocess.run(command, cwd=PROJECT_ROOT, env=_nextflow_environment(), check=True)
    except subprocess.CalledProcessError as exc:
        raise ToolExecutionError(
            f"Candidate workflow failed with exit code {exc.returncode}: {' '.join(command)}"
        ) from exc
    expected = (
        resolved_run / f"02_assembly/{candidate.run_id}/metadata/assembly_manifest.json",
        resolved_run / f"02_assembly/{candidate.run_id}/fasta/{candidate.run_id}.primary.fa",
        resolved_run / f"03_post_qc/{candidate.run_id}/assembly_metrics.json",
    )
    missing_outputs = [str(path) for path in expected if not path.is_file()]
    if missing_outputs:
        raise ToolExecutionError(
            f"Candidate workflow completed without required output(s): {', '.join(missing_outputs)}"
        )
    command_path = candidate_metadata / "hifiasm_command.txt"
    write_hifiasm_contract_artifacts(
        candidate,
        candidate_metadata,
        command_path=command_path,
    )
    return NextflowRunResult(tuple(command), resolved_run, reads_manifest)


def _find_nextflow() -> str:
    nextflow = shutil.which("nextflow")
    if nextflow is not None:
        return nextflow

    local_nextflow = Path("/home/gw/software/nextflow")
    if local_nextflow.is_file():
        return str(local_nextflow)

    raise ToolExecutionError("Nextflow executable was not found on PATH.")


def _append_optional_nextflow_param(
    command: list[str],
    name: str,
    value: object | None,
) -> None:
    """Append a Nextflow parameter only when it has a real value.

    Passing a bare Nextflow flag without a value is interpreted as boolean true,
    which is not equivalent to a missing optional numeric parameter.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return
    command.extend([name, str(value)])


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
