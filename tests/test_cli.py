from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import hifi_agent.cli
from hifi_agent.cli import app
from hifi_agent.constants import ExitCode
from hifi_agent.executors.nextflow import NextflowRunResult
from hifi_agent.rules.context import RuleContext
from hifi_agent.rules.models import RuleDecision

runner = CliRunner()


def test_help_lists_initial_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == ExitCode.OK
    assert "validate" in result.output
    assert "plan" in result.output
    assert "run" in result.output
    assert "evaluate" in result.output
    assert "report" in result.output
    assert "decide" in result.output
    assert "agent" in result.output
    assert "rag-index" in result.output
    assert "explain" in result.output
    assert "optimize" in result.output
    assert "synthesize-stage11-anomaly" in result.output


def test_version_option() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == ExitCode.OK
    assert "hifi-agent 1.0.0" in result.output


def test_placeholder_command_uses_project_exit_code() -> None:
    result = runner.invoke(app, ["plan", "sample.yaml"])

    assert result.exit_code == ExitCode.NOT_IMPLEMENTED
    assert "`hifi-agent plan` is not implemented yet" in result.output


def test_validate_missing_config_uses_input_validation_exit_code() -> None:
    result = runner.invoke(app, ["validate", "sample.yaml"])

    assert result.exit_code == ExitCode.INPUT_VALIDATION_FAILED
    assert "Config file does not exist" in result.output


def test_evaluate_runs_post_qc_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    def fake_evaluate(path: Path, *, resume: bool = True) -> NextflowRunResult:
        assert path == run_dir.resolve()
        assert resume is True
        return NextflowRunResult(("nextflow",), path, path / "reads.list")

    monkeypatch.setattr(hifi_agent.cli, "run_post_qc_workflow", fake_evaluate)

    result = runner.invoke(app, ["evaluate", str(run_dir)])

    assert result.exit_code == ExitCode.OK
    assert "Post-assembly evaluation completed" in result.output


def test_decide_writes_rule_decision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    context = RuleContext()
    decision = RuleDecision(
        decision_id="D-TEST",
        rule_set_version="test",
        threshold_catalog_version="test",
        decision="BASELINE",
        action="ACCEPT_DEFAULT_PARAMETERS",
        matched_rule_ids=["NORMAL"],
        controlling_rule_ids=["NORMAL"],
        reason_codes=["METRICS_NORMAL"],
        evidence={"assembly_size_ratio": 1.0},
        candidates=[],
        confidence=0.9,
        risk_level="low",
        conflicts=[],
        human_readable_explanation="Normal metrics.",
    )

    class FakeEngine:
        def evaluate(self, observed: RuleContext) -> RuleDecision:
            assert observed is context
            return decision

    monkeypatch.setattr(hifi_agent.cli, "load_rule_context", lambda path: context)
    monkeypatch.setattr(hifi_agent.cli, "load_default_rule_engine", FakeEngine)

    result = runner.invoke(app, ["decide", str(run_dir)])

    output = run_dir / "04_decisions" / "baseline" / "rule_decision.json"
    assert result.exit_code == ExitCode.OK
    assert "Rule decision: BASELINE" in result.output
    assert output.is_file()
    assert RuleDecision.model_validate_json(output.read_text()) == decision


def test_decide_missing_run_artifacts_uses_insufficient_evidence_exit_code(
    tmp_path: Path,
) -> None:
    result = runner.invoke(app, ["decide", str(tmp_path)])

    assert result.exit_code == ExitCode.INSUFFICIENT_EVIDENCE
    assert "Rule context artifact(s) missing" in result.output


def test_agent_command_runs_recoverable_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    observed: dict[str, object] = {}

    class FakeController:
        def __init__(self, observed_run_dir: Path, config: Path, tools: object) -> None:
            observed["run_dir"] = observed_run_dir
            observed["config"] = config
            observed["tools"] = tools
            self.store = SimpleNamespace(
                state_path=observed_run_dir / "05_agent" / "agent_state.json",
                trace_path=observed_run_dir / "05_agent" / "decision_trace.jsonl",
            )

        def run(self, *, resume: bool = False) -> SimpleNamespace:
            observed["resume"] = resume
            return SimpleNamespace(terminal_outcome="STOP_UNCERTAIN", state="REPORT")

    fake_tools = object()
    monkeypatch.setattr(hifi_agent.cli, "AgentController", FakeController)
    monkeypatch.setattr(hifi_agent.cli, "ExistingRunAgentTools", lambda path: fake_tools)

    result = runner.invoke(app, ["agent", str(run_dir), "--resume"])

    assert result.exit_code == ExitCode.OK
    assert "Agent terminal outcome: STOP_UNCERTAIN" in result.output
    assert observed["run_dir"] == run_dir.resolve()
    assert observed["resume"] is True


def test_rag_index_command_reports_source_and_chunk_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "index.json"
    monkeypatch.setattr(
        hifi_agent.cli,
        "build_knowledge_index",
        lambda **kwargs: SimpleNamespace(sources=[1, 2], chunks=[1, 2, 3]),
    )

    result = runner.invoke(app, ["rag-index", "--output", str(output)])

    assert result.exit_code == ExitCode.OK
    assert "Sources: 2" in result.output
    assert "Chunks: 3" in result.output


def test_explain_command_supports_llm_disabled_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    observed: dict[str, object] = {}

    def fake_explain(path: Path, **kwargs: object) -> SimpleNamespace:
        observed["path"] = path
        observed.update(kwargs)
        return SimpleNamespace(
            llm_status="DISABLED",
            explanation=SimpleNamespace(recommended_action="STOP_AND_REVIEW"),
            retrieval_evidence=[SimpleNamespace(source_id="hifiasm_faq")],
        )

    monkeypatch.setattr(hifi_agent.cli, "explain_run", fake_explain)

    result = runner.invoke(app, ["explain", str(run_dir), "--no-llm"])

    assert result.exit_code == ExitCode.OK
    assert "Explanation status: DISABLED" in result.output
    assert observed["path"] == run_dir.resolve()
    assert observed["enable_llm"] is False
