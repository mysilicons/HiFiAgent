from pathlib import Path

import pytest
from typer.testing import CliRunner

import hifi_agent.cli
from hifi_agent.cli import app
from hifi_agent.constants import ExitCode
from hifi_agent.executors.nextflow import NextflowRunResult

runner = CliRunner()


def test_help_lists_initial_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == ExitCode.OK
    assert "validate" in result.output
    assert "plan" in result.output
    assert "run" in result.output
    assert "evaluate" in result.output
    assert "report" in result.output


def test_version_option() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == ExitCode.OK
    assert "hifi-agent 0.1.0" in result.output


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
