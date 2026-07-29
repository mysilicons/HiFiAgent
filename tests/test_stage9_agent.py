import json
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from hifi_agent.agent.controller import AgentController
from hifi_agent.agent.models import (
    AgentRunState,
    AgentState,
    AssemblyArtifact,
    AssemblyConfig,
    PreQcMetrics,
    TransitionEvent,
)
from hifi_agent.agent.planner import Planner
from hifi_agent.agent.state import AgentStateStore, validate_transition
from hifi_agent.config import ConfigValidationResult
from hifi_agent.exceptions import (
    IllegalStateTransitionError,
    InputValidationError,
    ToolExecutionError,
)
from hifi_agent.rules.models import CandidateParameters, ParameterCandidate, RuleDecision
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.schemas.sample import AgentConfig, SampleConfig


def rule_decision(
    decision: str = "BASELINE",
    action: str = "ACCEPT_DEFAULT_PARAMETERS",
    *,
    candidate_parameters: list[CandidateParameters] | None = None,
) -> RuleDecision:
    candidates = [
        ParameterCandidate(
            candidate_id=f"candidate-{index}",
            source_rule_id="TEST_RULE",
            parameters=parameters,
            risk_level="medium",
        )
        for index, parameters in enumerate(candidate_parameters or [], start=1)
    ]
    return RuleDecision(
        decision_id=f"D-{decision}",
        rule_set_version="test",
        threshold_catalog_version="test",
        decision=decision,  # type: ignore[arg-type]
        action=action,
        matched_rule_ids=["TEST_RULE"],
        controlling_rule_ids=["TEST_RULE"],
        reason_codes=[f"TEST_{decision}"],
        evidence={"assembly_size_ratio": 1.0},
        candidates=candidates,
        confidence=0.9,
        risk_level="low",
        conflicts=[],
        human_readable_explanation="Test decision.",
    )


class FakeAgentTools:
    def __init__(
        self,
        run_dir: Path,
        config: SampleConfig,
        *,
        decisions: list[RuleDecision] | None = None,
        assembly_failures: int = 0,
        post_qc_failures: int = 0,
        cpu_hours: float = 2.0,
        walltime_hours: float = 0.5,
        input_error: bool = False,
        pre_qc_coverage: float | None = 30.0,
        pre_qc_total_bases: int | None = 3_000_000_000,
    ) -> None:
        self.run_dir = run_dir
        self.config = config
        self.decisions = decisions or [rule_decision()]
        self.assembly_failures = assembly_failures
        self.post_qc_failures = post_qc_failures
        self.cpu_hours = cpu_hours
        self.walltime_hours = walltime_hours
        self.input_error = input_error
        self.pre_qc_coverage = pre_qc_coverage
        self.pre_qc_total_bases = pre_qc_total_bases
        self.assembly_calls: list[str] = []
        self.post_qc_calls: list[str] = []
        self.evaluate_calls = 0
        self.planner = Planner()
        self.baseline: AssemblyConfig | None = None

    def validate_input(self, config: Path) -> ConfigValidationResult:
        if self.input_error:
            raise InputValidationError("injected invalid input")
        return ConfigValidationResult(
            config=self.config,
            metadata_dir=self.run_dir / "00_metadata",
            resolved_config=config,
            input_checksums=self.run_dir / "00_metadata" / "input_checksums.tsv",
            validation_receipt=self.run_dir / "00_metadata" / "validation_receipt.json",
        )

    def run_pre_qc(self, config: SampleConfig) -> PreQcMetrics:
        return PreQcMetrics(
            sample_id=config.sample_id,
            input_status="PASS",
            read_count=100,
            total_bases=self.pre_qc_total_bases,
            estimated_genome_size=100_000_000,
            estimated_coverage=self.pre_qc_coverage,
        )

    def plan_baseline(self, metrics: PreQcMetrics) -> AssemblyConfig:
        self.baseline = self.planner.plan_baseline(self.config, metrics)
        return self.baseline

    def run_assembly(self, config: AssemblyConfig) -> AssemblyArtifact:
        self.assembly_calls.append(config.run_id)
        if self.assembly_failures > 0:
            self.assembly_failures -= 1
            raise ToolExecutionError(f"injected assembly failure: {config.run_id}")
        assembly_dir = self.run_dir / "02_assembly" / config.run_id
        manifest = assembly_dir / "metadata" / "assembly_manifest.json"
        fasta = assembly_dir / "fasta" / f"{config.run_id}.primary.fa"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        fasta.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}\n")
        fasta.write_text(">contig\nACGT\n")
        return AssemblyArtifact(
            run_id=config.run_id,
            manifest=manifest,
            primary_fasta=fasta,
            cpu_hours=self.cpu_hours,
            walltime_hours=self.walltime_hours,
        )

    def run_post_qc(self, artifact: AssemblyArtifact) -> AssemblyMetrics:
        self.post_qc_calls.append(artifact.run_id)
        if self.post_qc_failures > 0:
            self.post_qc_failures -= 1
            raise ToolExecutionError(f"injected post-QC failure: {artifact.run_id}")
        path = self.run_dir / "03_post_qc" / artifact.run_id / "assembly_metrics.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        metrics = AssemblyMetrics(
            run_id=artifact.run_id,
            assembly_size=100_000_000,
            contig_n50=1_000_000,
            busco_complete=98.0,
            busco_duplicated=2.0,
            mapped_read_fraction=0.99,
            assembly_size_ratio=1.0,
        )
        path.write_text(metrics.model_dump_json())
        return metrics

    def evaluate(self, metrics: AssemblyMetrics, history: Sequence[str]) -> RuleDecision:
        assert metrics.run_id in history
        index = min(self.evaluate_calls, len(self.decisions) - 1)
        self.evaluate_calls += 1
        return self.decisions[index]

    def propose_candidates(self, decision: RuleDecision) -> list[AssemblyConfig]:
        assert self.baseline is not None
        return self.planner.propose_candidates(
            decision,
            self.baseline,
            optimization_round=1,
            max_candidates=self.config.agent.max_candidates_per_round,
            seen_fingerprints={self.baseline.parameter_fingerprint()},
        )

    def render_report(self, run_state: AgentRunState) -> Path:
        path = self.run_dir / "05_agent" / "agent_summary.json"
        path.write_text(
            json.dumps({"terminal_outcome": run_state.terminal_outcome}, sort_keys=True) + "\n"
        )
        return path


