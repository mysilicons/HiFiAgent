"""Unified Stage 3 controller with real baseline/candidate execution and resume."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from hifi_agent.agent.models import AssemblyConfig, PreQcMetrics
from hifi_agent.agent.planner import Planner
from hifi_agent.config import ConfigValidationResult, validate_config_file
from hifi_agent.exceptions import AgentStateError, HiFiAgentError, ToolExecutionError
from hifi_agent.executors.nextflow import run_candidate_workflow, run_phase3_workflow
from hifi_agent.orchestration.history import AttemptHistoryStore
from hifi_agent.orchestration.models import (
    AssemblyEvent,
    AssemblyRunState,
    AssemblyState,
    AttemptIdentity,
    RoundRecord,
)
from hifi_agent.orchestration.state import AssemblyStateStore, validate_assembly_transition
from hifi_agent.qc import build_qc_feature_bundle
from hifi_agent.rules import load_default_rule_engine, load_rule_context
from hifi_agent.rules.models import RuleDecision
from hifi_agent.schemas.sample import SampleConfig


class AssemblyTools(Protocol):
    """Read/execute boundary for the V2 controller."""

    def validate(self, config_path: Path) -> ConfigValidationResult:
        """Validate config and inputs."""

    def baseline_complete(self, config: SampleConfig) -> bool:
        """Return whether all baseline outputs already exist."""

    def execute_baseline(self, config: SampleConfig, *, resume: bool) -> None:
        """Execute the real baseline workflow."""

    def evaluate_baseline(self, run_dir: Path) -> RuleDecision:
        """Load baseline evidence and return a rule decision without rerunning post-QC."""

    def materialize_qc_features(self, config: SampleConfig) -> Path:
        """Build or deterministically replace the cheap V2 QC feature bundle."""

    def plan_candidate(self, config: SampleConfig, decision: RuleDecision) -> AssemblyConfig | None:
        """Return the first bounded Stage 3 candidate."""

    def candidate_complete(self, run_dir: Path, candidate: AssemblyConfig) -> bool:
        """Return whether candidate assembly and metrics already exist."""

    def execute_candidate(self, run_dir: Path, candidate: AssemblyConfig, *, resume: bool) -> None:
        """Execute a real candidate and common post-QC."""

    def baseline_artifacts(self, run_dir: Path) -> dict[str, Path]:
        """Return baseline artifacts for immutable history."""

    def candidate_artifacts(self, run_dir: Path, candidate: AssemblyConfig) -> dict[str, Path]:
        """Return candidate artifacts for immutable history."""

    def render_summary(self, state: AssemblyRunState) -> Path:
        """Write the Stage 3 machine-readable summary."""


class ExecutingAssemblyTools:
    """Real V2 adapter: reads completed evidence and executes missing workflows."""

    def __init__(self) -> None:
        self.planner = Planner()

    def validate(self, config_path: Path) -> ConfigValidationResult:
        """Validate inputs and materialize the standard metadata receipt."""
        return validate_config_file(config_path)

    def baseline_complete(self, config: SampleConfig) -> bool:
        """Check the complete baseline/post-QC artifact contract."""
        artifacts = self.baseline_artifacts(config.outdir)
        return all(
            path.is_file() for role, path in artifacts.items() if role != "qc_feature_bundle"
        )

    def execute_baseline(self, config: SampleConfig, *, resume: bool) -> None:
        """Run the real baseline workflow through common post-QC."""
        run_phase3_workflow(config, resume=resume)

    def evaluate_baseline(self, run_dir: Path) -> RuleDecision:
        """Evaluate already materialized baseline evidence without rerunning tools."""
        return load_default_rule_engine().evaluate(load_rule_context(run_dir))

    def materialize_qc_features(self, config: SampleConfig) -> Path:
        """Build the confidence-aware V2 QC feature bundle and LLM summary."""
        build_qc_feature_bundle(config.outdir)
        return config.outdir / "01_pre_qc/qc_feature_bundle.json"

    def plan_candidate(self, config: SampleConfig, decision: RuleDecision) -> AssemblyConfig | None:
        """Plan the first unique rule-authorized candidate for Stage 3."""
        raw_path = config.outdir / "01_pre_qc/raw_metrics.json"
        try:
            pre_qc = PreQcMetrics.model_validate_json(raw_path.read_text())
        except (OSError, ValidationError) as exc:
            raise ToolExecutionError(f"Pre-QC metrics are invalid: {raw_path}: {exc}") from exc
        baseline = self.planner.plan_baseline(config, pre_qc)
        candidates = self.planner.propose_candidates(
            decision,
            baseline,
            optimization_round=1,
            max_candidates=1,
            seen_fingerprints={baseline.parameter_fingerprint()},
        )
        return candidates[0] if candidates else None

    def candidate_complete(self, run_dir: Path, candidate: AssemblyConfig) -> bool:
        """Check the complete candidate/post-QC/parameter-contract artifact set."""
        return all(path.is_file() for path in self.candidate_artifacts(run_dir, candidate).values())

    def execute_candidate(self, run_dir: Path, candidate: AssemblyConfig, *, resume: bool) -> None:
        """Run one real rule-authorized candidate through common post-QC."""
        run_candidate_workflow(run_dir, candidate, resume=resume)

    def baseline_artifacts(self, run_dir: Path) -> dict[str, Path]:
        """Return required real baseline artifacts by stable role."""
        return {
            "assembly_manifest": run_dir / "02_assembly/baseline/metadata/assembly_manifest.json",
            "primary_fasta": run_dir / "02_assembly/baseline/fasta/baseline.primary.fa",
            "post_qc_metrics": run_dir / "03_post_qc/baseline/assembly_metrics.json",
            "raw_metrics": run_dir / "01_pre_qc/raw_metrics.json",
            "qc_feature_bundle": run_dir / "01_pre_qc/qc_feature_bundle.json",
        }

    def candidate_artifacts(self, run_dir: Path, candidate: AssemblyConfig) -> dict[str, Path]:
        """Return required real candidate artifacts by stable role."""
        return {
            "assembly_manifest": run_dir
            / f"02_assembly/{candidate.run_id}/metadata/assembly_manifest.json",
            "primary_fasta": run_dir
            / f"02_assembly/{candidate.run_id}/fasta/{candidate.run_id}.primary.fa",
            "post_qc_metrics": run_dir / f"03_post_qc/{candidate.run_id}/assembly_metrics.json",
            "parameter_contract": run_dir
            / f"02_assembly/{candidate.run_id}/metadata/parameter_contract_check.json",
        }

    def render_summary(self, state: AssemblyRunState) -> Path:
        """Render the bounded Stage 3 terminal summary once."""
        output = state.identity.run_dir / "06_report/v2_stage3_summary.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "schema_version": "2.0",
                    "sample_id": state.identity.sample_id,
                    "run_uuid": state.identity.run_uuid,
                    "terminal_outcome": state.terminal_outcome,
                    "decision": (state.latest_decision.decision if state.latest_decision else None),
                    "baseline_attempt": (
                        state.baseline_attempt.model_dump(mode="json")
                        if state.baseline_attempt
                        else None
                    ),
                    "candidate_attempt": (
                        state.candidate_attempt.model_dump(mode="json")
                        if state.candidate_attempt
                        else None
                    ),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return output


class AssemblyController:
    """Execute or resume baseline and one Stage 3 rule-authorized candidate."""

    def __init__(
        self,
        config_path: Path,
        tools: AssemblyTools,
        *,
        confirm_medium_high_risk: bool = False,
    ) -> None:
        self.config_path = config_path.resolve()
        preview = validate_config_file(self.config_path, write_outputs=False).config
        self.run_dir = preview.outdir
        self.tools = tools
        self.confirm_medium_high_risk = confirm_medium_high_risk
        self.history = AttemptHistoryStore(self.run_dir)
        self.store = AssemblyStateStore(self.run_dir)
        self._config: SampleConfig | None = None

    def run(self, *, resume: bool = False, max_steps: int | None = None) -> AssemblyRunState:
        """Run to REPORT; max_steps is an internal interruption-test hook."""
        state = self.store.load() if resume else self._initialize()
        if resume:
            self.history.load_identity(verify_config=self.config_path)
            self.history.verify_history()
        if state.state == AssemblyState.REPORT:
            return state
        steps = 0
        while True:
            if max_steps is not None and steps >= max_steps:
                return state
            state = self._step(state, resume=resume)
            steps += 1
            if state.state == AssemblyState.REPORT:
                return state

    def _initialize(self) -> AssemblyRunState:
        validation = self.tools.validate(self.config_path)
        self._config = validation.config
        identity = self.history.initialize(validation.config.sample_id, self.config_path)
        state = AssemblyRunState(identity=identity, config_path=self.config_path)
        event = AssemblyEvent(
            sequence=1,
            timestamp=datetime.now(UTC),
            state_before=None,
            state_after=AssemblyState.INPUT_VALIDATION,
            action="INITIALIZE_V2_ASSEMBLY",
            reason_codes=["V2_RUN_INITIALIZED"],
        )
        self.store.initialize(state, event)
        return state

    def _step(self, state: AssemblyRunState, *, resume: bool) -> AssemblyRunState:
        if state.state == AssemblyState.INPUT_VALIDATION:
            self._config = self.tools.validate(self.config_path).config
            return self._transition(
                state,
                AssemblyState.BASELINE_EXECUTION,
                "VALIDATE_INPUT",
                ["INPUT_VALIDATION_PASSED"],
            )
        if state.state == AssemblyState.BASELINE_EXECUTION:
            return self._baseline(state, resume=resume)
        if state.state == AssemblyState.BASELINE_EVALUATION:
            return self._evaluate(state)
        if state.state == AssemblyState.CANDIDATE_EXECUTION:
            return self._candidate(state, resume=resume)
        raise AgentStateError(f"No handler for V2 assembly state: {state.state}")

    def _baseline(self, state: AssemblyRunState, *, resume: bool) -> AssemblyRunState:
        config = self._load_config()
        attempt = self.history.begin_attempt(
            kind="baseline",
            round_index=0,
            retry=state.tool_retry_counts.get("baseline", 0) > 0,
        )
        state.baseline_attempt = attempt
        if not self.history.is_complete(attempt):
            try:
                if not self.tools.baseline_complete(config):
                    self.tools.execute_baseline(config, resume=resume)
                self.tools.materialize_qc_features(config)
                self.history.complete_attempt(
                    attempt,
                    artifacts=self.tools.baseline_artifacts(self.run_dir),
                )
            except (HiFiAgentError, OSError) as exc:
                return self._tool_failure(state, "baseline", attempt, exc)
        return self._transition(
            state,
            AssemblyState.BASELINE_EVALUATION,
            "COMPLETE_BASELINE_WORKFLOW",
            ["BASELINE_AND_POST_QC_AVAILABLE"],
            run_id="baseline",
            attempt=attempt,
        )

    def _evaluate(self, state: AssemblyRunState) -> AssemblyRunState:
        decision = self.tools.evaluate_baseline(self.run_dir)
        state.latest_decision = decision
        if decision.decision != "RETRY":
            state.terminal_outcome = (
                "ACCEPTED_BASELINE" if decision.decision == "BASELINE" else "STOP_RULE_DECISION"
            )
            self.history.record_round(
                RoundRecord(
                    round_index=0,
                    incumbent_before="baseline",
                    candidate_run_ids=[],
                    attempt_ids=[
                        state.baseline_attempt.attempt_id if state.baseline_attempt else ""
                    ],
                    outcome=state.terminal_outcome,
                    incumbent_after=(
                        "baseline" if state.terminal_outcome == "ACCEPTED_BASELINE" else None
                    ),
                    stop_reason=decision.action,
                )
            )
            return self._finish(state, decision.reason_codes)
        candidate = self.tools.plan_candidate(self._load_config(), decision)
        if candidate is None:
            state.terminal_outcome = "STOP_NO_LEGAL_CANDIDATE"
            return self._finish(state, ["NO_LEGAL_CANDIDATE"])
        if candidate.requires_user_confirmation and not self.confirm_medium_high_risk:
            state.candidate_config = candidate
            state.terminal_outcome = "STOP_CONFIRMATION_REQUIRED"
            return self._finish(state, ["CANDIDATE_CONFIRMATION_REQUIRED"])
        state.candidate_config = candidate
        self.history.record_round(
            RoundRecord(
                round_index=0,
                incumbent_before="baseline",
                candidate_run_ids=[candidate.run_id],
                attempt_ids=[state.baseline_attempt.attempt_id if state.baseline_attempt else ""],
                outcome="RETRY_AUTHORIZED",
                incumbent_after="baseline",
            )
        )
        return self._transition(
            state,
            AssemblyState.CANDIDATE_EXECUTION,
            "PLAN_RULE_AUTHORIZED_CANDIDATE",
            decision.reason_codes,
            run_id=candidate.run_id,
        )

    def _candidate(self, state: AssemblyRunState, *, resume: bool) -> AssemblyRunState:
        candidate = state.candidate_config
        if candidate is None:
            raise AgentStateError("Candidate execution state has no candidate config")
        attempt = self.history.begin_attempt(
            kind="candidate",
            round_index=1,
            candidate_index=1,
            retry=state.tool_retry_counts.get("candidate", 0) > 0,
        )
        state.candidate_attempt = attempt
        if not self.history.is_complete(attempt):
            try:
                if not self.tools.candidate_complete(self.run_dir, candidate):
                    self.tools.execute_candidate(self.run_dir, candidate, resume=resume)
                self.history.complete_attempt(
                    attempt,
                    artifacts=self.tools.candidate_artifacts(self.run_dir, candidate),
                    parameter_fingerprint=candidate.parameter_fingerprint(),
                )
            except (HiFiAgentError, OSError) as exc:
                return self._tool_failure(state, "candidate", attempt, exc)
        state.terminal_outcome = "CANDIDATE_EXECUTED_STAGE3"
        self.history.record_round(
            RoundRecord(
                round_index=1,
                incumbent_before="baseline",
                candidate_run_ids=[candidate.run_id],
                attempt_ids=[attempt.attempt_id],
                outcome=state.terminal_outcome,
                incumbent_after=None,
                stop_reason="STAGE3_COMPARISON_DEFERRED_TO_STAGE8",
            )
        )
        return self._finish(state, ["CANDIDATE_AND_POST_QC_AVAILABLE"])

    def _tool_failure(
        self,
        state: AssemblyRunState,
        step: str,
        attempt: AttemptIdentity,
        error: Exception,
    ) -> AssemblyRunState:
        config = self._load_config()
        count = state.tool_retry_counts.get(step, 0)
        state.last_error = str(error)
        try:
            self.history.complete_attempt(
                attempt,
                artifacts={},
                status="FAILED",
                error=str(error),
            )
        except AgentStateError:
            pass
        if count < config.agent.max_tool_retries:
            state.tool_retry_counts[step] = count + 1
            return self._transition(
                state,
                state.state,
                "RETRY_TOOL_FAILURE",
                ["TOOL_FAILURE", "TOOL_RETRY_WITHOUT_PARAMETER_CHANGE"],
                run_id=attempt.run_id,
                attempt=attempt,
            )
        state.terminal_outcome = "STOP_TOOL_FAILURE"
        return self._finish(state, ["TOOL_RETRY_BUDGET_EXCEEDED"])

    def _finish(self, state: AssemblyRunState, reasons: Sequence[str]) -> AssemblyRunState:
        state.report_path = self.tools.render_summary(state)
        return self._transition(
            state,
            AssemblyState.REPORT,
            "RENDER_STAGE3_SUMMARY",
            list(reasons) or ["TERMINAL_OUTCOME_RECORDED"],
        )

    def _transition(
        self,
        state: AssemblyRunState,
        target: AssemblyState,
        action: str,
        reasons: list[str],
        *,
        run_id: str | None = None,
        attempt: AttemptIdentity | None = None,
    ) -> AssemblyRunState:
        before = state.state
        validate_assembly_transition(before, target)
        state.state = target
        event = AssemblyEvent(
            sequence=state.transition_sequence + 1,
            timestamp=datetime.now(UTC),
            state_before=before,
            state_after=target,
            action=action,
            reason_codes=reasons,
            run_id=run_id,
            attempt_id=attempt.attempt_id if attempt else None,
        )
        self.store.persist_transition(state, event)
        return state

    def _load_config(self) -> SampleConfig:
        if self._config is None:
            self._config = validate_config_file(self.config_path, write_outputs=False).config
        return self._config
