import json
from pathlib import Path

import pytest
import yaml

import hifi_agent.orchestration.controller as orchestration_controller
from hifi_agent.agent.models import AssemblyConfig, AssemblyParameters
from hifi_agent.config import ConfigValidationResult, validate_config_file
from hifi_agent.exceptions import AgentStateError, IllegalStateTransitionError, ToolExecutionError
from hifi_agent.orchestration.controller import AssemblyController, ExecutingAssemblyTools
from hifi_agent.orchestration.models import AssemblyRunState, AssemblyState
from hifi_agent.orchestration.state import validate_assembly_transition
from hifi_agent.rules.models import CandidateParameters, ParameterCandidate, RuleDecision
from hifi_agent.schemas.sample import SampleConfig


def _decision(kind: str) -> RuleDecision:
    candidates = []
    if kind == "RETRY":
        candidates = [
            ParameterCandidate(
                candidate_id="disable-post-join",
                source_rule_id="TEST_RULE",
                parameters=CandidateParameters(disable_post_join=True),
                risk_level="medium",
            )
        ]
    return RuleDecision(
        decision_id=f"D-{kind}",
        rule_set_version="test",
        threshold_catalog_version="test",
        decision=kind,  # type: ignore[arg-type]
        action="TEST_ACTION",
        matched_rule_ids=["TEST_RULE"],
        controlling_rule_ids=["TEST_RULE"],
        reason_codes=[f"TEST_{kind}"],
        evidence={"assembly_size": 100},
        candidates=candidates,
        confidence=0.9,
        risk_level="medium",
        conflicts=[],
        human_readable_explanation="test",
    )


def _config_file(tmp_path: Path, *, tool_retries: int = 1) -> Path:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    config = tmp_path / "sample.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "sample_id": "sample",
                "hifi_reads": [str(reads)],
                "outdir": str(tmp_path / "run"),
                "agent": {"max_tool_retries": tool_retries},
            }
        )
    )
    return config


class FakeExecutingTools:
    def __init__(
        self,
        config_path: Path,
        *,
        decision: str = "BASELINE",
        baseline_failures: int = 0,
    ) -> None:
        self.config_path = config_path
        self.config = validate_config_file(config_path, write_outputs=False).config
        self.decision = _decision(decision)
        self.baseline_failures = baseline_failures
        self.baseline_execute_calls = 0
        self.baseline_resume_values: list[bool] = []
        self.candidate_execute_calls = 0
        self.evaluate_calls = 0
        self.qc_feature_calls = 0
        self.summary_calls = 0

    def validate(self, config_path: Path) -> ConfigValidationResult:
        return validate_config_file(config_path)

    def baseline_complete(self, config: SampleConfig) -> bool:
        return all(
            path.is_file()
            for role, path in self.baseline_artifacts(config.outdir).items()
            if role != "qc_feature_bundle"
        )

    def execute_baseline(self, config: SampleConfig, *, resume: bool) -> None:
        self.baseline_execute_calls += 1
        self.baseline_resume_values.append(resume)
        if self.baseline_failures:
            self.baseline_failures -= 1
            raise ToolExecutionError("injected baseline failure")
        _write_artifacts(self.baseline_artifacts(config.outdir))

    def evaluate_baseline(self, run_dir: Path) -> RuleDecision:
        del run_dir
        self.evaluate_calls += 1
        return self.decision

    def materialize_qc_features(self, config: SampleConfig) -> Path:
        self.qc_feature_calls += 1
        path = config.outdir / "legacy/baseline/qc_feature_bundle.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
        return path

    def plan_candidate(self, config: SampleConfig, decision: RuleDecision) -> AssemblyConfig | None:
        del decision
        return AssemblyConfig(
            run_id="candidate_r01_c01",
            input_reads=config.hifi_reads,
            threads=config.resources.max_threads,
            parameters=AssemblyParameters(disable_post_join=True),
            reason_codes=["TEST_RETRY"],
            risk_level="medium",
            retry_kind="PARAMETER_OPTIMIZATION",
            optimization_round=1,
        )

    def candidate_complete(self, run_dir: Path, candidate: AssemblyConfig) -> bool:
        return all(path.is_file() for path in self.candidate_artifacts(run_dir, candidate).values())

    def execute_candidate(self, run_dir: Path, candidate: AssemblyConfig, *, resume: bool) -> None:
        del resume
        self.candidate_execute_calls += 1
        _write_artifacts(self.candidate_artifacts(run_dir, candidate))

    def baseline_artifacts(self, run_dir: Path) -> dict[str, Path]:
        return {
            "assembly_manifest": run_dir / "legacy/baseline/assembly_manifest.json",
            "primary_fasta": run_dir / "legacy/baseline/primary.fa",
            "post_qc_metrics": run_dir / "legacy/baseline/assembly_metrics.json",
            "raw_metrics": run_dir / "legacy/baseline/raw_metrics.json",
            "qc_feature_bundle": run_dir / "legacy/baseline/qc_feature_bundle.json",
        }

    def candidate_artifacts(self, run_dir: Path, candidate: AssemblyConfig) -> dict[str, Path]:
        base = run_dir / "legacy" / candidate.run_id
        return {
            "assembly_manifest": base / "assembly_manifest.json",
            "primary_fasta": base / "primary.fa",
            "post_qc_metrics": base / "assembly_metrics.json",
            "parameter_contract": base / "parameter_contract_check.json",
        }

    def render_summary(self, state: AssemblyRunState) -> Path:
        self.summary_calls += 1
        path = state.identity.run_dir / "06_report/v2_stage3_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"outcome": state.terminal_outcome}) + "\n")
        return path


