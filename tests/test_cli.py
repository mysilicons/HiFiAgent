from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

import hifi_agent.cli
from hifi_agent.cli import app
from hifi_agent.constants import ExitCode, __version__
from hifi_agent.exceptions import AgentStateError
from hifi_agent.orchestration.bootstrap import write_bootstrap_failure
from hifi_agent.orchestration.runtime_models import RunPhase
from hifi_agent.reporting.models import FinalSummary

runner = CliRunner()


def _config(tmp_path: Path) -> Path:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    path = tmp_path / "sample.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent",
                "sample_id": "sample",
                "read_technology": "pacbio_hifi",
                "hifi_reads": [str(reads)],
                "outdir": str(tmp_path / "run"),
                "execution_budget": {"min_free_disk_gib": 0},
            }
        )
    )
    return path


def test_package_release_is_reported() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_public_cli_exposes_only_production_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("assemble", "plan", "validate", "verify-run"):
        assert command in result.output


def test_plan_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        hifi_agent.cli,
        "run_environment_preflight",
        lambda _sample: SimpleNamespace(status="PASS"),
    )
    monkeypatch.setattr(hifi_agent.cli, "require_environment_preflight", lambda _value: None)
    result = runner.invoke(app, ["plan", str(config), "--decision-mode", "llm_disabled"])
    assert result.exit_code == 0
    assert "No run artifacts were written" in result.output
    assert not (tmp_path / "run").exists()


def test_assemble_uses_only_coordinator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    observed: dict[str, object] = {}

    class FakeCoordinator:
        def __init__(
            self,
            path: Path,
            *,
            decision_mode_override: str | None,
            confirm_medium_high_risk: bool,
        ) -> None:
            observed["path"] = path
            observed["mode"] = decision_mode_override
            observed["confirmation"] = confirm_medium_high_risk

        def run(self, *, resume: bool) -> SimpleNamespace:
            observed["resume"] = resume
            report_dir = tmp_path / "run/06_report"
            report_dir.mkdir(parents=True)
            summary_path = report_dir / "final_summary.json"
            summary = FinalSummary(
                generated_at=datetime.now(UTC),
                run_uuid="a" * 32,
                sample_id="sample",
                package_version="test-release",
                code_commit="abc123",
                terminal_outcome="ACCEPTED_BASELINE",
                outcome_class="SCIENTIFIC",
                process_exit_code=0,
                selected_run_ref=Path("02_assembly/baseline/attempt_001"),
                baseline_run_ref=Path("02_assembly/baseline/attempt_001"),
                incumbent_chain=(Path("02_assembly/baseline/attempt_001"),),
                attempts=(),
                rounds=(),
                llm_activity=(),
                budget_limits={},
                budget_reserved={},
                budget_committed={},
                budget_remaining={},
                stop_reason_codes=("BASELINE_ACCEPTED",),
                scientific_limitations=("test fixture",),
                verification_status="PASS",
            )
            summary_path.write_text(summary.model_dump_json(indent=2) + "\n")
            return SimpleNamespace(
                run_dir=tmp_path / "run",
                state=SimpleNamespace(
                    state=RunPhase.TERMINAL,
                    terminal_outcome="ACCEPTED_BASELINE",
                ),
                baseline_attempt=SimpleNamespace(attempt_id="baseline.attempt_001"),
                report_bundle=SimpleNamespace(
                    markdown=report_dir / "final_report.md",
                    summary=summary_path,
                ),
            )

    monkeypatch.setattr(hifi_agent.cli, "RunCoordinator", FakeCoordinator)
    result = runner.invoke(
        app,
        ["assemble", str(config), "--resume", "--decision-mode", "rules_only"],
    )
    assert result.exit_code == 0
    assert "reported terminal state" in result.output
    assert observed == {
        "path": config,
        "mode": "rules_only",
        "confirmation": False,
        "resume": True,
    }


def test_cli_uses_documented_failure_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)

    class FailingCoordinator:
        def __init__(
            self,
            path: Path,
            *,
            decision_mode_override: str | None,
            confirm_medium_high_risk: bool,
        ) -> None:
            del path, decision_mode_override, confirm_medium_high_risk

        def run(self, *, resume: bool) -> None:
            del resume
            raise AgentStateError("corrupt state")

    monkeypatch.setattr(hifi_agent.cli, "RunCoordinator", FailingCoordinator)
    monkeypatch.setattr(hifi_agent.cli, "write_bootstrap_failure", lambda *args, **kwargs: None)
    result = runner.invoke(app, ["assemble", str(config)])
    assert result.exit_code == ExitCode.INTERNAL_ERROR
    assert "corrupt state" in result.output


def test_split_config_bootstrap_failure_uses_runtime_output_root(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    sample_root = config_root / "samples"
    sample_root.mkdir(parents=True)
    runtime = config_root / "runtime.yaml"
    runtime.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent-runtime",
                "paths": {
                    "data_root": "../Data",
                    "output_root": "../results",
                    "cache_root": "../cache",
                },
            }
        )
    )
    sample = sample_root / "apple.yaml"
    sample.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent-sample",
                "runtime_config": "../runtime.yaml",
                "sample_id": "apple",
            }
        )
    )

    receipt = write_bootstrap_failure(
        sample,
        AgentStateError("fixture bootstrap failure"),
        stage="CONTROLLER_BOOTSTRAP",
    )

    assert receipt == tmp_path / "results/apple/00_metadata/bootstrap_failure.json"
    assert receipt.is_file()
