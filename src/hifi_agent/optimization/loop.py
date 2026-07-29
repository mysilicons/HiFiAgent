"""Recoverable Stage 9 optimization loop over at most three rounds."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from hifi_agent.exceptions import AgentStateError, HiFiAgentError
from hifi_agent.optimization.loop_models import (
    LoopBudget,
    LoopDecisionContext,
    LoopDirective,
    LoopEvent,
    LoopPhase,
    LoopRoundRecord,
    LoopTerminalOutcome,
    OptimizationLoopState,
)
from hifi_agent.optimization.round_models import (
    ComparableRun,
    RoundComparisonContext,
)
from hifi_agent.optimization.rounds import RoundComparator
from hifi_agent.rag.models import ApprovedCandidate

ProposalProvider = Callable[[LoopDecisionContext], LoopDirective]
CandidateRunner = Callable[..., ComparableRun]


class OptimizationLoop:
    """Consume round outcomes until acceptance or a bounded stop condition."""

    def __init__(
        self,
        root: Path,
        *,
        sample_id: str,
        baseline: ComparableRun,
        proposal_provider: ProposalProvider,
        candidate_runner: CandidateRunner,
        comparison_context: RoundComparisonContext,
        budget: LoopBudget,
        max_rounds: Literal[1, 2, 3] = 3,
        max_candidates_per_round: int = 1,
        comparator: RoundComparator | None = None,
    ) -> None:
        if not 1 <= max_rounds <= 3:
            raise ValueError("Stage 9 max_rounds must be between 1 and 3")
        if not 1 <= max_candidates_per_round <= 2:
            raise ValueError("Stage 9 max_candidates_per_round must be one or two")
        if baseline.execution_status != "COMPLETED" or baseline.metrics is None:
            raise ValueError("Stage 9 baseline must be a completed comparable run")
        self.root = root.resolve()
        self.state_path = self.root / "optimization_loop_state.json"
        self.trace_path = self.root / "optimization_loop_trace.jsonl"
        self.rounds_root = self.root / "rounds"
        self.sample_id = sample_id
        self.baseline = baseline
        self.proposal_provider = proposal_provider
        self.candidate_runner = candidate_runner
        self.comparison_context = comparison_context
        self.initial_budget = budget
        self.max_rounds = max_rounds
        self.max_candidates_per_round = max_candidates_per_round
        self.comparator = comparator or RoundComparator()

    def run(self, *, resume: bool = False) -> OptimizationLoopState:
        """Run or resume until a terminal condition, persisting before every launch."""
        state = self._load_or_initialize(resume=resume)
        while state.phase != "TERMINAL":
            if state.phase == "DECIDE":
                self._decide(state)
            elif state.phase == "EXECUTE":
                self._execute_next(state)
            elif state.phase == "COMPARE":
                self._compare(state)
            else:
                raise AgentStateError(f"Unknown optimization loop phase: {state.phase}")
        return state

    def _load_or_initialize(self, *, resume: bool) -> OptimizationLoopState:
        if self.state_path.is_file():
            if not resume:
                raise AgentStateError("Optimization loop state exists; rerun with resume=True")
            state = self._load_state()
            self._validate_identity(state)
            return state
        if resume:
            raise AgentStateError("No OptimizationLoop state exists to resume")
        now = datetime.now(UTC)
        state = OptimizationLoopState(
            sample_id=self.sample_id,
            baseline_run_id=self.baseline.run_id,
            baseline_parameter_fingerprint=(self.baseline.config.parameter_fingerprint()),
            baseline_metrics_sha256=_metrics_sha256(self.baseline),
            created_at=now,
            updated_at=now,
            max_rounds=self.max_rounds,
            max_candidates_per_round=self.max_candidates_per_round,
            incumbent=self.baseline,
            seen_parameter_fingerprints=[self.baseline.config.parameter_fingerprint()],
            budget=self.initial_budget.model_copy(deep=True),
        )
        self._save(state)
        return state

    def _decide(self, state: OptimizationLoopState) -> None:
        assert state.incumbent.metrics is not None
        context = LoopDecisionContext(
            sample_id=state.sample_id,
            round_index=state.round_index,
            incumbent_run_id=state.incumbent.run_id,
            incumbent_metrics=state.incumbent.metrics,
            seen_parameter_fingerprints=state.seen_parameter_fingerprints,
            remaining_cpu_hours=max(
                state.budget.max_cpu_hours - state.budget.consumed_cpu_hours,
                0.0,
            ),
            remaining_walltime_hours=max(
                state.budget.max_walltime_hours - state.budget.consumed_walltime_hours,
                0.0,
            ),
        )
        directive = self.proposal_provider(context)
        if directive.action == "ACCEPT":
            outcome: LoopTerminalOutcome = (
                "ACCEPTED_BASELINE"
                if not state.rounds and state.incumbent.run_id == "baseline"
                else "ACCEPTED_CURRENT_INCUMBENT"
            )
            self._terminal(
                state,
                outcome,
                selected_run_id=state.incumbent.run_id,
                reason_codes=directive.reason_codes,
            )
            return
        if directive.action == "STOP":
            self._terminal(
                state,
                "STOP_RULE_DECISION",
                selected_run_id=None,
                reason_codes=directive.reason_codes,
            )
            return

        unique: list[ApprovedCandidate] = []
        local: set[str] = set()
        for candidate in directive.approved_candidates:
            fingerprint = _projected_parameter_fingerprint(state.incumbent, candidate)
            if fingerprint in state.seen_parameter_fingerprints or fingerprint in local:
                continue
            local.add(fingerprint)
            unique.append(candidate)
            if len(unique) == state.max_candidates_per_round:
                break
        if not unique:
            self._terminal(
                state,
                "NO_UNIQUE_CANDIDATE",
                selected_run_id=None,
                reason_codes=["ALL_APPROVED_PARAMETER_FINGERPRINTS_ALREADY_SEEN"],
            )
            return
        state.active_directive = directive
        state.pending_candidates = unique
        state.candidate_results = []
        state.next_candidate_index = 1
        state.active_candidate_index = None
        self._transition(
            state,
            phase_after="EXECUTE",
            action="APPROVED_CANDIDATES_READY",
            reason_codes=directive.reason_codes,
        )

    def _execute_next(self, state: OptimizationLoopState) -> None:
        if state.next_candidate_index > len(state.pending_candidates):
            self._transition(
                state,
                phase_after="COMPARE",
                action="ROUND_CANDIDATES_COMPLETED",
                reason_codes=["ALL_STARTED_CANDIDATES_COMPLETED"],
            )
            return
        budget_reason = state.budget.exhausted_reason()
        if budget_reason is not None:
            self._terminal(
                state,
                "STOP_BUDGET",
                selected_run_id=None,
                reason_codes=[budget_reason],
            )
            return

        candidate_index = state.next_candidate_index
        approved = state.pending_candidates[candidate_index - 1]
        expected_run_id = f"candidate_r{state.round_index:02d}_c{candidate_index:02d}"
        expected_parameter_fingerprint = _projected_parameter_fingerprint(
            state.incumbent,
            approved,
        )
        resume_attempt = state.active_candidate_index == candidate_index
        if not resume_attempt:
            state.active_candidate_index = candidate_index
            state.budget.candidates_started += 1
            self._event(
                state,
                phase_before="EXECUTE",
                phase_after="EXECUTE",
                action="CANDIDATE_LAUNCH_RESERVED",
                reason_codes=["BUDGET_RESERVED_BEFORE_LAUNCH"],
                candidate_index=candidate_index,
                run_id=expected_run_id,
            )
            self._save(state)
        try:
            result = self.candidate_runner(
                approved,
                round_index=state.round_index,
                candidate_index=candidate_index,
                resume=resume_attempt,
            )
        except KeyboardInterrupt:
            raise
        except HiFiAgentError as exc:
            state.last_error = str(exc)
            self._terminal(
                state,
                "STOP_EXECUTION_FAILURE",
                selected_run_id=None,
                reason_codes=["CANDIDATE_EXECUTION_FAILED"],
            )
            return
        if result.run_id != expected_run_id:
            state.last_error = (
                f"Candidate runner returned {result.run_id}; expected {expected_run_id}"
            )
            self._terminal(
                state,
                "STOP_EXECUTION_FAILURE",
                selected_run_id=None,
                reason_codes=["CANDIDATE_RUN_ID_MISMATCH"],
            )
            return
        if result.config.parameter_fingerprint() != expected_parameter_fingerprint:
            state.last_error = "Candidate runner returned parameters outside the approved delta"
            self._terminal(
                state,
                "STOP_EXECUTION_FAILURE",
                selected_run_id=None,
                reason_codes=["APPROVED_EXECUTED_PARAMETER_MISMATCH"],
            )
            return
        state.candidate_results.append(result)
        state.budget.account(result)
        state.seen_parameter_fingerprints.append(result.config.parameter_fingerprint())
        state.active_candidate_index = None
        state.next_candidate_index += 1
        self._event(
            state,
            phase_before="EXECUTE",
            phase_after="EXECUTE",
            action="CANDIDATE_COMPLETED",
            reason_codes=["CANDIDATE_AND_POST_QC_RETAINED"],
            candidate_index=candidate_index,
            run_id=result.run_id,
        )
        self._save(state)

    def _compare(self, state: OptimizationLoopState) -> None:
        directive = state.active_directive
        if directive is None or not state.candidate_results:
            raise AgentStateError("COMPARE phase lacks directive or candidate results")
        incumbent_before = state.incumbent
        round_dir = self.rounds_root / f"round_{state.round_index:02d}"
        comparison = self.comparator.compare_round(
            round_index=state.round_index,
            incumbent=incumbent_before,
            candidates=state.candidate_results,
            context=self.comparison_context,
            output_dir=round_dir,
        )
        state.rounds.append(
            LoopRoundRecord(
                round_index=state.round_index,
                incumbent_before=incumbent_before.run_id,
                directive=directive,
                candidate_results=state.candidate_results,
                comparison=comparison,
            )
        )
        if comparison.outcome == "INCUMBENT_UPDATED":
            selected = next(
                item
                for item in state.candidate_results
                if item.run_id == comparison.selected_run_id
            )
            state.incumbent = selected
            if state.round_index == state.max_rounds:
                self._terminal(
                    state,
                    "STOP_MAX_ROUNDS",
                    selected_run_id=selected.run_id,
                    reason_codes=["MAXIMUM_OPTIMIZATION_ROUNDS_COMPLETED"],
                )
                return
            state.round_index += 1
            state.active_directive = None
            state.pending_candidates = []
            state.candidate_results = []
            state.next_candidate_index = 1
            self._transition(
                state,
                phase_after="DECIDE",
                action="INCUMBENT_UPDATED_NEXT_ROUND",
                reason_codes=comparison.reason_codes,
                run_id=selected.run_id,
            )
            return
        outcome_map: dict[str, LoopTerminalOutcome] = {
            "STOP_PLATEAU": "STOP_PLATEAU",
            "STOP_CONFLICT": "STOP_CONFLICT",
            "STOP_INSUFFICIENT_METRICS": "STOP_INSUFFICIENT_METRICS",
            "STOP_EXECUTION_FAILURE": "STOP_EXECUTION_FAILURE",
            "NO_UNIQUE_CANDIDATE": "NO_UNIQUE_CANDIDATE",
        }
        self._terminal(
            state,
            outcome_map[comparison.outcome],
            selected_run_id=None,
            reason_codes=comparison.reason_codes,
        )

    def _terminal(
        self,
        state: OptimizationLoopState,
        outcome: LoopTerminalOutcome,
        *,
        selected_run_id: str | None,
        reason_codes: list[str],
    ) -> None:
        state.terminal_outcome = outcome
        state.selected_run_id = selected_run_id
        self._transition(
            state,
            phase_after="TERMINAL",
            action=outcome,
            reason_codes=reason_codes,
            run_id=selected_run_id,
        )

    def _transition(
        self,
        state: OptimizationLoopState,
        *,
        phase_after: LoopPhase,
        action: str,
        reason_codes: list[str],
        run_id: str | None = None,
    ) -> None:
        before = state.phase
        state.phase = phase_after
        self._event(
            state,
            phase_before=before,
            phase_after=phase_after,
            action=action,
            reason_codes=reason_codes,
            run_id=run_id,
        )
        self._save(state)

    def _event(
        self,
        state: OptimizationLoopState,
        *,
        phase_before: LoopPhase,
        phase_after: LoopPhase,
        action: str,
        reason_codes: list[str],
        candidate_index: int | None = None,
        run_id: str | None = None,
    ) -> None:
        state.events.append(
            LoopEvent(
                sequence=len(state.events) + 1,
                timestamp=datetime.now(UTC),
                phase_before=phase_before,
                phase_after=phase_after,
                action=action,
                round_index=state.round_index,
                candidate_index=candidate_index,
                run_id=run_id,
                reason_codes=reason_codes,
            )
        )

    def _save(self, state: OptimizationLoopState) -> None:
        state.updated_at = datetime.now(UTC)
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.state_path, state.model_dump(mode="json"))
        trace = "".join(event.model_dump_json() + "\n" for event in state.events)
        temporary = self.trace_path.with_suffix(".jsonl.tmp")
        temporary.write_text(trace)
        temporary.replace(self.trace_path)

    def _load_state(self) -> OptimizationLoopState:
        try:
            return OptimizationLoopState.model_validate_json(self.state_path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"OptimizationLoop state is invalid: {exc}") from exc

    def _validate_identity(self, state: OptimizationLoopState) -> None:
        if state.sample_id != self.sample_id:
            raise AgentStateError("OptimizationLoop sample identity mismatch")
        if (
            state.baseline_run_id != self.baseline.run_id
            or state.baseline_parameter_fingerprint != self.baseline.config.parameter_fingerprint()
            or state.baseline_metrics_sha256 != _metrics_sha256(self.baseline)
        ):
            raise AgentStateError("OptimizationLoop baseline identity mismatch")
        if state.max_rounds != self.max_rounds:
            raise AgentStateError("OptimizationLoop max-round setting changed during resume")
        if state.max_candidates_per_round != self.max_candidates_per_round:
            raise AgentStateError("OptimizationLoop candidate limit changed during resume")
        if state.events:
            sequences = [event.sequence for event in state.events]
            if sequences != list(range(1, len(sequences) + 1)):
                raise AgentStateError("OptimizationLoop event sequence is not contiguous")


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _projected_parameter_fingerprint(
    incumbent: ComparableRun,
    approved: ApprovedCandidate,
) -> str:
    parameters = incumbent.config.parameters.model_dump(mode="json")
    parameters.update(approved.approved_parameters.model_dump(exclude_none=True))
    payload = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _metrics_sha256(run: ComparableRun) -> str:
    if run.metrics is None:
        raise ValueError("Comparable run has no metrics")
    payload = json.dumps(
        run.metrics.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
