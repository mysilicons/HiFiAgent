"""Recoverable explicit Agent controller with hard safety budgets."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import yaml
from pydantic import ValidationError

from hifi_agent.agent.models import (
    TERMINAL_STATES,
    AgentRunState,
    AgentState,
    BudgetLedger,
    RetryKind,
    TerminalOutcome,
    TransitionEvent,
)
from hifi_agent.agent.planner import Planner
from hifi_agent.agent.state import AgentStateStore, validate_transition
from hifi_agent.agent.tools import AgentTools
from hifi_agent.exceptions import (
    HiFiAgentError,
    InputValidationError,
    RuleEvaluationError,
    ToolExecutionError,
)
from hifi_agent.rules.models import RuleDecision
from hifi_agent.schemas.sample import AgentConfig, SampleConfig

Clock = Callable[[], datetime]


class AgentController:
    """Drive V1 workflow artifacts through an explicit, persistent state graph."""

    def __init__(
        self,
        run_dir: Path,
        config_path: Path,
        tools: AgentTools,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.run_dir = run_dir.resolve()
        self.config_path = config_path.resolve()
        self.tools = tools
        self.clock = clock or (lambda: datetime.now(UTC))
        self.store = AgentStateStore(self.run_dir / "05_agent")
        self.planner = Planner()
        self._validated_config: SampleConfig | None = None

    def run(self, *, resume: bool = False, max_steps: int | None = None) -> AgentRunState:
        """Execute or resume until REPORT; max_steps supports interruption tests."""
        state = self.store.load() if resume else self._initialize_state()
        if state.state == AgentState.REPORT:
            state.report_path = self.tools.render_report(state)
            return state
        steps = 0
        while True:
            if max_steps is not None and steps >= max_steps:
                return state
            state = self._step(state)
            steps += 1
            if state.state == AgentState.REPORT:
                return state

    def _initialize_state(self) -> AgentRunState:
        sample_id, agent_config = _bootstrap_config(self.config_path, self.run_dir.name)
        state = AgentRunState(
            sample_id=sample_id,
            run_dir=self.run_dir,
            config_path=self.config_path,
            budget=BudgetLedger(
                max_retry_rounds=agent_config.max_retry_rounds,
                max_candidates_per_round=agent_config.max_candidates_per_round,
                max_tool_retries=agent_config.max_tool_retries,
                max_cpu_hours=agent_config.max_cpu_hours,
                max_walltime_hours=agent_config.max_walltime_hours,
            ),
        )
        event = TransitionEvent(
            sequence=1,
            timestamp=self.clock(),
            state_before=None,
            state_after=AgentState.INPUT_VALIDATION,
            action="INITIALIZE_AGENT",
            reason_codes=["AGENT_RUN_STARTED"],
        )
        self.store.initialize(state, event)
        return state

    def _step(self, state: AgentRunState) -> AgentRunState:
        handlers = {
            AgentState.INPUT_VALIDATION: self._validate_input,
            AgentState.PRE_QC: self._pre_qc,
            AgentState.QC_REVIEW: self._review_qc,
            AgentState.ASSEMBLY_BASELINE: self._assemble_baseline,
            AgentState.POST_QC: self._post_qc,
            AgentState.EVALUATE: self._evaluate,
            AgentState.PLAN_RETRY: self._plan_retry,
            AgentState.ASSEMBLY_CANDIDATE: self._assemble_candidate,
        }
        if state.state in TERMINAL_STATES:
            return self._report(state)
        handler = handlers[state.state]
        return handler(state)

    def _validate_input(self, state: AgentRunState) -> AgentRunState:
        try:
            validation = self.tools.validate_input(self.config_path)
        except HiFiAgentError as exc:
            state.last_error = str(exc)
            return self._transition(
                state,
                AgentState.FAILED_INPUT,
                "REJECT_INPUT",
                ["INPUT_VALIDATION_FAILED"],
                evidence={"error": str(exc)},
            )
        self._validated_config = validation.config
        state.sample_id = validation.config.sample_id
        return self._transition(
            state,
            AgentState.PRE_QC,
            "VALIDATE_INPUT",
            ["INPUT_VALIDATION_PASSED"],
        )

    def _pre_qc(self, state: AgentRunState) -> AgentRunState:
        config = self._get_validated_config()
        try:
            metrics = self.tools.run_pre_qc(config)
        except ToolExecutionError as exc:
            return self._tool_failure(state, "PRE_QC", exc)
        state.pre_qc_metrics = metrics
        return self._transition(
            state,
            AgentState.QC_REVIEW,
            "RUN_PRE_QC",
            ["PRE_QC_METRICS_AVAILABLE"],
            evidence={
                "input_status": metrics.input_status,
                "estimated_coverage": metrics.estimated_coverage,
                "read_count": metrics.read_count,
            },
        )

    def _review_qc(self, state: AgentRunState) -> AgentRunState:
        metrics = state.pre_qc_metrics
        if metrics is None:
            return self._transition(
                state,
                AgentState.STOP_INSUFFICIENT_METADATA,
                "STOP_PRE_QC_MISSING",
                ["PRE_QC_METRICS_MISSING"],
            )
        if metrics.read_count is None or metrics.total_bases is None:
            return self._transition(
                state,
                AgentState.STOP_INSUFFICIENT_METADATA,
                "STOP_PRE_QC_INCOMPLETE",
                ["PRE_QC_CORE_METRICS_MISSING"],
            )
        if (
            metrics.input_status != "PASS"
            or metrics.read_count <= 0
            or metrics.total_bases <= 0
            or (metrics.estimated_coverage is not None and metrics.estimated_coverage < 15.0)
        ):
            return self._transition(
                state,
                AgentState.STOP_LOW_QUALITY,
                "STOP_LOW_QUALITY_INPUT",
                ["PRE_QC_MINIMUM_NOT_MET"],
                evidence={"estimated_coverage": metrics.estimated_coverage},
            )
        return self._transition(
            state,
            AgentState.ASSEMBLY_BASELINE,
            "PLAN_BASELINE",
            ["PRE_QC_GATE_PASSED"],
        )

    def _assemble_baseline(self, state: AgentRunState) -> AgentRunState:
        metrics = state.pre_qc_metrics
        if metrics is None:
            raise InputValidationError("PRE_QC metrics disappeared from Agent state")
        if state.baseline_config is None:
            state.baseline_config = self.tools.plan_baseline(metrics)
        state.active_config = state.baseline_config
        budget_reason = state.budget.exhausted_reason()
        if budget_reason is not None:
            return self._budget_stop(state, budget_reason)
        try:
            artifact = self.tools.run_assembly(state.baseline_config)
        except ToolExecutionError as exc:
            return self._tool_failure(state, "ASSEMBLY_BASELINE", exc)
        state.active_artifact = artifact
        state.budget.account(artifact)
        fingerprint = state.baseline_config.parameter_fingerprint()
        _append_unique(state.started_parameter_fingerprints, fingerprint)
        _append_unique(state.completed_run_ids, artifact.run_id)
        return self._transition(
            state,
            AgentState.POST_QC,
            "RUN_BASELINE_ASSEMBLY",
            ["BASELINE_ASSEMBLY_AVAILABLE"],
            evidence={"cpu_hours": artifact.cpu_hours, "walltime_hours": artifact.walltime_hours},
            run_id=artifact.run_id,
            parameter_fingerprint=fingerprint,
        )

    def _post_qc(self, state: AgentRunState) -> AgentRunState:
        artifact = state.active_artifact
        if artifact is None:
            raise ToolExecutionError("Active assembly artifact is absent from Agent state")
        try:
            metrics = self.tools.run_post_qc(artifact)
        except ToolExecutionError as exc:
            return self._tool_failure(state, f"POST_QC:{artifact.run_id}", exc)
        state.active_metrics = metrics
        state.active_metrics_path = (
            self.run_dir / "03_post_qc" / artifact.run_id / "assembly_metrics.json"
        )
        return self._transition(
            state,
            AgentState.EVALUATE,
            "RUN_POST_QC",
            ["POST_QC_METRICS_AVAILABLE"],
            run_id=artifact.run_id,
        )

    def _evaluate(self, state: AgentRunState) -> AgentRunState:
        artifact = state.active_artifact
        if artifact is None:
            raise RuleEvaluationError("Cannot evaluate without an active assembly artifact")
        metrics = state.active_metrics
        if metrics is None:
            raise RuleEvaluationError("Cannot evaluate without retained post-QC metrics")
        try:
            decision = self.tools.evaluate(metrics, state.completed_run_ids)
        except ToolExecutionError as exc:
            return self._tool_failure(state, f"EVALUATE:{artifact.run_id}", exc)
        except RuleEvaluationError as exc:
            state.last_error = str(exc)
            return self._transition(
                state,
                AgentState.STOP_INSUFFICIENT_METADATA,
                "STOP_RULE_EVALUATION",
                ["RULE_EVIDENCE_INSUFFICIENT"],
                evidence={"error": str(exc)},
                run_id=artifact.run_id,
            )
        state.latest_decision = decision
        target = _decision_target(decision)
        return self._transition(
            state,
            target,
            decision.action,
            decision.reason_codes,
            evidence=decision.evidence,
            run_id=artifact.run_id,
        )

    def _plan_retry(self, state: AgentRunState) -> AgentRunState:
        decision = state.latest_decision
        baseline = state.baseline_config
        if decision is None or baseline is None:
            return self._budget_stop(state, "RETRY_PLAN_CONTEXT_MISSING")
        if not state.pending_candidates:
            if state.budget.optimization_rounds_started >= state.budget.max_retry_rounds:
                return self._budget_stop(state, "OPTIMIZATION_ROUND_BUDGET_EXCEEDED")
            optimization_round = state.budget.optimization_rounds_started + 1
            state.pending_candidates = self.planner.propose_candidates(
                decision,
                baseline,
                optimization_round=optimization_round,
                max_candidates=state.budget.max_candidates_per_round,
                seen_fingerprints=set(state.started_parameter_fingerprints),
            )
            if not state.pending_candidates:
                return self._budget_stop(state, "NO_UNIQUE_PARAMETER_CANDIDATE")
        candidate = state.pending_candidates.pop(0)
        round_key = str(candidate.optimization_round)
        started = state.budget.candidates_started_by_round.get(round_key, 0)
        if started >= state.budget.max_candidates_per_round:
            return self._budget_stop(state, "CANDIDATE_COUNT_BUDGET_EXCEEDED")
        estimate_cpu = state.active_artifact.cpu_hours if state.active_artifact else 0.0
        estimate_wall = state.active_artifact.walltime_hours if state.active_artifact else 0.0
        budget_reason = state.budget.exhausted_reason(
            estimated_cpu=estimate_cpu,
            estimated_wall=estimate_wall,
        )
        if budget_reason is not None:
            return self._budget_stop(state, budget_reason)
        fingerprint = candidate.parameter_fingerprint()
        if fingerprint in state.started_parameter_fingerprints:
            return self._budget_stop(state, "DUPLICATE_PARAMETER_CANDIDATE")
        state.active_config = candidate
        state.active_artifact = None
        state.budget.optimization_rounds_started = max(
            state.budget.optimization_rounds_started,
            candidate.optimization_round,
        )
        state.budget.candidates_started_by_round[round_key] = started + 1
        state.started_parameter_fingerprints.append(fingerprint)
        return self._transition(
            state,
            AgentState.ASSEMBLY_CANDIDATE,
            "START_PARAMETER_OPTIMIZATION",
            ["UNIQUE_CANDIDATE_WITHIN_BUDGET"],
            retry_kind="PARAMETER_OPTIMIZATION",
            run_id=candidate.run_id,
            parameter_fingerprint=fingerprint,
        )

    def _assemble_candidate(self, state: AgentRunState) -> AgentRunState:
        candidate = state.active_config
        if candidate is None or candidate.retry_kind != "PARAMETER_OPTIMIZATION":
            return self._budget_stop(state, "ACTIVE_CANDIDATE_MISSING")
        try:
            artifact = self.tools.run_assembly(candidate)
        except ToolExecutionError as exc:
            return self._tool_failure(state, f"ASSEMBLY_CANDIDATE:{candidate.run_id}", exc)
        state.active_artifact = artifact
        state.budget.account(artifact)
        _append_unique(state.completed_run_ids, artifact.run_id)
        return self._transition(
            state,
            AgentState.POST_QC,
            "RUN_CANDIDATE_ASSEMBLY",
            ["CANDIDATE_ASSEMBLY_AVAILABLE"],
            retry_kind="PARAMETER_OPTIMIZATION",
            evidence={"cpu_hours": artifact.cpu_hours, "walltime_hours": artifact.walltime_hours},
            run_id=artifact.run_id,
            parameter_fingerprint=candidate.parameter_fingerprint(),
        )

    def _report(self, state: AgentRunState) -> AgentRunState:
        state.report_path = self.tools.render_report(state)
        return self._transition(
            state,
            AgentState.REPORT,
            "RENDER_STAGE9_SUMMARY",
            ["TERMINAL_OUTCOME_RECORDED"],
            evidence={"terminal_outcome": state.terminal_outcome},
        )

    def _tool_failure(
        self,
        state: AgentRunState,
        step_key: str,
        error: ToolExecutionError,
    ) -> AgentRunState:
        attempts = state.budget.tool_retry_counts.get(step_key, 0)
        state.last_error = str(error)
        if attempts < state.budget.max_tool_retries:
            state.budget.tool_retry_counts[step_key] = attempts + 1
            return self._transition(
                state,
                state.state,
                "RETRY_TOOL_FAILURE",
                ["WORKFLOW_TOOL_FAILURE", "TOOL_RETRY_WITHOUT_PARAMETER_CHANGE"],
                retry_kind="TOOL_FAILURE",
                evidence={"tool_step": step_key, "error": str(error)},
                run_id=state.active_config.run_id if state.active_config else None,
                parameter_fingerprint=(
                    state.active_config.parameter_fingerprint() if state.active_config else None
                ),
            )
        return self._transition(
            state,
            AgentState.FAILED_TOOL_EXECUTION,
            "STOP_TOOL_RETRIES_EXHAUSTED",
            ["WORKFLOW_TOOL_FAILURE", "TOOL_RETRY_BUDGET_EXCEEDED"],
            evidence={"tool_step": step_key, "error": str(error)},
            run_id=state.active_config.run_id if state.active_config else None,
        )

    def _budget_stop(self, state: AgentRunState, reason: str) -> AgentRunState:
        return self._transition(
            state,
            AgentState.STOP_BUDGET_EXCEEDED,
            "STOP_ASSEMBLY_BUDGET",
            [reason, "NO_ADDITIONAL_ASSEMBLY_STARTED"],
            evidence={
                "consumed_cpu_hours": state.budget.consumed_cpu_hours,
                "max_cpu_hours": state.budget.max_cpu_hours,
                "consumed_walltime_hours": state.budget.consumed_walltime_hours,
                "max_walltime_hours": state.budget.max_walltime_hours,
            },
        )

    def _transition(
        self,
        state: AgentRunState,
        target: AgentState,
        action: str,
        reason_codes: list[str],
        *,
        evidence: dict[str, bool | int | float | str | None] | None = None,
        retry_kind: RetryKind = "NONE",
        run_id: str | None = None,
        parameter_fingerprint: str | None = None,
    ) -> AgentRunState:
        before = state.state
        validate_transition(before, target)
        state.state = target
        if target in TERMINAL_STATES:
            state.terminal_outcome = cast(TerminalOutcome, target.value)
        event = TransitionEvent(
            sequence=state.transition_sequence + 1,
            timestamp=self.clock(),
            state_before=before,
            state_after=target,
            action=action,
            reason_codes=reason_codes,
            evidence=evidence or {},
            retry_kind=retry_kind,
            run_id=run_id,
            parameter_fingerprint=parameter_fingerprint,
        )
        self.store.persist_transition(state, event)
        return state

    def _get_validated_config(self) -> SampleConfig:
        if self._validated_config is None:
            validation = self.tools.validate_input(self.config_path)
            self._validated_config = validation.config
        return self._validated_config


def _bootstrap_config(config_path: Path, fallback_sample_id: str) -> tuple[str, AgentConfig]:
    try:
        data = yaml.safe_load(config_path.read_text())
        if not isinstance(data, dict):
            return fallback_sample_id, AgentConfig()
        sample_id = data.get("sample_id")
        agent_data = data.get("agent", {})
        return (
            sample_id if isinstance(sample_id, str) and sample_id else fallback_sample_id,
            AgentConfig.model_validate(agent_data),
        )
    except (OSError, yaml.YAMLError, ValidationError):
        return fallback_sample_id, AgentConfig()


def _decision_target(decision: RuleDecision) -> AgentState:
    if decision.decision == "BASELINE":
        return AgentState.ACCEPTED
    if decision.decision == "RETRY":
        return AgentState.PLAN_RETRY
    if decision.action == "STOP_LOW_COVERAGE_SEARCH":
        return AgentState.STOP_LOW_QUALITY
    if decision.action in {"STOP_INSUFFICIENT_CORE_METRICS", "STOP_INSUFFICIENT_EVIDENCE"}:
        return AgentState.STOP_INSUFFICIENT_METADATA
    if decision.action == "STOP_EVALUATION_INCOMPLETE":
        return AgentState.FAILED_TOOL_EXECUTION
    return AgentState.STOP_UNCERTAIN


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
