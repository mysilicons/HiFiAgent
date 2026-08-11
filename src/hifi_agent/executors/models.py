"""Typed current execution-port models shared by real and fixture runners."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hifi_agent.orchestration.manifests import ResourceUsage
from hifi_agent.orchestration.runtime_models import sha256_file
from hifi_agent.schemas.assembly import AssemblyConfig
from hifi_agent.schemas.sample import SampleConfig


class AttemptCoordinate(BaseModel):
    """Baseline or candidate identity independent of retry attempt number."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    round_index: int = Field(ge=0, le=3)
    candidate_index: int | None = Field(default=None, ge=1, le=2)

    @model_validator(mode="after")
    def validate_coordinate(self) -> AttemptCoordinate:
        """Reserve round zero for baseline and later rounds for candidates."""
        if (self.round_index == 0) != (self.candidate_index is None):
            raise ValueError("round 0 is baseline; rounds 1-3 require candidate_index")
        return self

    @property
    def round_id(self) -> str:
        """Return the stable round identifier."""
        return f"round_{self.round_index:02d}"

    @property
    def logical_run_id(self) -> str:
        """Return the stable scientific run identifier shared across retries."""
        if self.round_index == 0:
            return "baseline"
        return f"round_{self.round_index:02d}_candidate_{self.candidate_index:02d}"

    @property
    def relative_parent(self) -> Path:
        """Return the canonical directory above attempt_NNN."""
        if self.round_index == 0:
            return Path("baseline")
        return Path(self.round_id) / f"candidate_{self.candidate_index:02d}"


class InputArtifact(BaseModel):
    """Checksum-bound assembly input supplied by a manifest, never path guessing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    kind: Literal["file", "directory"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_path(cls, path: Path) -> InputArtifact:
        """Bind an existing input file to its checksum."""
        resolved = path.resolve()
        if resolved.is_file():
            return cls(path=resolved, kind="file", sha256=sha256_file(resolved))
        if resolved.is_dir():
            return cls(path=resolved, kind="directory", sha256=_sha256_directory(resolved))
        raise ValueError(f"Input artifact does not exist: {resolved}")

    def verify(self) -> Path:
        """Return the path only if it still matches the manifest."""
        exists = self.path.is_file() if self.kind == "file" else self.path.is_dir()
        observed = (
            sha256_file(self.path)
            if self.kind == "file" and exists
            else (_sha256_directory(self.path) if exists else "")
        )
        if not exists or observed != self.sha256:
            raise ValueError(f"Input artifact is missing or changed: {self.path}")
        return self.path


class AssemblyInputManifest(BaseModel):
    """Named inputs required by the common Nextflow attempt entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    artifacts: dict[str, InputArtifact]

    def require(self, role: str) -> Path:
        """Resolve one required role and verify its checksum."""
        artifact = self.artifacts.get(role)
        if artifact is None:
            raise ValueError(f"Assembly input manifest lacks required role: {role}")
        return artifact.verify()

    def optional(self, role: str) -> Path | None:
        """Resolve one optional role when declared."""
        artifact = self.artifacts.get(role)
        return artifact.verify() if artifact is not None else None


class ExecutionEstimate(BaseModel):
    """Conservative reservation requested before launching an attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cpu_hours: float = Field(default=1.0, gt=0.0)
    walltime_hours: float = Field(default=1.0, gt=0.0)
    artifact_gib: float = Field(default=0.001, gt=0.0)
    observed_free_gib: float = Field(default=1024.0, ge=0.0)


class PostQcContract(BaseModel):
    """Scientific post-QC settings applied identically to every assembly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    contract_id: Literal["post-qc"] = "post-qc"
    reference_genome: Path | None
    busco_lineage: str | None
    kmer_source: Literal["independent_high_confidence", "same_data_advisory"]
    mapping_min_read_length: int
    mapping_min_mean_qscore: float
    coverage_window_size: int

    @classmethod
    def from_sample(cls, sample: SampleConfig) -> PostQcContract:
        """Project one sample config into the invariant post-QC contract."""
        return cls(
            reference_genome=sample.reference_genome,
            busco_lineage=sample.busco_lineage,
            kmer_source=(
                "independent_high_confidence" if sample.kmer_reads else "same_data_advisory"
            ),
            mapping_min_read_length=sample.mapping_qc.min_read_length,
            mapping_min_mean_qscore=sample.mapping_qc.min_mean_qscore,
            coverage_window_size=sample.mapping_qc.coverage_window_size,
        )


class WorkflowInvocation(BaseModel):
    """Complete typed request passed to the one assembly workflow runner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    coordinate: AttemptCoordinate
    attempt_id: str
    attempt_root: Path
    sample: SampleConfig
    approved_config: AssemblyConfig
    inputs: AssemblyInputManifest
    post_qc_contract: PostQcContract
    rendered_hifiasm_argv: tuple[str, ...]
    resume: bool = False


class WorkflowResult(BaseModel):
    """Manifest-like result returned by any compliant workflow runner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: tuple[str, ...] = Field(min_length=1)
    realized_hifiasm_argv: tuple[str, ...] = Field(min_length=2)
    artifacts: tuple[Path, ...] = Field(min_length=1)
    tool_versions: dict[str, str]
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage)
    post_qc_contract_id: Literal["post-qc"] = "post-qc"


class ArtifactInventoryEntry(BaseModel):
    """One immutable artifact retained inside an attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: Path
    bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: Path) -> Path:
        """Prevent inventory references escaping the attempt root."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("Inventory paths must be attempt-relative")
        return value


class ArtifactInventory(BaseModel):
    """Checksum inventory frozen immediately before the completion marker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    attempt_id: str
    created_at: datetime
    entries: tuple[ArtifactInventoryEntry, ...] = Field(min_length=1)


class CompletionMarker(BaseModel):
    """Final marker proving a successful attempt's inventory and contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    attempt_id: str
    completed_at: datetime
    artifacts_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameter_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    post_qc_contract_id: Literal["post-qc"] = "post-qc"


class ExecutionStatus(BaseModel):
    """Mutable recovery hint; authoritative final status remains the manifest."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    attempt_id: str
    status: Literal["RUNNING", "INTERRUPTED", "FAILED", "COMPLETED"]
    started_at: datetime
    updated_at: datetime
    resume_count: int = Field(default=0, ge=0)
    error: str | None = None


def _sha256_directory(path: Path) -> str:
    """Hash directory membership, relative names, and every regular file."""
    import hashlib

    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    for item in files:
        digest.update(str(item.relative_to(path)).encode())
        digest.update(b"\0")
        digest.update(sha256_file(item).encode())
        digest.update(b"\n")
    return digest.hexdigest()
