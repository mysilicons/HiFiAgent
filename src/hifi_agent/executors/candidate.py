"""Stage 7 ApprovedCandidate-only execution with isolated, immutable attempts."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hifi_agent.agent.models import AssemblyConfig, AssemblyParameters
from hifi_agent.config import verify_recorded_input_checksums, verify_validation_receipt
from hifi_agent.exceptions import AgentStateError, HiFiAgentError, ToolExecutionError
from hifi_agent.executors.nextflow import NextflowRunResult, run_candidate_workflow
from hifi_agent.orchestration.history import AttemptHistoryStore
from hifi_agent.orchestration.models import AttemptIdentity
from hifi_agent.rag.models import ApprovedCandidate
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.schemas.sample import SampleConfig

Runner = Callable[..., NextflowRunResult]
HifiasmVersionResolver = Callable[[], tuple[str, str]]
SAFE_BIN_REUSE_PARAMETERS = frozenset(
    {"purge_level", "purge_similarity", "hom_cov", "disable_post_join"}
)


class CacheCompatibilityReceipt(BaseModel):
    """Checksum-bound decision for reuse of baseline corrected-read/overlap bins."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    status: Literal["PASS"] = "PASS"
    policy_version: Literal["hifiasm-bin-reuse-v1"] = "hifiasm-bin-reuse-v1"
    source_run_id: Literal["baseline"] = "baseline"
    target_run_id: str
    baseline_hifiasm_version: str
    runtime_hifiasm_version: str
    runtime_hifiasm_executable: Path
    changed_parameters: list[str]
    input_checksum_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bin_sha256: dict[str, str] = Field(min_length=1)
    reason_codes: list[str] = Field(min_length=1)


class ArtifactInventoryEntry(BaseModel):
    """One retained Stage 7 scientific or audit artifact."""

    model_config = ConfigDict(extra="forbid")

    relative_path: Path
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactInventory(BaseModel):
    """Complete checksum inventory of published candidate and post-QC outputs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    attempt: AttemptIdentity
    entries: list[ArtifactInventoryEntry] = Field(min_length=1)


class CandidateExecutionReceipt(BaseModel):
    """Recoverable Stage 7 execution result kept outside scientific metrics."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    status: Literal["RUNNING", "COMPLETED", "FAILED"]
    attempt: AttemptIdentity
    source_run_dir: Path
    workflow_run_dir: Path
    approved_candidate_id: str
    parameter_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: datetime
    completed_at: datetime | None = None
    resume_requested: bool
    nextflow_command: list[str] = Field(default_factory=list)
    artifact_inventory: Path | None = None
    tool_failures: list[str] = Field(default_factory=list)
    failure_category: (
        Literal[
            "PREFLIGHT",
            "WORKFLOW",
            "PARAMETER_CONTRACT",
            "POST_QC_TOOL_FAILURE",
            "HOMOLOGY_MISMATCH",
        ]
        | None
    ) = None
    error: str | None = None
    biological_quality_interpretation: Literal["NOT_EVALUATED_IN_STAGE7"] = (
        "NOT_EVALUATED_IN_STAGE7"
    )


