"""Immutable current attempt/round manifests and append-only history chain."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from hifi_agent.exceptions import AgentStateError
from hifi_agent.orchestration.runtime_models import sha256_file, sha256_json


class ManifestReference(BaseModel):
    """Checksum-bound reference relative to one current run root."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("relative_path")
    @classmethod
    def require_safe_relative_path(cls, value: Path) -> Path:
        """Reject absolute and parent-traversing manifest references."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("manifest references must be safe run-relative paths")
        return value

    @classmethod
    def from_path(cls, run_dir: Path, path: Path) -> ManifestReference:
        """Create a run-relative reference bound to the file's current SHA-256."""
        root = run_dir.resolve()
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise AgentStateError(f"Manifest path escapes the run root: {resolved}") from exc
        if not resolved.is_file():
            raise AgentStateError(f"Manifest reference is not a file: {resolved}")
        return cls(relative_path=relative, sha256=sha256_file(resolved))


class ResourceUsage(BaseModel):
    """Actual resource settlement attached to a completed attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cpu_hours: float = Field(default=0.0, ge=0.0)
    walltime_hours: float = Field(default=0.0, ge=0.0)
    peak_rss_gib: float | None = Field(default=None, ge=0.0)
    artifact_bytes: int = Field(default=0, ge=0)


class AssemblyAttemptRecord(BaseModel):
    """Final immutable manifest for one baseline or candidate attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    attempt_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    logical_run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    round_id: str = Field(pattern=r"^round_[0-9]{2}$")
    round_index: int = Field(ge=0, le=3)
    candidate_index: int | None = Field(default=None, ge=1, le=2)
    attempt_index: int = Field(ge=1)
    status: Literal[
        "PLANNED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "INTERRUPTED",
        "CONTRACT_VIOLATION",
    ]
    requested_config_ref: ManifestReference | None = None
    approved_config_ref: ManifestReference | None = None
    rendered_config_ref: ManifestReference | None = None
    realized_config_ref: ManifestReference | None = None
    command: list[str] = Field(default_factory=list)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    environment_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: datetime
    completed_at: datetime | None = None
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage)
    artifacts_inventory_ref: ManifestReference | None = None
    completion_marker_ref: ManifestReference | None = None
    error: str | None = None
    retry_parent_attempt_id: str | None = None
    comparison_eligible: bool = False
    ineligible_reason_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_completion_contract(self) -> AssemblyAttemptRecord:
        """Require completion evidence before an attempt can enter comparison."""
        if self.status == "COMPLETED" and self.completed_at is None:
            raise ValueError("completed attempt requires completed_at")
        if self.comparison_eligible and (
            self.status != "COMPLETED"
            or self.artifacts_inventory_ref is None
            or self.completion_marker_ref is None
        ):
            raise ValueError(
                "comparison-eligible attempt requires COMPLETED status, inventory, and marker"
            )
        if not self.comparison_eligible and not self.ineligible_reason_codes:
            raise ValueError("ineligible attempt requires reason codes")
        return self

    def relative_directory(self) -> Path:
        """Return the canonical current directory for this attempt coordinate."""
        parent = (
            Path("baseline")
            if self.round_index == 0
            else Path(self.round_id) / f"candidate_{self.candidate_index:02d}"
        )
        return parent / f"attempt_{self.attempt_index:03d}"


class RoundRecord(BaseModel):
    """Final immutable audit manifest for baseline round 0 or optimization round 1-3."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    round_id: str = Field(pattern=r"^round_[0-9]{2}$")
    round_index: int = Field(ge=0, le=3)
    incumbent_before_ref: ManifestReference | None = None
    decision_context_ref: ManifestReference | None = None
    rule_decision_ref: ManifestReference | None = None
    retrieval_trace_ref: ManifestReference | None = None
    proposal_decision_ref: ManifestReference | None = None
    llm_call_receipt_ref: ManifestReference | None = None
    llm_raw_response_ref: ManifestReference | None = None
    raw_candidate_refs: list[ManifestReference] = Field(default_factory=list)
    approved_candidate_refs: list[ManifestReference] = Field(default_factory=list)
    rejected_candidate_refs: list[ManifestReference] = Field(default_factory=list)
    attempt_refs: list[ManifestReference] = Field(default_factory=list)
    comparison_ref: ManifestReference | None = None
    incumbent_after_ref: ManifestReference | None = None
    round_outcome: str
    stop_reason_codes: list[str] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def validate_round_coordinate(self) -> RoundRecord:
        """Keep round identifiers and timestamps internally consistent."""
        if self.round_id != f"round_{self.round_index:02d}":
            raise ValueError("round_id does not match round_index")
        if self.completed_at < self.created_at:
            raise ValueError("round completed_at precedes created_at")
        return self


class HistoryManifest(BaseModel):
    """One append-only history snapshot linked to the previous snapshot hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    sequence: int = Field(ge=1)
    created_at: datetime
    previous_entry_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    attempt_refs: list[ManifestReference] = Field(default_factory=list)
    round_refs: list[ManifestReference] = Field(default_factory=list)