def make_controller(
    tmp_path: Path,
    *,
    agent: AgentConfig | None = None,
    decisions: list[RuleDecision] | None = None,
    assembly_failures: int = 0,
    post_qc_failures: int = 0,
    cpu_hours: float = 2.0,
    walltime_hours: float = 0.5,
    input_error: bool = False,
    pre_qc_coverage: float | None = 30.0,
    pre_qc_total_bases: int | None = 3_000_000_000,
) -> tuple[AgentController, FakeAgentTools]:
    run_dir = tmp_path / "run"
    config_path = run_dir / "00_metadata" / "resolved_config.yaml"
    config_path.parent.mkdir(parents=True)
    sample = SampleConfig(
        sample_id="sample",
        hifi_reads=[tmp_path / "reads.fastq"],
        outdir=run_dir,
        expected_genome_size=100_000_000,
        ploidy=2,
        agent=agent or AgentConfig(),
    )
    config_path.write_text(yaml.safe_dump(sample.model_dump(mode="json"), sort_keys=False))
    tools = FakeAgentTools(
        run_dir,
        sample,
        decisions=decisions,
        assembly_failures=assembly_failures,
        post_qc_failures=post_qc_failures,
        cpu_hours=cpu_hours,
        walltime_hours=walltime_hours,
        input_error=input_error,
        pre_qc_coverage=pre_qc_coverage,
        pre_qc_total_bases=pre_qc_total_bases,
    )
    return AgentController(run_dir, config_path, tools), tools


def read_trace(controller: AgentController) -> list[TransitionEvent]:
    return [
        TransitionEvent.model_validate_json(line)
        for line in controller.store.trace_path.read_text().splitlines()
        if line
    ]