class CandidateExecutor:
    """Execute only a validated ApprovedCandidate in an isolated attempt workspace."""

    def __init__(
        self,
        source_run_dir: Path,
        execution_root: Path,
        *,
        runner: Runner = run_candidate_workflow,
        hifiasm_version_resolver: HifiasmVersionResolver | None = None,
    ) -> None:
        self.source_run_dir = source_run_dir.resolve()
        self.execution_root = execution_root.resolve()
        self.runner = runner
        self.hifiasm_version_resolver = hifiasm_version_resolver or _resolve_hifiasm_version
        self.config_path = self.source_run_dir / "00_metadata/resolved_config.yaml"
        self.history = AttemptHistoryStore(self.execution_root)

    def execute(
        self,
        approved: ApprovedCandidate,
        *,
        round_index: int,
        candidate_index: int,
        resume: bool = False,
        retry: bool = False,
        threads: int | None = None,
        confirm_medium_high_risk: bool = False,
    ) -> CandidateExecutionReceipt:
        """Preflight, execute, validate homologous post-QC, and freeze one attempt."""
        config = self._load_config()
        self._initialize_history(config)
        if retry:
            matching = [
                item
                for item in self.history.load_history().attempts
                if item.kind == "candidate"
                and item.round_index == round_index
                and item.candidate_index == candidate_index
            ]
            if not matching:
                raise AgentStateError("Stage 7 retry requires an existing failed attempt")
            previous = matching[-1]
            previous_receipt = (
                self.execution_root
                / "02_assembly"
                / previous.relative_directory()
                / "stage7_execution.json"
            )
            prior_result = self._load_receipt(previous_receipt)
            self._assert_same_approval(prior_result, approved)
            if prior_result.status != "FAILED":
                raise AgentStateError("Stage 7 retry requires the latest attempt to be FAILED")
        attempt = self.history.begin_attempt(
            kind="candidate",
            round_index=round_index,
            candidate_index=candidate_index,
            retry=retry,
        )
        attempt_dir = self.execution_root / "02_assembly" / attempt.relative_directory()
        receipt_path = attempt_dir / "stage7_execution.json"
        if self.history.is_complete(attempt):
            completed = self._load_receipt(receipt_path)
            self._assert_same_approval(completed, approved)
            return completed
        if receipt_path.is_file():
            existing = self._load_receipt(receipt_path)
            self._assert_same_approval(existing, approved)
            if existing.status == "FAILED":
                raise AgentStateError("Failed Stage 7 attempt is immutable; create a retry attempt")
            if not resume:
                raise AgentStateError("Incomplete Stage 7 attempt exists; rerun with resume=True")

        workflow_run = attempt_dir / "workflow"
        started_at = (
            self._load_receipt(receipt_path).started_at
            if receipt_path.is_file()
            else datetime.now(UTC)
        )
        running = CandidateExecutionReceipt(
            status="RUNNING",
            attempt=attempt,
            source_run_dir=self.source_run_dir,
            workflow_run_dir=workflow_run,
            approved_candidate_id=approved.candidate_id,
            parameter_fingerprint=approved.parameter_fingerprint,
            started_at=started_at,
            resume_requested=resume,
        )
        _atomic_json(receipt_path, running.model_dump(mode="json"))

        audit_files: dict[str, Path] = {"stage7_execution": receipt_path}
        try:
            candidate = self._assembly_config(
                approved,
                attempt=attempt,
                config=config,
                threads=threads,
                confirm_medium_high_risk=confirm_medium_high_risk,
            )
            cache_receipt = self._preflight(approved, candidate, config, attempt_dir)
            cache_path = attempt_dir / "cache_compatibility.json"
            _atomic_json(cache_path, cache_receipt.model_dump(mode="json"))
            approval_path = attempt_dir / "approved_candidate.json"
            _atomic_json(approval_path, approved.model_dump(mode="json"))
            audit_files.update(
                {
                    "approved_candidate": approval_path,
                    "cache_compatibility": cache_path,
                }
            )
            result = self.runner(
                self.source_run_dir,
                candidate,
                resume=resume,
                execution_run_dir=workflow_run,
            )
            running.nextflow_command = list(result.command)
            binding_path = self._validate_attempt_binding(attempt, workflow_run)
            homology_path, metrics = self._validate_homologous_post_qc(
                attempt,
                workflow_run,
            )
            lineage_path = self._validate_parameter_lineage(
                approved,
                candidate,
                workflow_run,
                attempt_dir,
            )
            audit_files.update(
                {
                    "attempt_binding": binding_path,
                    "post_qc_homology": homology_path,
                    "parameter_lineage": lineage_path,
                    "assembly_manifest": workflow_run
                    / f"02_assembly/{attempt.run_id}/metadata/assembly_manifest.json",
                    "primary_fasta": workflow_run
                    / f"02_assembly/{attempt.run_id}/fasta/{attempt.run_id}.primary.fa",
                    "post_qc_metrics": workflow_run
                    / f"03_post_qc/{attempt.run_id}/assembly_metrics.json",
                    "parameter_contract": workflow_run
                    / f"02_assembly/{attempt.run_id}/metadata/parameter_contract_check.json",
                }
            )
            inventory_path = self._write_inventory(attempt, workflow_run, attempt_dir)
            assert inventory_path is not None
            audit_files["artifact_inventory"] = inventory_path
            running.artifact_inventory = inventory_path
            running.tool_failures = metrics.tool_failures
            running.completed_at = datetime.now(UTC)
            if metrics.tool_failures:
                running.status = "FAILED"
                running.failure_category = "POST_QC_TOOL_FAILURE"
                running.error = (
                    "Post-QC tool failure retained separately from biological quality: "
                    + ", ".join(metrics.tool_failures)
                )
                _atomic_json(receipt_path, running.model_dump(mode="json"))
                self.history.complete_attempt(
                    attempt,
                    artifacts=audit_files,
                    status="FAILED",
                    parameter_fingerprint=approved.parameter_fingerprint,
                    error=running.error,
                )
                return running
            running.status = "COMPLETED"
            _atomic_json(receipt_path, running.model_dump(mode="json"))
            self.history.complete_attempt(
                attempt,
                artifacts=audit_files,
                parameter_fingerprint=approved.parameter_fingerprint,
            )
            return running
        except (HiFiAgentError, OSError, ValidationError) as exc:
            if self._attempt_has_completion(attempt):
                raise
            running.status = "FAILED"
            running.completed_at = datetime.now(UTC)
            running.failure_category = _failure_category(exc)
            running.error = str(exc)
            _atomic_json(receipt_path, running.model_dump(mode="json"))
            partial_inventory = self._write_inventory(
                attempt,
                workflow_run,
                attempt_dir,
                required=False,
            )
            if partial_inventory is not None:
                audit_files["partial_artifact_inventory"] = partial_inventory
                running.artifact_inventory = partial_inventory
                _atomic_json(receipt_path, running.model_dump(mode="json"))
            self.history.complete_attempt(
                attempt,
                artifacts=audit_files,
                status="FAILED",
                parameter_fingerprint=approved.parameter_fingerprint,
                error=str(exc),
            )
            raise

    def _initialize_history(self, config: SampleConfig) -> None:
        if self.history.identity_path.is_file():
            self.history.load_identity(verify_config=self.config_path)
            self.history.verify_history()
            return
        self.history.initialize(config.sample_id, self.config_path)

    def _load_config(self) -> SampleConfig:
        try:
            payload = yaml.safe_load(self.config_path.read_text())
            return SampleConfig.model_validate(payload)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise ToolExecutionError(f"Stage 7 resolved config is invalid: {exc}") from exc

    def _assembly_config(
        self,
        approved: ApprovedCandidate,
        *,
        attempt: AttemptIdentity,
        config: SampleConfig,
        threads: int | None,
        confirm_medium_high_risk: bool,
    ) -> AssemblyConfig:
        if approved.requires_user_confirmation and not confirm_medium_high_risk:
            raise ToolExecutionError("Approved candidate still requires explicit risk confirmation")
        selected_threads = threads or config.resources.max_threads
        if selected_threads > config.resources.max_threads:
            raise ToolExecutionError("Candidate threads exceed validated resource limits")
        merged = AssemblyParameters().model_dump(mode="json")
        merged.update(approved.approved_parameters.model_dump(exclude_none=True))
        return AssemblyConfig(
            run_id=attempt.run_id,
            input_reads=config.hifi_reads,
            threads=selected_threads,
            parameters=AssemblyParameters.model_validate(merged),
            reason_codes=approved.reason_codes,
            source_metrics=approved.metric_ids,
            risk_level=approved.risk_level,
            requires_user_confirmation=False,
            retry_kind="PARAMETER_OPTIMIZATION",
            optimization_round=attempt.round_index,
        )

    def _preflight(
        self,
        approved: ApprovedCandidate,
        candidate: AssemblyConfig,
        config: SampleConfig,
        attempt_dir: Path,
    ) -> CacheCompatibilityReceipt:
        verify_validation_receipt(
            config,
            self.source_run_dir / "00_metadata/validation_receipt.json",
        )
        checksum_manifest = self.source_run_dir / "00_metadata/input_checksums.tsv"
        verify_recorded_input_checksums(checksum_manifest)
        if candidate.input_reads != config.hifi_reads:
            raise ToolExecutionError("Candidate reads differ from validated baseline inputs")
        changed = set(approved.approved_parameters.model_dump(exclude_none=True))
        unsupported = changed - SAFE_BIN_REUSE_PARAMETERS
        if unsupported:
            raise ToolExecutionError(
                f"Candidate changes parameter(s) incompatible with bin reuse: {sorted(unsupported)}"
            )
        baseline_manifest_path = (
            self.source_run_dir / "02_assembly/baseline/metadata/assembly_manifest.json"
        )
        try:
            baseline_manifest = json.loads(baseline_manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolExecutionError("Baseline assembly manifest is invalid") from exc
        version = baseline_manifest.get("hifiasm_version")
        if not isinstance(version, str) or not version:
            raise ToolExecutionError("Baseline hifiasm version is unavailable")
        executable, runtime_version = self.hifiasm_version_resolver()
        if runtime_version != version:
            raise ToolExecutionError(
                "Incompatible hifiasm cache rejected before launch: "
                f"baseline={version}, runtime={runtime_version}, executable={executable}"
            )
        bins = sorted((self.source_run_dir / "02_assembly/baseline/bins").glob("*.bin"))
        if not bins:
            raise ToolExecutionError("No baseline hifiasm bins are available")
        bin_sha256 = {path.name: _sha256(path) for path in bins}
        receipt = CacheCompatibilityReceipt(
            target_run_id=candidate.run_id,
            baseline_hifiasm_version=version,
            runtime_hifiasm_version=runtime_version,
            runtime_hifiasm_executable=Path(executable),
            changed_parameters=sorted(changed),
            input_checksum_manifest_sha256=_sha256(checksum_manifest),
            bin_sha256=bin_sha256,
            reason_codes=[
                "SAME_VALIDATED_INPUT_CHECKSUMS",
                "EXACT_BASELINE_HIFIASM_VERSION_REQUIRED_POST_RUN",
                "ONLY_GRAPH_OR_OUTPUT_STAGE_PARAMETERS_CHANGED",
                "CORRECTED_READ_AND_OVERLAP_BINS_CHECKSUM_BOUND",
            ],
        )
        _atomic_json(attempt_dir / "preflight.json", receipt.model_dump(mode="json"))
        return receipt

    def _validate_parameter_lineage(
        self,
        approved: ApprovedCandidate,
        candidate: AssemblyConfig,
        workflow_run: Path,
        attempt_dir: Path,
    ) -> Path:
        contract_path = (
            workflow_run / f"02_assembly/{candidate.run_id}/metadata/parameter_contract_check.json"
        )
        try:
            contract = json.loads(contract_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolExecutionError("Candidate parameter contract receipt is invalid") from exc
        execution_parameters = candidate.parameters.model_dump(mode="json")
        differences: dict[str, object] = {}
        if approved.requested_parameters != approved.approved_parameters:
            differences["requested_vs_approved"] = {
                "requested": approved.requested_parameters.model_dump(mode="json"),
                "approved": approved.approved_parameters.model_dump(mode="json"),
            }
        if contract.get("approved_parameters") != execution_parameters:
            differences["approved_vs_rendered"] = {
                "approved": execution_parameters,
                "rendered": contract.get("approved_parameters"),
            }
        if contract.get("realized_parameters") != execution_parameters:
            differences["rendered_vs_realized"] = {
                "rendered": execution_parameters,
                "realized": contract.get("realized_parameters"),
            }
        output = attempt_dir / "parameter_lineage.json"
        _atomic_json(
            output,
            {
                "schema_version": "2.0",
                "status": "FAIL" if differences else "PASS",
                "requested_parameters": approved.requested_parameters.model_dump(mode="json"),
                "approved_parameters": approved.approved_parameters.model_dump(mode="json"),
                "execution_parameters_with_defaults": execution_parameters,
                "rendered_parameters_with_defaults": contract.get("approved_parameters"),
                "realized_parameters_with_defaults": contract.get("realized_parameters"),
                "differences": differences,
            },
        )
        if differences:
            raise ToolExecutionError(
                f"PARAMETER_CONTRACT_VIOLATION: parameter lineage differs: {differences}"
            )
        return output

    def _validate_attempt_binding(
        self,
        attempt: AttemptIdentity,
        workflow_run: Path,
    ) -> Path:
        assembly_path = (
            workflow_run / f"02_assembly/{attempt.run_id}/metadata/assembly_manifest.json"
        )
        metrics_path = workflow_run / f"03_post_qc/{attempt.run_id}/assembly_metrics.json"
        try:
            assembly = json.loads(assembly_path.read_text())
            metrics = AssemblyMetrics.model_validate_json(metrics_path.read_text())
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ToolExecutionError("Candidate attempt outputs are invalid") from exc
        if assembly.get("run_id") != attempt.run_id or metrics.run_id != attempt.run_id:
            raise ToolExecutionError(
                "Candidate post-QC outputs are not bound to the attempt run ID"
            )
        output = (
            self.execution_root
            / "02_assembly"
            / attempt.relative_directory()
            / "attempt_binding.json"
        )
        _atomic_json(
            output,
            {
                "schema_version": "2.0",
                "attempt": attempt.model_dump(mode="json"),
                "assembly_run_id": assembly.get("run_id"),
                "post_qc_run_id": metrics.run_id,
                "status": "PASS",
            },
        )
        return output

    def _validate_homologous_post_qc(
        self,
        attempt: AttemptIdentity,
        workflow_run: Path,
    ) -> tuple[Path, AssemblyMetrics]:
        baseline_manifest_path = (
            self.source_run_dir / "02_assembly/baseline/metadata/assembly_manifest.json"
        )
        candidate_manifest_path = (
            workflow_run / f"02_assembly/{attempt.run_id}/metadata/assembly_manifest.json"
        )
        baseline_metrics_path = self.source_run_dir / "03_post_qc/baseline/assembly_metrics.json"
        candidate_metrics_path = workflow_run / f"03_post_qc/{attempt.run_id}/assembly_metrics.json"
        try:
            baseline_manifest = json.loads(baseline_manifest_path.read_text())
            candidate_manifest = json.loads(candidate_manifest_path.read_text())
            baseline = AssemblyMetrics.model_validate_json(baseline_metrics_path.read_text())
            candidate = AssemblyMetrics.model_validate_json(candidate_metrics_path.read_text())
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ToolExecutionError("Baseline/candidate homology evidence is invalid") from exc
        differences: dict[str, object] = {}
        if baseline_manifest.get("hifiasm_version") != candidate_manifest.get("hifiasm_version"):
            differences["hifiasm_version"] = {
                "baseline": baseline_manifest.get("hifiasm_version"),
                "candidate": candidate_manifest.get("hifiasm_version"),
            }
        if baseline.tool_versions != candidate.tool_versions:
            differences["post_qc_tool_versions"] = {
                "baseline": baseline.tool_versions,
                "candidate": candidate.tool_versions,
            }
        baseline_signature = _evaluation_signature(baseline)
        candidate_signature = _evaluation_signature(candidate)
        if baseline_signature != candidate_signature:
            differences["evaluation_parameters"] = {
                "baseline": baseline_signature,
                "candidate": candidate_signature,
            }
        output = (
            self.execution_root
            / "02_assembly"
            / attempt.relative_directory()
            / "post_qc_homology.json"
        )
        _atomic_json(
            output,
            {
                "schema_version": "2.0",
                "status": "FAIL" if differences else "PASS",
                "attempt_id": attempt.attempt_id,
                "baseline_run_id": "baseline",
                "candidate_run_id": attempt.run_id,
                "differences": differences,
                "candidate_tool_failures": candidate.tool_failures,
            },
        )
        if differences:
            raise ToolExecutionError(
                f"Baseline and candidate post-QC are not homologous: {differences}"
            )
        return output, candidate

    def _write_inventory(
        self,
        attempt: AttemptIdentity,
        workflow_run: Path,
        attempt_dir: Path,
        *,
        required: bool = True,
    ) -> Path | None:
        roots = [
            workflow_run / "00_metadata",
            workflow_run / "02_assembly" / attempt.run_id,
            workflow_run / "03_post_qc" / attempt.run_id,
            workflow_run / "logs",
        ]
        files = sorted(
            {
                path
                for root in roots
                if root.exists()
                for path in root.rglob("*")
                if path.is_file() and not path.is_symlink()
            }
        )
        if not files:
            if required:
                raise ToolExecutionError("Stage 7 produced no retainable artifacts")
            return None
        inventory = ArtifactInventory(
            attempt=attempt,
            entries=[
                ArtifactInventoryEntry(
                    relative_path=path.relative_to(workflow_run),
                    bytes=path.stat().st_size,
                    sha256=_sha256(path),
                )
                for path in files
            ],
        )
        output = attempt_dir / "artifact_inventory.json"
        _atomic_json(output, inventory.model_dump(mode="json"))
        return output

    def _load_receipt(self, path: Path) -> CandidateExecutionReceipt:
        try:
            return CandidateExecutionReceipt.model_validate_json(path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"Stage 7 execution receipt is invalid: {path}") from exc

    def _attempt_has_completion(self, attempt: AttemptIdentity) -> bool:
        return (
            self.execution_root / "02_assembly" / attempt.relative_directory() / "completion.json"
        ).is_file()

    @staticmethod
    def _assert_same_approval(
        receipt: CandidateExecutionReceipt,
        approved: ApprovedCandidate,
    ) -> None:
        if (
            receipt.approved_candidate_id != approved.candidate_id
            or receipt.parameter_fingerprint != approved.parameter_fingerprint
        ):
            raise AgentStateError("Stage 7 attempt is bound to a different ApprovedCandidate")


def _evaluation_signature(metrics: AssemblyMetrics) -> dict[str, object]:
    busco = metrics.tool_metadata.get("busco")
    mapping = metrics.tool_metadata.get("mapping_filter")
    merqury = metrics.tool_metadata.get("merqury")
    return {
        "busco": _selected_mapping(
            busco,
            {"requested_lineage", "actual_lineage", "lineage_selection"},
        ),
        "mapping_filter": _selected_mapping(
            mapping,
            {"min_read_length", "min_mean_qscore"},
        ),
        "merqury": _selected_mapping(merqury, {"kmer_source"}),
    }


def _selected_mapping(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {key: value.get(key) for key in sorted(keys)}


def _failure_category(
    error: Exception,
) -> Literal["PREFLIGHT", "WORKFLOW", "PARAMETER_CONTRACT", "HOMOLOGY_MISMATCH"]:
    text = str(error)
    if "PARAMETER_CONTRACT" in text:
        return "PARAMETER_CONTRACT"
    if "homologous" in text or "bound to the attempt" in text:
        return "HOMOLOGY_MISMATCH"
    if "Nextflow" in text or "workflow" in text.lower():
        return "WORKFLOW"
    return "PREFLIGHT"


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_hifiasm_version() -> tuple[str, str]:
    executable = shutil.which("hifiasm")
    local = Path("/home/gw/software/hifiasm/hifiasm")
    if executable is None and local.is_file() and local.stat().st_mode & 0o111:
        executable = str(local)
    if executable is None:
        raise ToolExecutionError("hifiasm executable was not found for cache validation")
    try:
        completed = subprocess.run(
            [executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ToolExecutionError(
            f"hifiasm version check failed before cache reuse: {executable}"
        ) from exc
    version = (completed.stdout or completed.stderr).strip().splitlines()
    if not version or not version[0]:
        raise ToolExecutionError("hifiasm returned an empty version before cache reuse")
    return executable, version[0].strip()
