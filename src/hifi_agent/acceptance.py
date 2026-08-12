"""Strict real-data acceptance verification and reproducible evidence packaging."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hifi_agent.exceptions import InputValidationError
from hifi_agent.executors.models import PostQcContract
from hifi_agent.orchestration.comparison import RoundComparison
from hifi_agent.orchestration.environment import EnvironmentManifest
from hifi_agent.orchestration.identity import IdentityStore
from hifi_agent.orchestration.runtime_config import resolve_runtime_config
from hifi_agent.orchestration.runtime_models import RunIdentity, sha256_file, sha256_json
from hifi_agent.orchestration.verifier import verify_run
from hifi_agent.reporting.models import FinalSummary
from hifi_agent.schemas.metrics import AssemblyMetrics

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DatasetLocator(BaseModel):
    """Portable external location rooted by an explicit environment variable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root_env: str = Field(pattern=r"^HIFI_AGENT_[A-Z0-9_]+$")
    relative_path: Path

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: Path) -> Path:
        """Reject absolute or parent-traversing external dataset locators."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("dataset relative_path must remain below its declared root")
        return value


class AcceptanceDataset(BaseModel):
    """Frozen biological and byte-level facts for one external acceptance input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    species: str
    taxon_id: int = Field(gt=0)
    read_technology: Literal["pacbio_hifi"]
    accession: str
    source_uri: str
    source_archive: str
    usage_policy: str
    usage_policy_uri: str
    approved_usage: tuple[str, ...] = Field(min_length=1)
    locator: DatasetLocator
    bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    read_count: int = Field(gt=0)
    total_bases: int = Field(gt=0)
    expected_genome_size: int = Field(gt=0)
    expected_genome_size_source: str
    ploidy: int = Field(gt=0)
    inbred: bool | None
    reference: None = None
    busco_lineage: str
    limitations: tuple[str, ...] = ()


class DatasetRegistry(BaseModel):
    """Versioned registry for real inputs that remain outside Git."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    registry_id: str
    datasets: tuple[AcceptanceDataset, ...] = Field(min_length=1)


class ResolvedDataset(BaseModel):
    """A registry entry resolved and re-hashed on the current host."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: AcceptanceDataset
    path: Path
    observed_bytes: int
    observed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RealRunAcceptance(BaseModel):
    """Machine-readable outcome of all non-provider real-run checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    status: Literal["PASS"] = "PASS"
    checked_at: datetime
    dataset_id: str
    run_uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    code_commit: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_attempt_ref: Path
    candidate_attempt_ref: Path
    changed_parameter: str
    comparison_outcome: Literal["ACCEPT_CANDIDATE", "KEEP_INCUMBENT"]
    comparison_reason_codes: tuple[str, ...] = Field(min_length=1)
    deep_verification: Literal["PASS"] = "PASS"
    environment_status: Literal["PASS"] = "PASS"
    checks: tuple[str, ...] = Field(min_length=1)
    run_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceBundleManifest(BaseModel):
    """Small release evidence bundle that references, rather than copies, large artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    status: Literal["PASS"] = "PASS"
    created_at: datetime
    code_commit: str
    package_version: str
    run_uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    dataset_id: str
    run_dir: Path
    run_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    wheel_file: str
    wheel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolved_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    live_smoke_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    real_suite_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    real_suite_tests: int = Field(gt=0)
    real_suite_failures: Literal[0] = 0
    real_suite_errors: Literal[0] = 0
    real_suite_skipped: Literal[0] = 0
    bundled_artifacts: dict[str, str]


def load_dataset(registry_path: Path, dataset_id: str) -> AcceptanceDataset:
    """Load exactly one frozen dataset record from the versioned registry."""
    try:
        registry = DatasetRegistry.model_validate(yaml.safe_load(registry_path.read_text()))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise InputValidationError(f"Dataset registry is invalid: {exc}") from exc
    matches = [item for item in registry.datasets if item.dataset_id == dataset_id]
    if len(matches) != 1:
        raise InputValidationError(
            f"Dataset registry must contain exactly one `{dataset_id}` entry"
        )
    return matches[0]