def test_complete_no_llm_execution_logs_every_state_change(tmp_path: Path) -> None:
    controller, tools = make_controller(tmp_path)

    state = controller.run()
    trace = read_trace(controller)

    assert state.state == AgentState.REPORT
    assert state.terminal_outcome == "ACCEPTED"
    assert tools.assembly_calls == ["baseline"]
    assert tools.post_qc_calls == ["baseline"]
    assert len(trace) == state.transition_sequence
    assert [event.sequence for event in trace] == list(range(1, len(trace) + 1))
    assert trace[-2].state_after == AgentState.ACCEPTED
    assert trace[-1].state_after == AgentState.REPORT
    assert state.report_path is not None
    assert state.report_path.is_file()


def test_illegal_state_transition_has_explicit_error() -> None:
    with pytest.raises(
        IllegalStateTransitionError,
        match="Illegal Agent transition PRE_QC -> ACCEPTED",
    ):
        validate_transition(AgentState.PRE_QC, AgentState.ACCEPTED)


def test_invalid_input_reaches_failed_input_and_report(tmp_path: Path) -> None:
    controller, tools = make_controller(tmp_path, input_error=True)

    state = controller.run()

    assert state.terminal_outcome == "FAILED_INPUT"
    assert tools.assembly_calls == []
    assert read_trace(controller)[-2].state_after == AgentState.FAILED_INPUT


def test_low_coverage_reaches_low_quality_stop_without_assembly(tmp_path: Path) -> None:
    controller, tools = make_controller(tmp_path, pre_qc_coverage=14.9)

    state = controller.run()

    assert state.terminal_outcome == "STOP_LOW_QUALITY"
    assert tools.assembly_calls == []


def test_missing_pre_qc_core_metric_reaches_metadata_stop(tmp_path: Path) -> None:
    controller, tools = make_controller(tmp_path, pre_qc_total_bases=None)

    state = controller.run()

    assert state.terminal_outcome == "STOP_INSUFFICIENT_METADATA"
    assert tools.assembly_calls == []


def test_rule_uncertainty_reaches_safe_uncertain_stop(tmp_path: Path) -> None:
    uncertain = rule_decision("STOP", "REVIEW_GENOME_SIZE_ESTIMATE")
    controller, tools = make_controller(tmp_path, decisions=[uncertain])

    state = controller.run()

    assert state.terminal_outcome == "STOP_UNCERTAIN"
    assert tools.assembly_calls == ["baseline"]


@pytest.mark.parametrize(
    "agent",
    [
        AgentConfig(max_cpu_hours=0.0),
        AgentConfig(max_walltime_hours=0.0),
    ],
)
def test_exhausted_compute_budget_never_starts_assembly(
    tmp_path: Path,
    agent: AgentConfig,
) -> None:
    controller, tools = make_controller(tmp_path, agent=agent)

    state = controller.run()

    assert state.terminal_outcome == "STOP_BUDGET_EXCEEDED"
    assert tools.assembly_calls == []
    assert "NO_ADDITIONAL_ASSEMBLY_STARTED" in read_trace(controller)[-2].reason_codes


def test_candidate_estimate_cannot_overshoot_cpu_budget(tmp_path: Path) -> None:
    retry = rule_decision(
        "RETRY",
        "PROPOSE_STRONGER_PURGE",
        candidate_parameters=[CandidateParameters(purge_similarity=0.5)],
    )
    controller, tools = make_controller(
        tmp_path,
        agent=AgentConfig(max_cpu_hours=15.0),
        decisions=[retry],
        cpu_hours=10.0,
    )

    state = controller.run()

    assert state.terminal_outcome == "STOP_BUDGET_EXCEEDED"
    assert tools.assembly_calls == ["baseline"]
    assert read_trace(controller)[-2].reason_codes[0] == "CPU_HOUR_BUDGET_EXCEEDED"


def test_duplicate_baseline_parameters_are_never_rerun(tmp_path: Path) -> None:
    retry = rule_decision(
        "RETRY",
        "PROPOSE_DUPLICATE",
        candidate_parameters=[CandidateParameters(purge_level=3)],
    )
    controller, tools = make_controller(tmp_path, decisions=[retry])

    state = controller.run()

    assert state.terminal_outcome == "STOP_BUDGET_EXCEEDED"
    assert tools.assembly_calls == ["baseline"]
    assert read_trace(controller)[-2].reason_codes[0] == "NO_UNIQUE_PARAMETER_CANDIDATE"


