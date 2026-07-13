"""State graph validation and crash-recoverable Agent persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import ValidationError

from hifi_agent.agent.models import AgentRunState, AgentState, TransitionEvent
from hifi_agent.exceptions import AgentStateError, IllegalStateTransitionError

LEGAL_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.INPUT_VALIDATION: frozenset({AgentState.PRE_QC, AgentState.FAILED_INPUT}),
    AgentState.PRE_QC: frozenset(
        {AgentState.PRE_QC, AgentState.QC_REVIEW, AgentState.FAILED_TOOL_EXECUTION}
    ),
    AgentState.QC_REVIEW: frozenset(
        {
            AgentState.ASSEMBLY_BASELINE,
            AgentState.STOP_LOW_QUALITY,
            AgentState.STOP_INSUFFICIENT_METADATA,
        }
    ),
    AgentState.ASSEMBLY_BASELINE: frozenset(
        {
            AgentState.ASSEMBLY_BASELINE,
            AgentState.POST_QC,
            AgentState.STOP_BUDGET_EXCEEDED,
            AgentState.FAILED_TOOL_EXECUTION,
        }
    ),
    AgentState.POST_QC: frozenset(
        {AgentState.POST_QC, AgentState.EVALUATE, AgentState.FAILED_TOOL_EXECUTION}
    ),
    AgentState.EVALUATE: frozenset(
        {
            AgentState.ACCEPTED,
            AgentState.PLAN_RETRY,
            AgentState.STOP_LOW_QUALITY,
            AgentState.STOP_INSUFFICIENT_METADATA,
            AgentState.STOP_UNCERTAIN,
            AgentState.FAILED_TOOL_EXECUTION,
        }
    ),
    AgentState.PLAN_RETRY: frozenset(
        {AgentState.ASSEMBLY_CANDIDATE, AgentState.STOP_BUDGET_EXCEEDED}
    ),
    AgentState.ASSEMBLY_CANDIDATE: frozenset(
        {
            AgentState.ASSEMBLY_CANDIDATE,
            AgentState.POST_QC,
            AgentState.STOP_BUDGET_EXCEEDED,
            AgentState.FAILED_TOOL_EXECUTION,
        }
    ),
    AgentState.ACCEPTED: frozenset({AgentState.REPORT}),
    AgentState.FAILED_INPUT: frozenset({AgentState.REPORT}),
    AgentState.STOP_LOW_QUALITY: frozenset({AgentState.REPORT}),
    AgentState.STOP_INSUFFICIENT_METADATA: frozenset({AgentState.REPORT}),
    AgentState.STOP_UNCERTAIN: frozenset({AgentState.REPORT}),
    AgentState.STOP_BUDGET_EXCEEDED: frozenset({AgentState.REPORT}),
    AgentState.FAILED_TOOL_EXECUTION: frozenset({AgentState.REPORT}),
    AgentState.REPORT: frozenset(),
}


def validate_transition(state_before: AgentState, state_after: AgentState) -> None:
    """Raise a precise exception for an illegal state transition."""
    if state_after not in LEGAL_TRANSITIONS[state_before]:
        allowed = ", ".join(sorted(state.value for state in LEGAL_TRANSITIONS[state_before]))
        raise IllegalStateTransitionError(
            f"Illegal Agent transition {state_before.value} -> {state_after.value}; "
            f"allowed: {allowed or '<none>'}"
        )


class AgentStateStore:
    """Persist atomic snapshots and an append-only transition trace."""

    def __init__(self, agent_dir: Path) -> None:
        self.agent_dir = agent_dir
        self.state_path = agent_dir / "agent_state.json"
        self.trace_path = agent_dir / "decision_trace.jsonl"

    def initialize(self, state: AgentRunState, event: TransitionEvent) -> None:
        """Create a new state store without overwriting an existing execution."""
        if self.state_path.exists() or self.trace_path.exists():
            raise AgentStateError(
                f"Agent state already exists in {self.agent_dir}; use resume=True to continue"
            )
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        state.last_event = event
        state.transition_sequence = event.sequence
        self._write_state(state)
        self._append_event(event)

    def persist_transition(self, state: AgentRunState, event: TransitionEvent) -> None:
        """Write the snapshot first, then append its recoverable transition event."""
        state.last_event = event
        state.transition_sequence = event.sequence
        self._write_state(state)
        self._append_event(event)

    def load(self) -> AgentRunState:
        """Load state and repair a crash between snapshot and trace writes."""
        if not self.state_path.is_file():
            raise AgentStateError(f"Agent state file does not exist: {self.state_path}")
        try:
            state = AgentRunState.model_validate_json(self.state_path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"Agent state is invalid: {self.state_path}: {exc}") from exc
        trace = self._load_trace()
        last_trace_sequence = trace[-1].sequence if trace else 0
        if last_trace_sequence > state.transition_sequence:
            raise AgentStateError(
                "decision_trace.jsonl is ahead of agent_state.json; manual audit is required"
            )
        if last_trace_sequence < state.transition_sequence:
            if last_trace_sequence != state.transition_sequence - 1:
                raise AgentStateError("Agent trace is missing more than one recoverable event")
            if state.last_event is None or state.last_event.sequence != state.transition_sequence:
                raise AgentStateError("Agent snapshot cannot repair its missing trace event")
            self._append_event(state.last_event)
        return state

    def _write_state(self, state: AgentRunState) -> None:
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(state.model_dump_json(indent=2) + "\n")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(self.state_path)

    def _append_event(self, event: TransitionEvent) -> None:
        with self.trace_path.open("a") as handle:
            handle.write(event.model_dump_json())
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _load_trace(self) -> list[TransitionEvent]:
        if not self.trace_path.is_file():
            return []
        lines = [line for line in self.trace_path.read_text().splitlines() if line]
        events: list[TransitionEvent] = []
        for line_number, line in enumerate(lines, start=1):
            try:
                events.append(TransitionEvent.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise AgentStateError(
                    f"Agent trace line {line_number} is invalid: {self.trace_path}: {exc}"
                ) from exc
        expected = list(range(1, len(events) + 1))
        observed = [event.sequence for event in events]
        if observed != expected:
            raise AgentStateError(
                f"Agent trace sequence is not contiguous: expected {expected}, observed {observed}"
            )
        return events