class ManifestStore:
    """Persist immutable manifests and verify the append-only reference graph."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.history_path = self.run_dir / "05_agent/history_manifest.jsonl"

    def initialize_history(self) -> HistoryManifest:
        """Create the first empty history entry without replacing existing history."""
        if self.history_path.exists():
            raise AgentStateError("current history manifest already exists")
        entry = HistoryManifest(sequence=1, created_at=datetime.now(UTC))
        _append_model(self.history_path, entry)
        return entry

    def write_attempt(self, record: AssemblyAttemptRecord) -> Path:
        """Write one immutable attempt manifest at its canonical current path."""
        expected_round = f"round_{record.round_index:02d}"
        if record.round_id != expected_round:
            raise AgentStateError("Attempt round_id does not match round_index")
        path = self.run_dir / "02_assembly" / record.relative_directory() / "attempt_manifest.json"
        _exclusive_model(path, record)
        return path

    def write_round(self, record: RoundRecord) -> Path:
        """Write one immutable round manifest at its canonical decision path."""
        path = self.run_dir / "04_decisions" / record.round_id / "round_manifest.json"
        _exclusive_model(path, record)
        return path

    def append_history(
        self,
        *,
        attempt_paths: list[Path] | None = None,
        round_paths: list[Path] | None = None,
    ) -> HistoryManifest:
        """Append a deduplicated checksum-bound snapshot to the history chain."""
        entries = self.load_history()
        if not entries:
            raise AgentStateError("current history manifest must be initialized first")
        previous = entries[-1]
        attempt_refs = list(previous.attempt_refs)
        round_refs = list(previous.round_refs)
        for path in attempt_paths or []:
            reference = ManifestReference.from_path(self.run_dir, path)
            if reference.relative_path not in {item.relative_path for item in attempt_refs}:
                attempt_refs.append(reference)
        for path in round_paths or []:
            reference = ManifestReference.from_path(self.run_dir, path)
            if reference.relative_path not in {item.relative_path for item in round_refs}:
                round_refs.append(reference)
        entry = HistoryManifest(
            sequence=previous.sequence + 1,
            created_at=datetime.now(UTC),
            previous_entry_sha256=sha256_json(previous.model_dump(mode="json")),
            attempt_refs=attempt_refs,
            round_refs=round_refs,
        )
        _append_model(self.history_path, entry)
        return entry

    def load_history(self) -> list[HistoryManifest]:
        """Load and verify contiguous sequence numbers and previous-entry hashes."""
        if not self.history_path.is_file():
            return []
        entries: list[HistoryManifest] = []
        for line_number, line in enumerate(self.history_path.read_text().splitlines(), start=1):
            try:
                entries.append(HistoryManifest.model_validate_json(line))
            except ValidationError as exc:
                raise AgentStateError(
                    f"current history manifest line {line_number} is invalid: {exc}"
                ) from exc
        for index, entry in enumerate(entries):
            expected_sequence = index + 1
            if entry.sequence != expected_sequence:
                raise AgentStateError("current history manifest sequence is not contiguous")
            expected_previous = (
                None if index == 0 else sha256_json(entries[index - 1].model_dump(mode="json"))
            )
            if entry.previous_entry_sha256 != expected_previous:
                raise AgentStateError("current history manifest hash chain is broken")
        return entries

    def verify(self) -> HistoryManifest:
        """Verify all registered manifests and reject unregistered manifest files."""
        entries = self.load_history()
        if not entries:
            raise AgentStateError("current history manifest is missing")
        latest = entries[-1]
        registered = {ref.relative_path for ref in [*latest.attempt_refs, *latest.round_refs]}
        for reference in [*latest.attempt_refs, *latest.round_refs]:
            path = self.run_dir / reference.relative_path
            if not path.is_file() or sha256_file(path) != reference.sha256:
                raise AgentStateError(
                    f"current registered manifest drift: {reference.relative_path}"
                )
            try:
                if path.name == "attempt_manifest.json":
                    attempt = AssemblyAttemptRecord.model_validate_json(path.read_text())
                    nested = (
                        attempt.requested_config_ref,
                        attempt.approved_config_ref,
                        attempt.rendered_config_ref,
                        attempt.realized_config_ref,
                        attempt.artifacts_inventory_ref,
                        attempt.completion_marker_ref,
                    )
                    for item in nested:
                        if item is not None:
                            _verify_reference(self.run_dir, item)
                elif path.name == "round_manifest.json":
                    round_record = RoundRecord.model_validate_json(path.read_text())
                    nested_round = (
                        round_record.incumbent_before_ref,
                        round_record.decision_context_ref,
                        round_record.rule_decision_ref,
                        round_record.retrieval_trace_ref,
                        round_record.proposal_decision_ref,
                        round_record.llm_call_receipt_ref,
                        round_record.llm_raw_response_ref,
                        round_record.comparison_ref,
                        round_record.incumbent_after_ref,
                        *round_record.raw_candidate_refs,
                        *round_record.approved_candidate_refs,
                        *round_record.rejected_candidate_refs,
                        *round_record.attempt_refs,
                    )
                    for item in nested_round:
                        if item is not None:
                            _verify_reference(self.run_dir, item)
            except ValidationError as exc:
                raise AgentStateError(
                    f"current registered manifest is invalid: {path}: {exc}"
                ) from exc
        discovered = {
            path.relative_to(self.run_dir)
            for pattern in (
                "02_assembly/**/attempt_manifest.json",
                "04_decisions/round_*/round_manifest.json",
            )
            for path in self.run_dir.glob(pattern)
        }
        if discovered != registered:
            raise AgentStateError(
                "current history/discovered manifest set differs: "
                f"registered={sorted(map(str, registered))}, "
                f"discovered={sorted(map(str, discovered))}"
            )
        return latest


def _verify_reference(run_dir: Path, reference: ManifestReference) -> None:
    path = run_dir / reference.relative_path
    if not path.is_file() or sha256_file(path) != reference.sha256:
        raise AgentStateError(f"current nested manifest reference drift: {reference.relative_path}")


def _exclusive_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(model.model_dump_json(indent=2))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _append_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(model.model_dump_json())
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