def resolve_dataset(registry_path: Path, dataset_id: str) -> ResolvedDataset:
    """Resolve, size-check, and fully hash one external dataset."""
    record = load_dataset(registry_path, dataset_id)
    root_value = os.environ.get(record.locator.root_env)
    if not root_value:
        raise InputValidationError(
            f"Dataset root environment variable `{record.locator.root_env}` is not set"
        )
    root = Path(root_value).expanduser().resolve()
    path = (root / record.locator.relative_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise InputValidationError(f"Dataset input is missing or escapes its root: {path}")
    observed_bytes = path.stat().st_size
    if observed_bytes != record.bytes:
        raise InputValidationError(
            f"Dataset byte size differs: expected={record.bytes}, observed={observed_bytes}"
        )
    observed_sha256 = sha256_file(path)
    if observed_sha256 != record.sha256:
        raise InputValidationError(
            f"Dataset checksum differs: expected={record.sha256}, observed={observed_sha256}"
        )
    return ResolvedDataset(
        record=record,
        path=path,
        observed_bytes=observed_bytes,
        observed_sha256=observed_sha256,
    )


def verify_real_run(run_dir: Path, dataset: ResolvedDataset) -> RealRunAcceptance:
    """Enforce the baseline/candidate, protocol, argv, QC, and comparator gates."""
    root = run_dir.resolve()
    identity = IdentityStore(root).verify_snapshots()
    deep = verify_run(root, deep=True)
    if deep.status != "PASS":
        failed = [item.check_id for item in deep.checks if item.status == "FAIL"]
        raise InputValidationError(f"Deep run verification failed: {', '.join(failed)}")
    summary = _load_summary(root)
    environment = _load_environment(root)
    if environment.status != "PASS" or environment.busco_lineage is None:
        raise InputValidationError("Real run environment or offline BUSCO lineage is incomplete")
    if environment.requested_threads != 128:
        raise InputValidationError("Real run did not use the required 128-thread resource limit")

    _verify_input_manifest(root, dataset)
    baseline = next(
        (item for item in summary.attempts if item.round_index == 0 and item.comparison_eligible),
        None,
    )
    candidates = [
        item for item in summary.attempts if item.round_index > 0 and item.comparison_eligible
    ]
    if baseline is None or not candidates:
        raise InputValidationError("Real run must contain an eligible baseline and candidate")
    candidate = candidates[0]
    if len(candidate.requested_config) != 1:
        raise InputValidationError("Real candidate requested config is not a one-variable diff")
    differences = {
        name
        for name in baseline.approved_parameters
        if baseline.approved_parameters[name] != candidate.approved_parameters.get(name)
    }
    if len(differences) != 1 or differences != set(candidate.requested_config):
        raise InputValidationError(
            "Real candidate changed more or less than its one approved variable"
        )
    changed_parameter = next(iter(differences))

    baseline_root = root / baseline.attempt_ref.parent
    candidate_root = root / candidate.attempt_ref.parent
    baseline_contract = _verify_attempt_contract(baseline_root)
    candidate_contract = _verify_attempt_contract(candidate_root)
    if baseline_contract != candidate_contract:
        raise InputValidationError("Baseline and candidate post-QC protocols differ")
    if baseline.rendered_argv != candidate.rendered_argv:
        _verify_only_approved_argv_change(baseline.rendered_argv, candidate.rendered_argv)
    _verify_metrics(baseline_root)
    _verify_metrics(candidate_root)
    if baseline.realized_parameters != baseline.approved_parameters:
        raise InputValidationError("Baseline approved and realized parameters differ")
    if candidate.realized_parameters != candidate.approved_parameters:
        raise InputValidationError("Candidate approved and realized parameters differ")

    comparison_path = root / "04_decisions/round_01/comparison.json"
    try:
        comparison = RoundComparison.model_validate_json(comparison_path.read_text())
    except (OSError, ValidationError) as exc:
        raise InputValidationError(f"Real comparison is invalid: {exc}") from exc
    comparison_outcome = comparison.outcome
    if comparison_outcome not in ("ACCEPT_CANDIDATE", "KEEP_INCUMBENT"):
        raise InputValidationError(
            f"Real comparison did not reach accept/reject/plateau: {comparison_outcome}"
        )
    if not comparison.reason_codes:
        raise InputValidationError("Real comparison lacks reason codes")

    run_hash = _run_evidence_hash(root, identity)
    return RealRunAcceptance(
        checked_at=datetime.now(UTC),
        dataset_id=dataset.record.dataset_id,
        run_uuid=identity.run_uuid,
        code_commit=identity.code_commit,
        input_sha256=dataset.observed_sha256,
        baseline_attempt_ref=baseline.attempt_ref,
        candidate_attempt_ref=candidate.attempt_ref,
        changed_parameter=changed_parameter,
        comparison_outcome=comparison_outcome,
        comparison_reason_codes=comparison.reason_codes,
        checks=(
            "DATASET_MANIFEST_MATCH",
            "SINGLE_IMMUTABLE_INPUT_MANIFEST",
            "ENVIRONMENT_AND_OFFLINE_BUSCO_COMPLETE",
            "BASELINE_AND_CANDIDATE_ELIGIBLE",
            "SINGLE_PARAMETER_CHANGE",
            "APPROVED_RENDERED_REALIZED_CONTRACT_PASS",
            "HOMOLOGOUS_POST_QC_PROTOCOL",
            "POST_QC_METRICS_PARSEABLE",
            "COMPARISON_REASON_CODES_COMPLETE",
            "DEEP_VERIFICATION_PASS",
        ),
        run_evidence_sha256=run_hash,
    )


def build_evidence_bundle(
    *,
    run_dir: Path,
    registry_path: Path,
    dataset_id: str,
    source_config: Path,
    wheel_path: Path,
    live_smoke_manifest: Path,
    real_suite_report: Path,
    output_dir: Path,
) -> Path:
    """Create an immutable small bundle after all real and live gates pass."""
    commit = _require_clean_commit()
    dataset = resolve_dataset(registry_path, dataset_id)
    acceptance = verify_real_run(run_dir, dataset)
    identity = IdentityStore(run_dir).verify_snapshots()
    if identity.code_commit != commit:
        raise InputValidationError(
            f"Run commit {identity.code_commit} differs from clean source commit {commit}"
        )
    _verify_source_config_binding(
        source_config,
        expected_effective_sha256=identity.effective_config_sha256,
        run_dir=run_dir,
    )
    from hifi_agent.live_smoke import verify_live_smoke

    smoke = verify_live_smoke(run_dir, live_smoke_manifest)
    if smoke.code_commit != commit:
        raise InputValidationError("Live smoke commit differs from the real run commit")
    tests, failures, errors, skipped = _junit_counts(real_suite_report)
    if tests <= 0 or failures or errors or skipped:
        raise InputValidationError(
            "Real acceptance suite must have tests>0, failures=0, errors=0, skipped=0"
        )
    if not wheel_path.is_file():
        raise InputValidationError(f"Wheel artifact is missing: {wheel_path}")
    _verify_wheel_source(wheel_path, identity.package_version)
    target = output_dir.resolve()
    if target.exists():
        raise InputValidationError(f"Evidence output already exists: {target}")
    copies = {
        "dataset_registry.yaml": registry_path,
        "source_config.yaml": source_config,
        wheel_path.name: wheel_path,
        "run_identity.json": run_dir / "00_metadata/run_identity.json",
        "input_manifest.json": run_dir / "00_metadata/input_manifest.json",
        "environment_manifest.json": run_dir / "00_metadata/environment_manifest.json",
        "baseline_attempt_manifest.json": run_dir / acceptance.baseline_attempt_ref,
        "candidate_attempt_manifest.json": run_dir / acceptance.candidate_attempt_ref,
        "comparison.json": run_dir / "04_decisions/round_01/comparison.json",
        "decision_context.json": run_dir / "04_decisions/round_01/decision_context.json",
        "rule_directive.json": run_dir / "04_decisions/round_01/rule_directive.json",
        "rag_index_snapshot.json": run_dir / "04_decisions/rag_index_snapshot.json",
        "final_summary.json": run_dir / "06_report/final_summary.json",
        "run_verification.json": run_dir / "06_report/verification_report.json",
        "live_smoke_manifest.json": live_smoke_manifest,
        "live_llm_call_receipt.json": (
            live_smoke_manifest.parent / "04_decisions/round_01/llm_call_receipt.json"
        ),
        "live_proposal_decision.json": (
            live_smoke_manifest.parent / "04_decisions/round_01/proposal_decision.json"
        ),
        "live_raw_response.json": (
            live_smoke_manifest.parent / "04_decisions/round_01/proposals/raw_llm_response.json"
        ),
        "real_acceptance.xml": real_suite_report,
    }
    missing = [source for source in copies.values() if not source.is_file()]
    if missing:
        raise InputValidationError(f"Required evidence artifact is missing: {missing[0]}")
    target.mkdir(parents=True)
    bundled: dict[str, str] = {}
    for name, source in copies.items():
        destination = target / name
        shutil.copy2(source, destination)
        bundled[name] = sha256_file(destination)
    manifest = EvidenceBundleManifest(
        created_at=datetime.now(UTC),
        code_commit=commit,
        package_version=identity.package_version,
        run_uuid=identity.run_uuid,
        dataset_id=dataset_id,
        run_dir=run_dir.resolve(),
        run_evidence_sha256=acceptance.run_evidence_sha256,
        wheel_file=wheel_path.name,
        wheel_sha256=sha256_file(wheel_path),
        registry_sha256=sha256_file(registry_path),
        source_config_sha256=sha256_file(source_config),
        resolved_config_sha256=identity.config_sha256,
        effective_config_sha256=identity.effective_config_sha256,
        input_manifest_sha256=identity.input_manifest_sha256,
        environment_manifest_sha256=identity.environment_manifest_sha256,
        live_smoke_manifest_sha256=sha256_file(live_smoke_manifest),
        real_suite_report_sha256=sha256_file(real_suite_report),
        real_suite_tests=tests,
        real_suite_failures=0,
        real_suite_errors=0,
        real_suite_skipped=0,
        bundled_artifacts=bundled,
    )
    path = target / "acceptance_manifest.json"
    path.write_text(manifest.model_dump_json(indent=2) + "\n")
    return path


def _load_summary(root: Path) -> FinalSummary:
    try:
        return FinalSummary.model_validate_json((root / "06_report/final_summary.json").read_text())
    except (OSError, ValidationError) as exc:
        raise InputValidationError(f"Final summary is invalid: {exc}") from exc


def _load_environment(root: Path) -> EnvironmentManifest:
    try:
        return EnvironmentManifest.model_validate_json(
            (root / "00_metadata/environment_manifest.json").read_text()
        )
    except (OSError, ValidationError) as exc:
        raise InputValidationError(f"Environment manifest is invalid: {exc}") from exc


def _verify_input_manifest(root: Path, dataset: ResolvedDataset) -> None:
    try:
        manifest = json.loads((root / "00_metadata/input_manifest.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise InputValidationError(f"Run input manifest is invalid: {exc}") from exc
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    hifi = [item for item in entries or [] if item.get("role") == "hifi_reads"]
    if len(hifi) != 1:
        raise InputValidationError("Real run must contain exactly one registered HiFi input")
    entry = hifi[0]
    if (
        entry.get("path") != str(dataset.path)
        or entry.get("bytes") != dataset.observed_bytes
        or entry.get("sha256") != dataset.observed_sha256
    ):
        raise InputValidationError("Run input manifest differs from the frozen dataset record")


def _verify_attempt_contract(attempt_root: Path) -> PostQcContract:
    try:
        check = json.loads((attempt_root / "contract/parameter_contract_check.json").read_text())
        post_qc = PostQcContract.model_validate_json(
            (attempt_root / "metadata/post_qc_contract.json").read_text()
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise InputValidationError(f"Attempt contract is invalid at {attempt_root}: {exc}") from exc
    if check.get("status") != "PASS":
        raise InputValidationError(f"Attempt parameter contract did not pass: {attempt_root}")
    return post_qc


def _verify_metrics(attempt_root: Path) -> None:
    try:
        metrics = AssemblyMetrics.model_validate_json(
            (attempt_root / "post_qc/assembly_metrics.json").read_text()
        )
    except (OSError, ValidationError) as exc:
        raise InputValidationError(
            f"Post-QC metrics are not parseable at {attempt_root}: {exc}"
        ) from exc
    required = (
        "busco_complete",
        "kmer_completeness",
        "kmer_qv",
        "mapped_read_fraction",
        "coverage_cv",
        "contig_n50",
    )
    missing = [name for name in required if getattr(metrics, name) is None]
    if missing:
        raise InputValidationError(
            f"Post-QC metrics are missing required values at {attempt_root}: {', '.join(missing)}"
        )


def _verify_only_approved_argv_change(
    baseline: tuple[str, ...], candidate: tuple[str, ...]
) -> None:
    """Require argv shape to remain comparable; detailed values are checked by each contract."""
    if baseline[0] != candidate[0] or "-t" not in baseline or "-t" not in candidate:
        raise InputValidationError(
            "Baseline and candidate argv do not use the same assembler contract"
        )


def _run_evidence_hash(root: Path, identity: RunIdentity) -> str:
    paths = [
        root / "00_metadata/run_identity.json",
        root / "05_agent/history_manifest.jsonl",
        root / "06_report/final_summary.json",
        root / "06_report/verification_report.json",
        *sorted((root / "02_assembly").glob("**/attempt_manifest.json")),
        *sorted((root / "04_decisions").glob("round_*/round_manifest.json")),
    ]
    payload = {
        "run_uuid": identity.run_uuid,
        "artifacts": {
            str(path.relative_to(root)): sha256_file(path) for path in paths if path.is_file()
        },
    }
    return sha256_json(payload)


def _require_clean_commit() -> str:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InputValidationError(f"Unable to verify source commit: {exc}") from exc
    if dirty:
        raise InputValidationError("Release evidence requires a clean committed source tree")
    return commit


def _junit_counts(path: Path) -> tuple[int, int, int, int]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise InputValidationError(f"Real suite JUnit report is invalid: {exc}") from exc
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise InputValidationError("Real suite JUnit report contains no test suites")
    totals = []
    for key in ("tests", "failures", "errors", "skipped"):
        totals.append(sum(int(item.attrib.get(key, "0")) for item in suites))
    return totals[0], totals[1], totals[2], totals[3]


def _verify_wheel_source(wheel_path: Path, package_version: str) -> None:
    """Require byte-identical package sources and production runtime resources."""
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            names = set(archive.namelist())
            metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise InputValidationError("Wheel must contain exactly one METADATA record")
            metadata = archive.read(metadata_names[0]).decode(errors="replace")
            if f"Version: {package_version}\n" not in metadata:
                raise InputValidationError(
                    "Wheel version differs from the real run package version"
                )
            expected_sources = {
                path.relative_to(PROJECT_ROOT / "src").as_posix(): path
                for path in (PROJECT_ROOT / "src/hifi_agent").rglob("*.py")
            }
            wheel_sources = {
                name for name in names if name.startswith("hifi_agent/") and name.endswith(".py")
            }
            if set(expected_sources) != wheel_sources:
                raise InputValidationError(
                    "Wheel Python source set differs from the committed source tree"
                )
            changed = [
                name
                for name, source in expected_sources.items()
                if archive.read(name) != source.read_bytes()
            ]
            if changed:
                raise InputValidationError(
                    "Wheel contains source bytes that differ from the clean commit: "
                    + ", ".join(changed)
                )
            data_root = PROJECT_ROOT / "src/hifi_agent/data"
            expected_resources = {
                path.relative_to(PROJECT_ROOT / "src").as_posix(): path
                for path in data_root.rglob("*")
                if path.is_file() and path.suffix in {".config", ".json", ".nf", ".yaml"}
            }
            missing_resources = sorted(set(expected_resources).difference(names))
            if missing_resources:
                raise InputValidationError(
                    "Wheel is missing production runtime resources: " + ", ".join(missing_resources)
                )
            changed_resources = [
                name
                for name, source in expected_resources.items()
                if archive.read(name) != source.read_bytes()
            ]
            if changed_resources:
                raise InputValidationError(
                    "Wheel contains runtime resource bytes that differ from the clean commit: "
                    + ", ".join(changed_resources)
                )
    except zipfile.BadZipFile as exc:
        raise InputValidationError(f"Wheel artifact is invalid: {exc}") from exc


def _verify_source_config_binding(
    source_config: Path,
    *,
    expected_effective_sha256: str,
    run_dir: Path,
) -> None:
    """Resolve the committed source config and bind it to the accepted run identity."""
    try:
        runtime = resolve_runtime_config(source_config)
    except (OSError, ValueError) as exc:
        raise InputValidationError(f"Source config cannot be resolved: {exc}") from exc
    effective_payload = (
        json.dumps(runtime.effective.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    observed_effective_sha256 = hashlib.sha256(effective_payload.encode()).hexdigest()
    if observed_effective_sha256 != expected_effective_sha256:
        raise InputValidationError(
            "Committed source config does not reproduce the run effective config"
        )
    if runtime.effective.sample.outdir.resolve() != run_dir.resolve():
        raise InputValidationError("Committed source config points to a different run directory")


def file_sha256(path: Path) -> str:
    """Public streaming digest helper for launch and evidence scripts."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