def _write_artifacts(artifacts: dict[str, Path]) -> None:
    for role, path in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{role}\n")


def test_fixture_one_command_completes_baseline_and_report(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    tools = FakeExecutingTools(config)
    controller = AssemblyController(config, tools)

    state = controller.run()

    assert state.state == AssemblyState.REPORT
    assert state.terminal_outcome == "ACCEPTED_BASELINE"
    assert tools.baseline_execute_calls == 1
    assert tools.evaluate_calls == 1
    assert tools.qc_feature_calls == 1
    assert tools.summary_calls == 1
    assert state.report_path is not None
    assert state.report_path.is_file()
    assert state.baseline_attempt is not None
    assert controller.history.is_complete(state.baseline_attempt)
    assert [record.round_index for record in controller.history.load_history().rounds] == [0]


def test_missing_qc_bundle_is_materialized_without_rerunning_complete_baseline(
    tmp_path: Path,
) -> None:
    config = _config_file(tmp_path)
    tools = FakeExecutingTools(config)
    artifacts = tools.baseline_artifacts(tmp_path / "run")
    _write_artifacts(
        {role: path for role, path in artifacts.items() if role != "qc_feature_bundle"}
    )

    state = AssemblyController(config, tools).run()

    assert state.state == AssemblyState.REPORT
    assert tools.baseline_execute_calls == 0
    assert tools.qc_feature_calls == 1
    assert artifacts["qc_feature_bundle"].is_file()


def test_retry_decision_executes_a_real_adapter_candidate_path(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    tools = FakeExecutingTools(config, decision="RETRY")

    state = AssemblyController(config, tools).run()

    assert state.terminal_outcome == "CANDIDATE_EXECUTED_STAGE3"
    assert tools.candidate_execute_calls == 1
    assert state.candidate_attempt is not None
    assert state.candidate_attempt.run_id == "candidate_r01_c01"
    assert [
        record.round_index
        for record in AssemblyController(config, tools).history.load_history().rounds
    ] == [0, 1]


def test_interruption_resume_does_not_rerun_completed_baseline(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    tools = FakeExecutingTools(config)
    first = AssemblyController(config, tools)

    interrupted = first.run(max_steps=2)
    assert interrupted.state == AssemblyState.BASELINE_EVALUATION
    assert tools.baseline_execute_calls == 1

    resumed = AssemblyController(config, tools).run(resume=True)

    assert resumed.state == AssemblyState.REPORT
    assert tools.baseline_execute_calls == 1


def test_report_resume_is_a_noop_without_new_events_or_report(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    tools = FakeExecutingTools(config)
    first = AssemblyController(config, tools)
    completed = first.run()
    trace_before = first.store.trace_path.read_text()
    summary_calls = tools.summary_calls

    resumed = AssemblyController(config, tools).run(resume=True)

    assert resumed == completed
    assert first.store.trace_path.read_text() == trace_before
    assert tools.summary_calls == summary_calls


def test_resume_detects_tampered_attempt_artifact(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    tools = FakeExecutingTools(config)
    controller = AssemblyController(config, tools)
    controller.run(max_steps=2)
    tools.baseline_artifacts(tmp_path / "run")["post_qc_metrics"].write_text("tampered\n")

    with pytest.raises(AgentStateError, match="checksum mismatch"):
        AssemblyController(config, tools).run(resume=True)


def test_tool_retry_uses_attempt_002_without_parameter_change(tmp_path: Path) -> None:
    config = _config_file(tmp_path, tool_retries=1)
    tools = FakeExecutingTools(config, baseline_failures=1)

    state = AssemblyController(config, tools).run()

    assert state.state == AssemblyState.REPORT
    assert tools.baseline_execute_calls == 2
    attempts = AssemblyController(config, tools).history.load_history().attempts
    assert [attempt.attempt_id for attempt in attempts] == ["attempt_001", "attempt_002"]


def test_resume_passes_nextflow_resume_to_incomplete_tool_retry(tmp_path: Path) -> None:
    config = _config_file(tmp_path, tool_retries=1)
    tools = FakeExecutingTools(config, baseline_failures=1)
    interrupted = AssemblyController(config, tools).run(max_steps=2)
    assert interrupted.state == AssemblyState.BASELINE_EXECUTION

    resumed = AssemblyController(config, tools).run(resume=True)

    assert resumed.state == AssemblyState.REPORT
    assert tools.baseline_resume_values == [False, True]


def test_resume_repairs_one_missing_trace_event(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    tools = FakeExecutingTools(config)
    controller = AssemblyController(config, tools)
    interrupted = controller.run(max_steps=1)
    assert interrupted.transition_sequence == 2
    lines = controller.store.trace_path.read_text().splitlines()
    controller.store.trace_path.write_text(lines[0] + "\n")

    loaded = controller.store.load()

    assert loaded.transition_sequence == 2
    assert len(controller.store.trace_path.read_text().splitlines()) == 2


def test_resume_rejects_changed_original_config(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    tools = FakeExecutingTools(config)
    AssemblyController(config, tools).run(max_steps=1)
    data = yaml.safe_load(config.read_text())
    data["species_name"] = "changed after initialization"
    config.write_text(yaml.safe_dump(data))

    with pytest.raises(AgentStateError, match="config checksum differs"):
        AssemblyController(config, tools).run(resume=True)


def test_illegal_transition_fails_without_mutating_state(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    tools = FakeExecutingTools(config)
    controller = AssemblyController(config, tools)
    state = controller.run(max_steps=1)
    state_before = controller.store.state_path.read_text()
    trace_before = controller.store.trace_path.read_text()

    with pytest.raises(IllegalStateTransitionError):
        validate_assembly_transition(AssemblyState.BASELINE_EXECUTION, AssemblyState.REPORT)

    assert controller.store.state_path.read_text() == state_before
    assert controller.store.trace_path.read_text() == trace_before
    assert state.state == AssemblyState.BASELINE_EXECUTION


def test_real_adapter_calls_baseline_and_candidate_nextflow_executors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config_file(tmp_path)
    config = validate_config_file(config_path, write_outputs=False).config
    candidate = AssemblyConfig(
        run_id="candidate_r01_c01",
        input_reads=config.hifi_reads,
        threads=config.resources.max_threads,
        parameters=AssemblyParameters(disable_post_join=True),
        reason_codes=["TEST_EXECUTOR"],
        risk_level="medium",
        retry_kind="PARAMETER_OPTIMIZATION",
        optimization_round=1,
    )
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        orchestration_controller,
        "run_phase3_workflow",
        lambda observed, *, resume: calls.append((observed.sample_id, resume)),
    )
    monkeypatch.setattr(
        orchestration_controller,
        "run_candidate_workflow",
        lambda run_dir, observed, *, resume: calls.append((observed.run_id, resume)),
    )
    tools = ExecutingAssemblyTools()

    tools.execute_baseline(config, resume=True)
    tools.execute_candidate(config.outdir, candidate, resume=True)

    assert calls == [("sample", True), ("candidate_r01_c01", True)]
