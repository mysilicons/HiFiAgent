"""Atomic and recoverable V2 orchestration state persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import ValidationError

from hifi_agent.exceptions import AgentStateError, IllegalStateTransitionError
from hifi_agent.orchestration.models import AssemblyEvent, AssemblyRunState, AssemblyState

LEGAL_TRANSITIONS: dict[AssemblyState, frozenset[AssemblyState]] = {
    AssemblyState.INPUT_VALIDATION: frozenset({AssemblyState.BASELINE_EXECUTION}),
    AssemblyState.BASELINE_EXECUTION: frozenset(
        {AssemblyState.BASELINE_EXECUTION, AssemblyState.BASELINE_EVALUATION}
    ),
    AssemblyState.BASELINE_EVALUATION: frozenset(
        {AssemblyState.CANDIDATE_EXECUTION, AssemblyState.REPORT}
    ),
    AssemblyState.CANDIDATE_EXECUTION: frozenset(
        {AssemblyState.CANDIDATE_EXECUTION, AssemblyState.REPORT}
    ),
    AssemblyState.REPORT: frozenset(),
}


def validate_assembly_transition(before: AssemblyState, after: AssemblyState) -> None:
    """Reject transitions outside the explicit Stage 3 graph."""
    if after not in LEGAL_TRANSITIONS[before]:
        allowed = ", ".join(sorted(state.value for state in LEGAL_TRANSITIONS[before]))
        raise IllegalStateTransitionError(
            f"Illegal V2 assembly transition {before.value} -> {after.value}; "
            f"allowed: {allowed or '<none>'}"
        )


class AssemblyStateStore:
    """Persist a V2 snapshot first and append its recoverable event second."""

    def __init__(self, run_dir: Path) -> None:
        self.directory = run_dir.resolve() / "05_agent/v2"
        self.state_path = self.directory / "run_state.json"
        self.trace_path = self.directory / "event_trace.jsonl"

    def initialize(self, state: AssemblyRunState, event: AssemblyEvent) -> None:
        """Create state and trace without overwriting a prior run."""
        if self.state_path.exists() or self.trace_path.exists():
            raise AgentStateError("V2 assembly state already exists; use --resume")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.persist_transition(state, event)

    def persist_transition(self, state: AssemblyRunState, event: AssemblyEvent) -> None:
        """Atomically replace state, then append and fsync its event."""
        state.transition_sequence = event.sequence
        state.last_event = event
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(state.model_dump_json(indent=2) + "\n")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(self.state_path)
        with self.trace_path.open("a") as handle:
            handle.write(event.model_dump_json())
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def load(self) -> AssemblyRunState:
        """Load state, validate trace, and repair a one-event crash window."""
        try:
            state = AssemblyRunState.model_validate_json(self.state_path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(
                f"V2 assembly state is invalid: {self.state_path}: {exc}"
            ) from exc
        events = self._load_events()
        last_sequence = events[-1].sequence if events else 0
        if last_sequence > state.transition_sequence:
            raise AgentStateError("V2 event trace is ahead of run state")
        if last_sequence < state.transition_sequence:
            if last_sequence != state.transition_sequence - 1 or state.last_event is None:
                raise AgentStateError("V2 event trace has an unrecoverable gap")
            with self.trace_path.open("a") as handle:
                handle.write(state.last_event.model_dump_json() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return state

    def _load_events(self) -> list[AssemblyEvent]:
        if not self.trace_path.is_file():
            return []
        events: list[AssemblyEvent] = []
        for line_number, line in enumerate(self.trace_path.read_text().splitlines(), start=1):
            if not line:
                continue
            try:
                events.append(AssemblyEvent.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise AgentStateError(
                    f"V2 event trace line {line_number} is invalid: {exc}"
                ) from exc
        observed = [event.sequence for event in events]
        expected = list(range(1, len(events) + 1))
        if observed != expected:
            raise AgentStateError(
                f"V2 event sequence is not contiguous: expected {expected}, observed {observed}"
            )
        return events
