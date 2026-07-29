import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from hifi_agent.benchmarking import run_v2_portable_demo
from hifi_agent.cli import app
from hifi_agent.optimization.policy import DEFAULT_COMPARISON_POLICY, load_comparison_policy


def test_packaged_comparison_policy_is_available() -> None:
    assert "hifi_agent/data" in DEFAULT_COMPARISON_POLICY.as_posix()
    assert load_comparison_policy().policy_version == "2.0.0"


def test_v2_portable_demo_is_explicitly_data_free(tmp_path: Path) -> None:
    report = run_v2_portable_demo(
        tmp_path,
        generated_at=datetime(2026, 7, 29, tzinfo=UTC),
    )

    payload = json.loads((tmp_path / "v2_portable_demo.json").read_text())
    markdown = (tmp_path / "v2_portable_demo.md").read_text()
    assert report.result == "PASS"
    assert report.biological_data_used is False
    assert len(report.safety_scenarios) == 5
    assert all(item.passed for item in report.safety_scenarios)
    assert payload["biological_data_used"] is False
    assert "not a biological assembly result" in markdown


def test_demo_v2_cli(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["demo-v2", str(tmp_path)])

    assert result.exit_code == 0
    assert "Portable V2 demo: PASS" in result.output
    assert "Scenarios passed: 5/5" in result.output
