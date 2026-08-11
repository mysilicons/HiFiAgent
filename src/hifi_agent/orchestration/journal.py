"""Crash-safe current state/event transaction journal with deterministic recovery."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from pydantic import ValidationError

from hifi_agent.exceptions import AgentStateError, IllegalStateTransitionError
from hifi_agent.orchestration.runtime_models import (
    PendingTransaction,
    RunEvent,
    RunIdentity,
    RunPhase,
    RunState,
    sha256_json,
    state_control_sha256,
)

FaultInjector = Callable[[str, PendingTransaction], None]


_FLOW: dict[RunPhase, frozenset[RunPhase]] = {
    RunPhase.INITIALIZING: frozenset({RunPhase.INPUT_VALIDATION}),
    RunPhase.INPUT_VALIDATION: frozenset({RunPhase.ENVIRONMENT_PREFLIGHT}),
    RunPhase.ENVIRONMENT_PREFLIGHT: frozenset({RunPhase.PRE_QC}),
    RunPhase.PRE_QC: frozenset({RunPhase.BASELINE_PLAN}),
    RunPhase.BASELINE_PLAN: frozenset({RunPhase.BASELINE_ASSEMBLY}),
    RunPhase.BASELINE_ASSEMBLY: frozenset({RunPhase.BASELINE_ASSEMBLY, RunPhase.BASELINE_POST_QC}),
    RunPhase.BASELINE_POST_QC: frozenset({RunPhase.BASELINE_REVIEW}),
    RunPhase.BASELINE_REVIEW: frozenset({RunPhase.ROUND_CONTEXT}),
    RunPhase.ROUND_CONTEXT: frozenset({RunPhase.RAG_RETRIEVAL}),
    RunPhase.RAG_RETRIEVAL: frozenset({RunPhase.LLM_PROPOSAL}),
    RunPhase.LLM_PROPOSAL: frozenset({RunPhase.SAFETY_REVIEW}),
    RunPhase.SAFETY_REVIEW: frozenset({RunPhase.BUDGET_RESERVATION, RunPhase.ROUND_COMPARISON}),
    RunPhase.BUDGET_RESERVATION: frozenset({RunPhase.CANDIDATE_ASSEMBLY}),
    RunPhase.CANDIDATE_ASSEMBLY: frozenset(
        {RunPhase.CANDIDATE_ASSEMBLY, RunPhase.CANDIDATE_POST_QC}
    ),
    RunPhase.CANDIDATE_POST_QC: frozenset({RunPhase.CANDIDATE_ASSEMBLY, RunPhase.ROUND_COMPARISON}),
    RunPhase.ROUND_COMPARISON: frozenset({RunPhase.INCUMBENT_UPDATE, RunPhase.REPORTING}),
    RunPhase.INCUMBENT_UPDATE: frozenset({RunPhase.ROUND_CONTEXT, RunPhase.REPORTING}),
    RunPhase.REPORTING: frozenset({RunPhase.VERIFYING}),
    RunPhase.VERIFYING: frozenset({RunPhase.TERMINAL}),
    RunPhase.TERMINAL: frozenset(),
}


def validate_transition(before: RunPhase, after: RunPhase) -> None:
    """Reject lifecycle transitions outside the explicit current graph."""
    allowed = set(_FLOW[before])
    if before not in {RunPhase.REPORTING, RunPhase.VERIFYING, RunPhase.TERMINAL}:
        allowed.add(RunPhase.REPORTING)
    if after not in allowed:
        rendered = ", ".join(sorted(item.value for item in allowed)) or "<none>"
        raise IllegalStateTransitionError(
            f"Illegal current transition {before.value} -> {after.value}; allowed: {rendered}"
        )


class StateStore:
    """Own the authoritative snapshot and append-only event journal for a current run."""

    def __init__(self, run_dir: Path, *, fault_injector: FaultInjector | None = None) -> None:
        self.run_dir = run_dir.resolve()
        self.directory = self.run_dir / "05_agent"
        self.state_path = self.directory / "run_state.json"
        self.trace_path = self.directory / "event_trace.jsonl"
        self.pending_dir = self.directory / "pending"
        self.fault_injector = fault_injector

    def initialize(self, identity: RunIdentity) -> RunState:
        """Create the first transaction without overwriting any current control plane."""
        if (
            self.state_path.exists()
            or self.trace_path.exists()
            or any(self.pending_dir.glob("*.json") if self.pending_dir.exists() else ())
        ):
            raise AgentStateError("current state already exists; use --resume")
        if identity.run_dir.resolve() != self.run_dir:
            raise AgentStateError("current identity run_dir differs from the state store root")
        state = RunState(identity=identity)
        return self._transact(
            previous=None,
            next_state=state,
            state_before=None,
            action="INITIALIZE_RUN",
            reason_codes=["CONTROL_PLANE_INITIALIZED"],
        )

    def transition(
        self,
        state: RunState,
        target: RunPhase,
        *,
        action: str,
        reason_codes: list[str],
        updates: dict[str, object] | None = None,
    ) -> RunState:
        """Validate and commit one transition through the pending journal."""
        persisted = self.load()
        if persisted.identity != state.identity or persisted.sequence != state.sequence:
            raise AgentStateError("Caller current state is stale or belongs to a different run")
        validate_transition(state.state, target)
        payload = state.model_dump(mode="python")
        forbidden_updates = {
            "schema_id",
            "identity",
            "sequence",
            "state",
            "last_transaction_id",
            "last_event",
        }
        invalid_updates = forbidden_updates.intersection(updates or {})
        if invalid_updates:
            raise AgentStateError(
                f"current transition updates protected field(s): {sorted(invalid_updates)}"
            )
        payload.update(updates or {})
        payload["state"] = target
        next_state = RunState.model_validate(payload)
        return self._transact(
            previous=state,
            next_state=next_state,
            state_before=state.state,
            action=action,
            reason_codes=reason_codes,
        )

    def load(self) -> RunState:
        """Recover at most one pending transaction and verify the full journal."""
        self._recover_pending()
        state = self._read_state()
        assert state is not None
        events = self.load_events()
        if not events:
            raise AgentStateError("current event trace is empty")
        if state.sequence != len(events):
            raise AgentStateError(
                f"State/event mismatch: state={state.sequence}, events={len(events)}"
            )
        last = events[-1]
        if state.last_event != last or state.last_transaction_id != last.transaction_id:
            raise AgentStateError("current state does not match the final committed event")
        if state_control_sha256(state) != last.state_sha256:
            raise AgentStateError("current state control checksum does not match the final event")
        if state.identity.run_dir.resolve() != self.run_dir:
            raise AgentStateError("current state identity points at a different run directory")
        return state

    def verify_read_only(self) -> RunState:
        """Verify state/event integrity without reconciling or writing pending work."""
        pending = sorted(self.pending_dir.glob("*.json")) if self.pending_dir.exists() else []
        if pending:
            raise AgentStateError(
                "current has a pending transaction; resume is required before verify"
            )
        state = self._read_state()
        assert state is not None
        events = self.load_events()
        if state.sequence != len(events):
            raise AgentStateError(
                f"State/event mismatch: state={state.sequence}, events={len(events)}"
            )
        if not events or state.last_event != events[-1]:
            raise AgentStateError("current state does not match the append-only event tail")
        if state.last_transaction_id != events[-1].transaction_id:
            raise AgentStateError("current state transaction ID does not match the event tail")
        if state_control_sha256(state) != events[-1].state_sha256:
            raise AgentStateError("current state control checksum does not match the event tail")
        if state.identity.run_dir.resolve() != self.run_dir:
            raise AgentStateError("current state identity points at a different run directory")
        return state

    def load_events(self) -> list[RunEvent]:
        """Load and strictly validate the append-only event sequence."""
        if not self.trace_path.is_file():
            return []
        events: list[RunEvent] = []
        for line_number, line in enumerate(self.trace_path.read_text().splitlines(), start=1):
            if not line:
                raise AgentStateError(
                    f"current event trace contains an empty line at {line_number}"
                )
            try:
                events.append(RunEvent.model_validate_json(line))
            except ValidationError as exc:
                raise AgentStateError(
                    f"current event trace line {line_number} is invalid: {exc}"
                ) from exc
        expected = list(range(1, len(events) + 1))
        observed = [event.sequence for event in events]
        if observed != expected:
            raise AgentStateError(
                f"Event sequence is not contiguous: expected {expected}, observed {observed}"
            )
        transaction_ids = [event.transaction_id for event in events]
        if len(transaction_ids) != len(set(transaction_ids)):
            raise AgentStateError("current event trace contains duplicate transaction IDs")
        if events and (
            events[0].state_before is not None or events[0].state_after != RunPhase.INITIALIZING
        ):
            raise AgentStateError("current event trace has an invalid initialization event")
        for previous, current in pairwise(events):
            if current.state_before != previous.state_after:
                raise AgentStateError("current event state chain is not contiguous")
            try:
                validate_transition(previous.state_after, current.state_after)
            except IllegalStateTransitionError as exc:
                raise AgentStateError(f"current event transition graph is invalid: {exc}") from exc
        return events

    def _transact(
        self,
        *,
        previous: RunState | None,
        next_state: RunState,
        state_before: RunPhase | None,
        action: str,
        reason_codes: list[str],
    ) -> RunState:
        previous_sequence = previous.sequence if previous is not None else 0
        next_state.sequence = previous_sequence + 1
        event = RunEvent(
            transaction_id=uuid.uuid4().hex,
            sequence=next_state.sequence,
            timestamp=datetime.now(UTC),
            state_before=state_before,
            state_after=next_state.state,
            action=action,
            reason_codes=reason_codes,
            round_index=next_state.round_index,
            candidate_index=next_state.candidate_index,
            attempt_id=next_state.active_attempt_id,
            state_sha256=state_control_sha256(next_state),
        )
        next_state.last_transaction_id = event.transaction_id
        next_state.last_event = event
        pending = PendingTransaction.create(
            previous_sequence=previous_sequence,
            event=event,
            next_state=next_state,
        )
        self._commit_pending(pending)
        return next_state

    def _commit_pending(self, pending: PendingTransaction) -> None:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        path = self.pending_dir / f"{pending.event.transaction_id}.json"
        _exclusive_json(path, pending.model_dump(mode="json"))
        self._fault("after_pending", pending)
        _atomic_json(self.state_path, pending.next_state.model_dump(mode="json"))
        self._fault("after_state", pending)
        _append_event(self.trace_path, pending.event)
        self._fault("after_event", pending)
        path.unlink()
        _fsync_directory(self.pending_dir)

    def _recover_pending(self) -> None:
        paths = sorted(self.pending_dir.glob("*.json")) if self.pending_dir.exists() else []
        if len(paths) > 1:
            raise AgentStateError("current has more than one pending state transaction")
        if not paths:
            return
        path = paths[0]
        try:
            pending = PendingTransaction.model_validate_json(path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"current pending transaction is invalid: {path}: {exc}") from exc
        if sha256_json(pending.next_state.model_dump(mode="json")) != pending.next_state_sha256:
            raise AgentStateError("current pending next-state checksum mismatch")

        state = self._read_state(optional=True)
        events = self.load_events()
        committed = next(
            (event for event in events if event.transaction_id == pending.event.transaction_id),
            None,
        )
        if committed is not None and committed != pending.event:
            raise AgentStateError("current pending transaction differs from its committed event")
        if state is None or state.sequence == pending.previous_sequence:
            _atomic_json(self.state_path, pending.next_state.model_dump(mode="json"))
            state = pending.next_state
        elif state.sequence != pending.event.sequence:
            raise AgentStateError("current pending transaction cannot reconcile the current state")
        if state.identity.run_uuid != pending.run_uuid:
            raise AgentStateError("current pending transaction belongs to a different run")
        if sha256_json(state.model_dump(mode="json")) != pending.next_state_sha256:
            raise AgentStateError("current state differs from pending transaction next state")
        if committed is None:
            if len(events) != pending.previous_sequence:
                raise AgentStateError("current trace position cannot accept the pending event")
            _append_event(self.trace_path, pending.event)
        path.unlink()
        _fsync_directory(self.pending_dir)

    def _read_state(self, *, optional: bool = False) -> RunState | None:
        try:
            return RunState.model_validate_json(self.state_path.read_text())
        except FileNotFoundError:
            if optional:
                return None
            raise AgentStateError(f"current state is missing: {self.state_path}") from None
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"current state is invalid: {self.state_path}: {exc}") from exc

    def _fault(self, phase: str, pending: PendingTransaction) -> None:
        if self.fault_injector is not None:
            self.fault_injector(phase, pending)


def _exclusive_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)
    _fsync_directory(path.parent)


def _append_event(path: Path, event: RunEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(event.model_dump_json())
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
