"""Portable acceptance through executable tools, CLI subprocesses, and disk artifacts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hifi_agent.decision.client import RecordedLLMClient
from hifi_agent.exceptions import LLMProviderError
from hifi_agent.orchestration.verifier import VerificationReport
from hifi_agent.reporting.models import FinalSummary

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_SCRIPT = PROJECT_ROOT / "scripts/run_portable_demo.py"


def _portable(workspace: Path, scenario: str) -> tuple[dict[str, object], FinalSummary]:
    completed = subprocess.run(
        [
            sys.executable,
            str(DEMO_SCRIPT),
            "--workspace",
            str(workspace),
            "--scenario",
            scenario,
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    run_dir = Path(str(result["run_dir"]))
    summary = FinalSummary.model_validate_json(
        (run_dir / "06_report/final_summary.json").read_text()
    )
    return result, summary


def test_executable_fixture_runs_three_rounds_through_real_cli_and_files(
    tmp_path: Path,
) -> None:
    result, summary = _portable(tmp_path, "three-rounds")
    run_dir = Path(str(result["run_dir"]))

    assert result["exit_codes"] == [0]
    assert summary.terminal_outcome == "STOP_MAX_ROUNDS"
    assert len(summary.attempts) == 4
    assert [item.round_index for item in summary.rounds] == [0, 1, 2, 3]
    assert len(summary.incumbent_chain) == 4
    assert all(item.status == "COMPLETED" for item in summary.attempts)
    assert all(item.realized_parameters == item.approved_parameters for item in summary.attempts)

    verification = VerificationReport.model_validate_json(
        (run_dir / "06_report/verification_report.json").read_text()
    )
    assert verification.status == "PASS"
    cli_verify = subprocess.run(
        [sys.executable, "-m", "hifi_agent", "verify-run", str(run_dir), "--deep"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert cli_verify.returncode == 0, cli_verify.stdout + cli_verify.stderr
    assert '"status": "PASS"' in cli_verify.stdout


def test_recorded_llm_replay_is_round_bound_checksummed_and_reported(tmp_path: Path) -> None:
    result, summary = _portable(tmp_path, "llm-replay")
    run_dir = Path(str(result["run_dir"]))

    assert summary.terminal_outcome == "STOP_MAX_ROUNDS"
    assert [item.status for item in summary.llm_activity] == ["SUCCESS"] * 3
    assert [item.provider for item in summary.llm_activity] == ["recorded:portable-fixture"] * 3
    checksum_roles = {
        line.split("\t", maxsplit=1)[0]
        for line in (run_dir / "00_metadata/input_checksums.tsv").read_text().splitlines()[1:]
    }
    assert "llm_replay_transcript" in checksum_roles
    for round_index in range(1, 4):
        receipt = json.loads(
            (run_dir / f"04_decisions/round_{round_index:02d}/llm_call_receipt.json").read_text()
        )
        assert receipt["metadata"]["replay_round_index"] == round_index
        assert receipt["prompt_sha256"]
        assert receipt["output_sha256"]

    transcript = tmp_path / "recorded_llm_transcript.json"
    transcript.write_text(transcript.read_text() + "\n")
    drift = subprocess.run(
        [
            sys.executable,
            "-m",
            "hifi_agent",
            "assemble",
            str(result["config"]),
            "--resume",
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert drift.returncode == 2
    assert "Validated input is missing or changed" in drift.stderr
    verification = subprocess.run(
        [sys.executable, "-m", "hifi_agent", "verify-run", str(run_dir), "--deep"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert verification.returncode == 4
    assert '"check_id": "INPUT_CHECKSUMS"' in verification.stdout
    assert '"status": "FAIL"' in verification.stdout


def test_recorded_llm_replay_rejects_duplicate_or_unbound_rounds(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        json.dumps(
            {
                "schema_id": "hifi-agent",
                "provider": "fixture",
                "model": "fixture",
                "responses": [
                    {"round_index": 1, "output": {"proposals": []}},
                    {"round_index": 1, "output": {"proposals": []}},
                ],
            }
        )
    )
    with pytest.raises(LLMProviderError, match="duplicate round"):
        RecordedLLMClient(duplicate)

    transcript = PROJECT_ROOT / "tests/fixtures/toolchain/recorded_llm_transcript.json"
    client = RecordedLLMClient(transcript)
    with pytest.raises(LLMProviderError, match="no round binding"):
        client.complete_json(system_prompt="governed", user_prompt="{}")


def test_round_two_sigterm_resumes_same_attempt_without_rebilling(tmp_path: Path) -> None:
    result, summary = _portable(tmp_path, "resume")
    run_dir = Path(str(result["run_dir"]))

    assert result["exit_codes"] == [4, 0]
    assert summary.terminal_outcome == "STOP_MAX_ROUNDS"
    assert len(summary.attempts) == 4
    round_two = [item for item in summary.attempts if item.round_index == 2]
    assert [item.attempt_id for item in round_two] == ["round_02_candidate_01.attempt_001"]
    assert summary.budget_committed["ASSEMBLY"] == 4
    assert (
        run_dir
        / "02_assembly/round_02/candidate_01/attempt_001/workflow/.portable_interrupted_once"
    ).is_file()


@pytest.mark.parametrize(
    ("scenario", "expected_exit", "expected_outcome"),
    [
        ("human-review", 3, "STOP_HUMAN_REVIEW"),
        ("tool-failure", 4, "FAILED_TOOL"),
        ("llm-required-failure", 5, "FAILED_REQUIRED_LLM"),
    ],
)
def test_cli_subprocess_exit_code_and_report_contract(
    tmp_path: Path,
    scenario: str,
    expected_exit: int,
    expected_outcome: str,
) -> None:
    result, summary = _portable(tmp_path, scenario)
    assert result["exit_codes"] == [expected_exit]
    assert summary.process_exit_code == expected_exit
    assert summary.terminal_outcome == expected_outcome


def test_readme_portable_command_is_the_tested_entrypoint() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()
    assert (
        "python scripts/run_portable_demo.py --workspace /tmp/hifi-agent-portable "
        "--scenario three-rounds"
    ) in readme


def test_cli_help_labels_advanced_surface() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "hifi_agent", "--help"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "Advanced options" in completed.stdout
    assert "migrate" not in completed.stdout.lower()
