import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest

from hifi_agent.exceptions import AgentStateError
from hifi_agent.orchestration.retention import apply_retention
from hifi_agent.orchestration.runtime_models import RunPhase
from hifi_agent.orchestration.verifier import VerificationCheck, VerificationReport


def _verification(
    run_dir: Path,
    *,
    status: Literal["PASS", "WARNING", "FAIL"] = "PASS",
    deep: bool = True,
) -> None:
    report = VerificationReport(
        checked_at=datetime.now(UTC),
        run_dir=run_dir,
        deep=deep,
        status=status,
        checks=[
            VerificationCheck(
                check_id="fixture",
                status=status,
                message="fixture verification",
            )
        ],
    )
    output = run_dir / "06_report/verification_report.json"
    output.parent.mkdir(parents=True)
    output.write_text(report.model_dump_json(indent=2) + "\n")


def test_standard_retention_removes_only_regenerable_work_after_deep_pass(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    pre_qc_work = run_dir / "01_pre_qc/work"
    assembly_work = run_dir / "02_assembly/baseline/attempt_001/workflow/work"
    published = run_dir / "02_assembly/baseline/attempt_001/assembly/primary.fa"
    nextflow_cache = run_dir / "02_assembly/baseline/attempt_001/workflow/.nextflow/cache"
    for path in (pre_qc_work / "task.bin", assembly_work / "task.bin", published, nextflow_cache):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"1234")
    _verification(run_dir)

    receipt = apply_retention(
        run_dir,
        policy="standard",
        state=RunPhase.TERMINAL,
    )

    assert receipt is not None
    assert receipt.freed_bytes == 8
    assert set(receipt.removed_paths) == {
        Path("01_pre_qc/work"),
        Path("02_assembly/baseline/attempt_001/workflow/work"),
    }
    assert not pre_qc_work.exists()
    assert not assembly_work.exists()
    assert published.is_file()
    assert nextflow_cache.is_file()
    persisted = json.loads((run_dir / "00_metadata/retention_receipt.json").read_text())
    assert persisted["status"] == "PASS"


def test_standard_retention_is_idempotent(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    work = run_dir / "01_pre_qc/work"
    work.mkdir(parents=True)
    (work / "one").write_text("data")
    _verification(run_dir)

    first = apply_retention(run_dir, policy="standard", state=RunPhase.TERMINAL)
    second = apply_retention(run_dir, policy="standard", state=RunPhase.TERMINAL)

    assert second == first


@pytest.mark.parametrize(
    ("state", "status", "deep", "message"),
    [
        (RunPhase.VERIFYING, "PASS", True, "terminal run state"),
        (RunPhase.TERMINAL, "WARNING", True, "PASS deep-verification"),
        (RunPhase.TERMINAL, "PASS", False, "PASS deep-verification"),
    ],
)
def test_standard_retention_refuses_unverified_or_nonterminal_runs(
    tmp_path: Path,
    state: RunPhase,
    status: Literal["PASS", "WARNING", "FAIL"],
    deep: bool,
    message: str,
) -> None:
    run_dir = tmp_path / "run"
    _verification(run_dir, status=status, deep=deep)

    with pytest.raises(AgentStateError, match=message):
        apply_retention(run_dir, policy="standard", state=state)


def test_full_retention_never_mutates_work_directories(tmp_path: Path) -> None:
    work = tmp_path / "run/01_pre_qc/work"
    work.mkdir(parents=True)

    assert apply_retention(tmp_path / "run", policy="full", state=RunPhase.INITIALIZING) is None
    assert work.is_dir()
