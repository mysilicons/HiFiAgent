"""Auditable Stage 9 tool interface and real-artifact implementation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import ValidationError

from hifi_agent.agent.evaluator import Evaluator
from hifi_agent.agent.models import (
    AgentRunState,
    AgentState,
    AssemblyArtifact,
    AssemblyConfig,
    PreQcMetrics,
)
from hifi_agent.agent.planner import Planner
from hifi_agent.config import (
    ConfigValidationResult,
    validate_config_file,
    verify_recorded_input_checksums,
    verify_validation_receipt,
)
from hifi_agent.exceptions import InputValidationError, RuleEvaluationError, ToolExecutionError
from hifi_agent.rules import load_default_rule_engine, load_rule_context, write_rule_decision
from hifi_agent.rules.models import RuleDecision
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.schemas.sample import SampleConfig


class AgentTools(Protocol):
    """Typed tool boundary used by the explicit Agent controller."""

    def validate_input(self, config: Path) -> ConfigValidationResult:
        """Validate the user configuration and inputs."""

    def run_pre_qc(self, config: SampleConfig) -> PreQcMetrics:
        """Return normalized pre-QC metrics."""

    def plan_baseline(self, metrics: PreQcMetrics) -> AssemblyConfig:
        """Build the baseline assembly configuration."""

    def run_assembly(self, config: AssemblyConfig) -> AssemblyArtifact:
        """Return a completed assembly artifact or raise a tool failure."""

    def run_post_qc(self, artifact: AssemblyArtifact) -> AssemblyMetrics:
        """Return normalized post-QC metrics for an assembly artifact."""

    def evaluate(self, metrics: AssemblyMetrics, history: Sequence[str]) -> RuleDecision:
        """Evaluate evidence with deterministic expert rules."""

    def propose_candidates(self, decision: RuleDecision) -> list[AssemblyConfig]:
        """Return bounded, deduplicated assembly candidates."""

    def render_report(self, run_state: AgentRunState) -> Path:
        """Write the Stage 9 execution summary."""


class ExistingRunAgentTools:
    """Execute Stage 9 against genuine retained workflow artifacts."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.planner = Planner()
        self.evaluator = Evaluator(load_default_rule_engine())
        self.config: SampleConfig | None = None
        self.baseline: AssemblyConfig | None = None
        self.optimization_round = 1
        self.max_candidates = 2
        self.seen_fingerprints: set[str] = set()

    def validate_input(self, config: Path) -> ConfigValidationResult:
        """Validate real inputs and verify the retained validation receipt/checksums."""
        result = validate_config_file(config, write_outputs=False)
        receipt = self.run_dir / "00_metadata" / "validation_receipt.json"
        verify_validation_receipt(result.config, receipt)
        verify_recorded_input_checksums(self.run_dir / "00_metadata" / "input_checksums.tsv")
        self.config = result.config
        self.max_candidates = result.config.agent.max_candidates_per_round
        return result

    def run_pre_qc(self, config: SampleConfig) -> PreQcMetrics:
        """Load genuine normalized pre-QC output from the workflow run."""
        path = self.run_dir / "01_pre_qc" / "raw_metrics.json"
        if not path.is_file():
            raise ToolExecutionError(f"Pre-QC artifact is missing: {path}")
        try:
            return PreQcMetrics.model_validate_json(path.read_text())
        except (OSError, ValidationError) as exc:
            raise ToolExecutionError(f"Pre-QC artifact is invalid: {path}: {exc}") from exc

    def plan_baseline(self, metrics: PreQcMetrics) -> AssemblyConfig:
        """Build and retain the fixed baseline plan."""
        if self.config is None:
            raise InputValidationError("validate_input must run before plan_baseline")
        self.baseline = self.planner.plan_baseline(self.config, metrics)
        return self.baseline

    def run_assembly(self, config: AssemblyConfig) -> AssemblyArtifact:
        """Load a real completed assembly and its measured resource usage."""
        assembly_dir = self.run_dir / "02_assembly" / config.run_id
        manifest_path = assembly_dir / "metadata" / "assembly_manifest.json"
        primary_fasta = assembly_dir / "fasta" / f"{config.run_id}.primary.fa"
        if not manifest_path.is_file() or not primary_fasta.is_file():
            raise ToolExecutionError(
                f"Assembly artifacts for `{config.run_id}` are missing; Stage 9 never simulates "
                "candidate execution"
            )
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolExecutionError(
                f"Assembly manifest is invalid: {manifest_path}: {exc}"
            ) from exc
        if not isinstance(manifest, dict):
            raise ToolExecutionError(f"Assembly manifest must be an object: {manifest_path}")
        cpu_seconds = _nonnegative_number(manifest.get("cpu_seconds"), "cpu_seconds", manifest_path)
        wall_seconds = _nonnegative_number(
            manifest.get("real_time_seconds"), "real_time_seconds", manifest_path
        )
        return AssemblyArtifact(
            run_id=config.run_id,
            manifest=manifest_path,
            primary_fasta=primary_fasta,
            cpu_hours=cpu_seconds / 3600,
            walltime_hours=wall_seconds / 3600,
        )

    def run_post_qc(self, artifact: AssemblyArtifact) -> AssemblyMetrics:
        """Load genuine post-QC metrics corresponding to the assembly run ID."""
        path = self.run_dir / "03_post_qc" / artifact.run_id / "assembly_metrics.json"
        if not path.is_file():
            raise ToolExecutionError(f"Post-QC artifact is missing: {path}")
        try:
            metrics = AssemblyMetrics.model_validate_json(path.read_text())
        except (OSError, ValidationError) as exc:
            raise ToolExecutionError(f"Post-QC artifact is invalid: {path}: {exc}") from exc
        if metrics.run_id != artifact.run_id:
            raise ToolExecutionError(
                f"Post-QC run ID mismatch: {metrics.run_id} != {artifact.run_id}"
            )
        return metrics

    def evaluate(self, metrics: AssemblyMetrics, history: Sequence[str]) -> RuleDecision:
        """Evaluate the real baseline context and persist its decision artifact."""
        del history
        if metrics.run_id != "baseline":
            raise RuleEvaluationError(
                "Candidate-context normalization belongs to the Stage 11 closed-loop workflow"
            )
        context = load_rule_context(self.run_dir)
        decision = self.evaluator.evaluate(context)
        write_rule_decision(
            decision,
            self.run_dir / "04_decisions" / metrics.run_id / "rule_decision.json",
        )
        return decision

    def propose_candidates(self, decision: RuleDecision) -> list[AssemblyConfig]:
        """Generate bounded candidate configs through the audited Planner."""
        if self.baseline is None:
            raise InputValidationError("plan_baseline must run before propose_candidates")
        return self.planner.propose_candidates(
            decision,
            self.baseline,
            optimization_round=self.optimization_round,
            max_candidates=self.max_candidates,
            seen_fingerprints=self.seen_fingerprints,
        )

    def render_report(self, run_state: AgentRunState) -> Path:
        """Write a machine-readable Stage 9 execution summary, not the Stage 12 report."""
        output = self.run_dir / "05_agent" / "agent_summary.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "schema_version": "1.0",
            "sample_id": run_state.sample_id,
            "terminal_outcome": run_state.terminal_outcome,
            "final_state": "REPORT",
            "transition_count": run_state.transition_sequence
            + (run_state.state != AgentState.REPORT),
            "decision_id": (
                run_state.latest_decision.decision_id if run_state.latest_decision else None
            ),
            "decision": (run_state.latest_decision.decision if run_state.latest_decision else None),
            "action": run_state.latest_decision.action if run_state.latest_decision else None,
            "budget": run_state.budget.model_dump(mode="json"),
            "completed_run_ids": run_state.completed_run_ids,
            "last_error": run_state.last_error,
        }
        output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        return output


def load_resolved_sample_config(path: Path) -> SampleConfig:
    """Load a resolved sample config without mutating its metadata directory."""
    try:
        data = yaml.safe_load(path.read_text())
        return SampleConfig.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise InputValidationError(f"Resolved config is invalid: {path}: {exc}") from exc


def _nonnegative_number(value: object, field: str, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ToolExecutionError(f"Assembly manifest field `{field}` is invalid: {path}")
    return float(value)
