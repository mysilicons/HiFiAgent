"""Production Nextflow runner for the common assembly-attempt port."""

from __future__ import annotations

import json
import shlex
import signal
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from hifi_agent.config import verify_recorded_input_checksums, verify_validation_receipt
from hifi_agent.exceptions import InterruptedExecutionError, ToolExecutionError
from hifi_agent.executors.models import (
    ArtifactInventory,
    ArtifactInventoryEntry,
    AssemblyInputManifest,
    InputArtifact,
    WorkflowInvocation,
    WorkflowResult,
)
from hifi_agent.orchestration.manifests import ResourceUsage
from hifi_agent.orchestration.runtime_models import sha256_file
from hifi_agent.schemas.sample import SampleConfig
from hifi_agent.tool_resolution import declared_subprocess_environment, resolve_configured_tool

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_ENTRY = PROJECT_ROOT / "workflow/main.nf"
WORKFLOW_CONFIG = PROJECT_ROOT / "workflow/nextflow.config"
CommandRunner = Callable[[list[str], Path, dict[str, str]], None]


def run_pre_qc_workflow(
    sample: SampleConfig,
    *,
    resume: bool = False,
    command_runner: CommandRunner | None = None,
) -> AssemblyInputManifest:
    """Materialize run-level pre-QC and return a checksum-bound assembly input manifest."""
    run_dir = sample.outdir.resolve()
    inventory_path = run_dir / "01_pre_qc/artifacts_manifest.json"
    if resume and inventory_path.is_file():
        _verify_pre_qc_inventory(run_dir, inventory_path)
        return assembly_inputs_from_run(run_dir)
    metadata = run_dir / "00_metadata"
    reads_manifest = metadata / "hifi_reads.list"
    kmer_manifest = metadata / "kmer_reads.list"
    _write_or_verify_lines(reads_manifest, sample.hifi_reads)
    _write_or_verify_lines(kmer_manifest, sample.kmer_reads or sample.hifi_reads)
    validation_receipt = metadata / "validation_receipt.json"
    verify_validation_receipt(sample, validation_receipt)
    nextflow = resolve_configured_tool("nextflow", "nextflow", sample)
    if nextflow is None:
        raise ToolExecutionError("Nextflow executable was not resolved by current preflight")
    pre_qc_root = run_dir / "01_pre_qc"
    pre_qc_root.mkdir(parents=True, exist_ok=True)
    work_root = pre_qc_root / "work"
    command = [
        str(nextflow),
        "run",
        str(WORKFLOW_ENTRY),
        "-c",
        str(WORKFLOW_CONFIG),
        "-profile",
        "local",
        "-work-dir",
        str(work_root),
    ]
    if resume:
        command.append("-resume")
    command.extend(
        [
            "--sample_id",
            sample.sample_id,
            "--reads_manifest",
            str(reads_manifest),
            "--kmer_reads_manifest",
            str(kmer_manifest),
            "--kmer_source",
            "independent_high_confidence" if sample.kmer_reads else "same_data_advisory",
            "--outdir",
            str(run_dir),
            "--validation_receipt",
            str(validation_receipt),
            "--kmer_k",
            str(sample.kmer.k),
            "--kmer_low_coverage_peak_threshold",
            str(sample.kmer.low_coverage_peak_threshold),
            "--max_threads",
            str(sample.resources.max_threads),
            "--max_memory_gb",
            str(sample.resources.max_memory_gb),
        ]
    )
    _append_optional(command, "--expected_genome_size", sample.expected_genome_size)
    (command_runner or _run_command)(
        command,
        pre_qc_root,
        declared_subprocess_environment(sample),
    )
    required = (
        run_dir / "01_pre_qc/raw_metrics.json",
        run_dir / "01_pre_qc/kmer/read.meryl",
        run_dir / "01_pre_qc/kmer/kmer_histogram.tsv",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ToolExecutionError(
            "Pre-QC completed without required artifact(s): " + ", ".join(missing)
        )
    entries = []
    for path in sorted((run_dir / "01_pre_qc").rglob("*")):
        relative_pre_qc = path.relative_to(run_dir / "01_pre_qc")
        if (
            not path.is_file()
            or relative_pre_qc.is_relative_to(Path("work"))
            or path == inventory_path
        ):
            continue
        relative = path.relative_to(run_dir)
        stat = path.stat()
        entries.append(
            ArtifactInventoryEntry(
                relative_path=relative,
                bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                sha256=sha256_file(path),
            )
        )
    inventory = ArtifactInventory(
        attempt_id="pre_qc",
        created_at=datetime.now(UTC),
        entries=tuple(entries),
    )
    inventory_path.write_text(inventory.model_dump_json(indent=2) + "\n")
    return assembly_inputs_from_run(run_dir)


def assembly_inputs_from_run(run_dir: Path) -> AssemblyInputManifest:
    """Create explicit named inputs after verifying the pre-QC inventory."""
    root = run_dir.resolve()
    paths = {
        "resolved_config": root / "00_metadata/resolved_config.yaml",
        "validation_receipt": root / "00_metadata/validation_receipt.json",
        "input_checksums": root / "00_metadata/input_checksums.tsv",
        "reads_manifest": root / "00_metadata/hifi_reads.list",
        "raw_metrics": root / "01_pre_qc/raw_metrics.json",
        "meryl_db": root / "01_pre_qc/kmer/read.meryl",
        "kmer_histogram": root / "01_pre_qc/kmer/kmer_histogram.tsv",
        "pre_qc_inventory": root / "01_pre_qc/artifacts_manifest.json",
    }
    return AssemblyInputManifest(
        artifacts={role: InputArtifact.from_path(path) for role, path in paths.items()}
    )


class NextflowAssemblyRunner:
    """Execute baseline or candidate through the exact same Nextflow entry."""

    def __init__(self, *, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_command

    def run(self, invocation: WorkflowInvocation) -> WorkflowResult:
        """Run assembly and post-QC with publish/work/cache below the attempt root."""
        sample = invocation.sample
        try:
            resolved_config = invocation.inputs.require("resolved_config")
            validation_receipt = invocation.inputs.require("validation_receipt")
            input_checksums = invocation.inputs.require("input_checksums")
            reads_manifest = invocation.inputs.require("reads_manifest")
            raw_metrics = invocation.inputs.require("raw_metrics")
            meryl_db = invocation.inputs.require("meryl_db")
            kmer_histogram = invocation.inputs.require("kmer_histogram")
        except ValueError as exc:
            raise ToolExecutionError(str(exc)) from exc
        if resolved_config != sample.outdir / "00_metadata/resolved_config.yaml":
            raise ToolExecutionError("Resolved config role does not match the current run root")
        verify_validation_receipt(sample, validation_receipt)
        verify_recorded_input_checksums(input_checksums)

        attempt_root = invocation.attempt_root.resolve()
        workflow_root = attempt_root / "workflow"
        assembly_root = attempt_root / "assembly"
        post_qc_root = attempt_root / "post_qc"
        work_root = workflow_root / "work"
        for path in (workflow_root, assembly_root, post_qc_root, work_root):
            path.mkdir(parents=True, exist_ok=True)
        if invocation.resume:
            cache_root = workflow_root / ".nextflow/cache"
            if not cache_root.is_dir() or not any(cache_root.iterdir()):
                raise InterruptedExecutionError(
                    "Interrupted attempt cannot resume because its Nextflow cache is missing"
                )
        nextflow = resolve_configured_tool("nextflow", "nextflow", sample)
        if nextflow is None:
            raise ToolExecutionError("Nextflow executable was not resolved by current preflight")
        parameters = invocation.approved_config.parameters
        command = [
            str(nextflow),
            "run",
            str(WORKFLOW_ENTRY),
            "-c",
            str(WORKFLOW_CONFIG),
            "-profile",
            "local",
            "-entry",
            "ASSEMBLY_ATTEMPT",
            "-work-dir",
            str(work_root),
        ]
        if invocation.resume:
            command.append("-resume")
        command.extend(
            [
                "--sample_id",
                sample.sample_id,
                "--assembly_run_id",
                invocation.coordinate.logical_run_id,
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
                "--meryl_db",
                str(meryl_db),
                "--kmer_histogram",
                str(kmer_histogram),
                "--kmer_source",
                invocation.post_qc_contract.kmer_source,
                "--outdir",
                str(workflow_root),
                "--assembly_publish_dir",
                str(assembly_root),
                "--post_qc_publish_dir",
                str(post_qc_root),
                "--validation_receipt",
                str(validation_receipt),
                "--mapping_min_read_length",
                str(invocation.post_qc_contract.mapping_min_read_length),
                "--mapping_min_mean_qscore",
                str(invocation.post_qc_contract.mapping_min_mean_qscore),
                "--coverage_window_size",
                str(invocation.post_qc_contract.coverage_window_size),
                "--max_threads",
                str(invocation.approved_config.threads),
                "--max_memory_gb",
                str(sample.resources.max_memory_gb),
            ]
        )
        _append_optional(command, "--expected_genome_size", sample.expected_genome_size)
        _append_optional(command, "--hifiasm_hom_cov", parameters.hom_cov)
        _append_optional(command, "--reference_genome", sample.reference_genome)
        _append_optional(command, "--busco_lineage", sample.busco_lineage)
        if sample.tools.busco_lineage_dir is not None:
            _append_optional(command, "--busco_download_path", sample.tools.busco_lineage_dir)

        started = time.monotonic()
        self.command_runner(command, workflow_root, declared_subprocess_environment(sample))
        elapsed_hours = (time.monotonic() - started) / 3600
        command_path = assembly_root / "metadata/hifiasm_command.txt"
        metrics_path = post_qc_root / "assembly_metrics.json"
        primary_path = assembly_root / f"fasta/{invocation.coordinate.logical_run_id}.primary.fa"
        required = (command_path, metrics_path, primary_path)
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise ToolExecutionError(
                "Nextflow attempt completed without required artifact(s): " + ", ".join(missing)
            )
        try:
            realized = tuple(shlex.split(command_path.read_text()))
        except ValueError as exc:
            raise ToolExecutionError("Recorded hifiasm command is not valid argv") from exc
        artifacts = tuple(
            path
            for root in (assembly_root, post_qc_root, workflow_root / "logs")
            if root.exists()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        )
        return WorkflowResult(
            command=tuple(command),
            realized_hifiasm_argv=realized,
            artifacts=artifacts,
            tool_versions=_read_tool_versions(assembly_root),
            resource_usage=_read_resource_usage(assembly_root, elapsed_hours=elapsed_hours),
        )


def _run_command(command: list[str], cwd: Path, environment: dict[str, str]) -> None:
    try:
        subprocess.run(command, cwd=cwd, env=environment, check=True)
    except subprocess.CalledProcessError as exc:
        if exc.returncode in {
            -signal.SIGINT,
            -signal.SIGTERM,
            128 + signal.SIGINT,
            128 + signal.SIGTERM,
        }:
            raise InterruptedExecutionError(
                f"Nextflow assembly attempt was interrupted with exit code {exc.returncode}"
            ) from exc
        raise ToolExecutionError(
            f"Nextflow assembly attempt failed with exit code {exc.returncode}"
        ) from exc


def _append_optional(command: list[str], name: str, value: object | None) -> None:
    if value is not None and (not isinstance(value, str) or value.strip()):
        command.extend((name, str(value)))


def _read_tool_versions(assembly_root: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name, relative in (
        ("hifiasm", "metadata/hifiasm.version.txt"),
        ("gfatools", "metadata/gfatools.version.txt"),
    ):
        path = assembly_root / relative
        if path.is_file():
            versions[name] = path.read_text(errors="replace").strip()[:500]
    return versions


def _read_resource_usage(assembly_root: Path, *, elapsed_hours: float) -> ResourceUsage:
    """Read hifiasm CPU/RSS evidence and include end-to-end attempt walltime."""
    manifest = assembly_root / "metadata/assembly_manifest.json"
    if not manifest.is_file():
        return ResourceUsage(walltime_hours=elapsed_hours)
    try:
        payload = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolExecutionError(f"Assembly resource manifest is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ToolExecutionError("Assembly resource manifest must contain a JSON object")
    cpu_seconds = _nonnegative_number(payload.get("cpu_seconds"))
    peak_rss_gb = _nonnegative_number(payload.get("peak_rss_gb"))
    return ResourceUsage(
        cpu_hours=(cpu_seconds or 0.0) / 3600,
        walltime_hours=elapsed_hours,
        peak_rss_gib=(peak_rss_gb * (1000**3) / (1024**3) if peak_rss_gb is not None else None),
    )


def _nonnegative_number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


def _write_or_verify_lines(path: Path, values: list[Path]) -> None:
    content = "".join(f"{value.resolve()}\n" for value in values)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() != content:
        raise ToolExecutionError(f"current input manifest drift: {path}")
    if not path.exists():
        path.write_text(content)


def _verify_pre_qc_inventory(run_dir: Path, inventory_path: Path) -> None:
    try:
        inventory = ArtifactInventory.model_validate_json(inventory_path.read_text())
    except (OSError, ValueError) as exc:
        raise ToolExecutionError(f"Pre-QC inventory is invalid: {exc}") from exc
    for entry in inventory.entries:
        path = run_dir / entry.relative_path
        if not path.is_file() or sha256_file(path) != entry.sha256:
            raise ToolExecutionError(f"Pre-QC artifact inventory drift: {entry.relative_path}")


def nextflow_child_environment(invocation: WorkflowInvocation) -> dict[str, str]:
    """Expose the declared environment helper for deterministic acceptance tests."""
    environment = declared_subprocess_environment(invocation.sample)
    return {key: value for key, value in environment.items() if key in {"PATH", "PYTHONPATH"}}