def test_tool_failure_retry_is_not_parameter_optimization(tmp_path: Path) -> None:
    controller, tools = make_controller(
        tmp_path,
        agent=AgentConfig(max_tool_retries=1),
        assembly_failures=2,
    )

    state = controller.run()
    trace = read_trace(controller)

    assert state.terminal_outcome == "FAILED_TOOL_EXECUTION"
    assert tools.assembly_calls == ["baseline", "baseline"]
    assert state.budget.optimization_rounds_started == 0
    retry_events = [event for event in trace if event.retry_kind == "TOOL_FAILURE"]
    assert len(retry_events) == 1
    assert state.baseline_config is not None
    assert retry_events[0].parameter_fingerprint == state.baseline_config.parameter_fingerprint()
    assert state.latest_decision is None


def test_post_qc_tool_failure_is_not_biological_quality_stop(tmp_path: Path) -> None:
    controller, _tools = make_controller(
        tmp_path,
        agent=AgentConfig(max_tool_retries=0),
        post_qc_failures=1,
    )

    state = controller.run()

    assert state.terminal_outcome == "FAILED_TOOL_EXECUTION"
    assert state.latest_decision is None
    assert read_trace(controller)[-2].action == "STOP_TOOL_RETRIES_EXHAUSTED"


def test_interrupted_execution_resumes_from_snapshot_without_repeating_assembly(
    tmp_path: Path,
) -> None:
    controller, tools = make_controller(tmp_path)
    interrupted = controller.run(max_steps=4)

    assert interrupted.state == AgentState.POST_QC
    assert tools.assembly_calls == ["baseline"]

    resumed_controller = AgentController(
        controller.run_dir,
        controller.config_path,
        tools,
    )
    completed = resumed_controller.run(resume=True)

    assert completed.terminal_outcome == "ACCEPTED"
    assert tools.assembly_calls == ["baseline"]
    trace = read_trace(resumed_controller)
    assert len(trace) == completed.transition_sequence
    assert [event.sequence for event in trace] == list(range(1, len(trace) + 1))


def test_state_store_repairs_snapshot_written_before_trace_append(tmp_path: Path) -> None:
    controller, _tools = make_controller(tmp_path)
    interrupted = controller.run(max_steps=2)
    lines = controller.store.trace_path.read_text().splitlines()
    controller.store.trace_path.write_text("\n".join(lines[:-1]) + "\n")

    recovered = AgentStateStore(controller.store.agent_dir).load()

    assert recovered.transition_sequence == interrupted.transition_sequence
    assert len(read_trace(controller)) == recovered.transition_sequence


def test_candidate_limit_and_retry_round_limit_are_hard_bounds(tmp_path: Path) -> None:
    retry = rule_decision(
        "RETRY",
        "PROPOSE_CANDIDATES",
        candidate_parameters=[
            CandidateParameters(purge_similarity=0.5),
            CandidateParameters(disable_post_join=True),
        ],
    )
    controller, tools = make_controller(
        tmp_path,
        agent=AgentConfig(max_retry_rounds=1, max_candidates_per_round=1),
        decisions=[retry, retry],
    )

    state = controller.run()

    assert state.terminal_outcome == "STOP_BUDGET_EXCEEDED"
    assert tools.assembly_calls == ["baseline", "candidate_r01_c01"]
    assert state.budget.optimization_rounds_started == 1
    assert state.budget.candidates_started_by_round == {"1": 1}
    assert read_trace(controller)[-2].reason_codes[0] == "OPTIMIZATION_ROUND_BUDGET_EXCEEDED"


def test_rule_reported_tool_failure_maps_to_failed_tool_execution(tmp_path: Path) -> None:
    tool_failure = rule_decision("STOP", "STOP_EVALUATION_INCOMPLETE")
    controller, tools = make_controller(tmp_path, decisions=[tool_failure])

    state = controller.run()

    assert state.terminal_outcome == "FAILED_TOOL_EXECUTION"
    assert tools.assembly_calls == ["baseline"]
    assert state.budget.optimization_rounds_started == 0
