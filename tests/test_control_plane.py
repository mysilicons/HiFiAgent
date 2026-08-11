import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hifi_agent.constants import __version__
from hifi_agent.exceptions import AgentStateError, IllegalStateTransitionError
from hifi_agent.orchestration.budget import (
    BudgetLedger,
    BudgetLimits,
    BudgetResource,
)
from hifi_agent.orchestration.identity import IdentityStore
from hifi_agent.orchestration.journal import StateStore
from hifi_agent.orchestration.lock import RunLock
from hifi_agent.orchestration.manifests import (
    AssemblyAttemptRecord,
    ManifestReference,
    ManifestStore,
    RoundRecord,
)
from hifi_agent.orchestration.runtime_models import (
    RunIdentity,
    RunPhase,
    RunState,
)
from hifi_agent.orchestration.verifier import verify_run


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _limits() -> BudgetLimits:
    return BudgetLimits(
        max_total_assemblies=4,
        max_tool_retries=1,
        max_cpu_hours=20,
        max_walltime_hours=10,
        min_free_disk_gib=5,
        max_llm_calls_per_round=1,
        max_total_llm_calls=3,
    )


def _control_plane(
    tmp_path: Path,
) -> tuple[Path, RunIdentity, RunState, BudgetLedger]:
    run_dir = tmp_path / "run"
    resolved = _write(run_dir / "00_metadata/resolved_config.yaml", "sample_id: sample\n")
    effective = _write(run_dir / "00_metadata/effective_config.json", "{}\n")
    _write(run_dir / "00_metadata/input_checksums.tsv", "role\tpath\tsha256\tbytes\n")
    inputs = _write(run_dir / "00_metadata/input_manifest.json", "{}\n")
    environment = _write(run_dir / "00_metadata/environment_manifest.json", "{}\n")
    policy = _write(run_dir / "04_decisions/comparison_policy_snapshot.yaml", "version: 1\n")
    identity = RunIdentity.create(
        sample_id="sample",
        run_dir=run_dir,
        code_commit="abc123",
        package_version=__version__,
        config=resolved,
        effective_config=effective,
        input_manifest=inputs,
        environment_manifest=environment,
        comparison_policy=policy,
    )
    IdentityStore(run_dir).initialize(identity)
    state = StateStore(run_dir).initialize(identity)
    ledger = BudgetLedger(run_dir)
    ledger.initialize(_limits())
    ManifestStore(run_dir).initialize_history()
    return run_dir, identity, state, ledger


def test_identity_is_immutable_and_snapshot_drift_writes_receipt(tmp_path: Path) -> None:
    run_dir, identity, _state, _ledger = _control_plane(tmp_path)
    store = IdentityStore(run_dir)
    assert store.verify_snapshots() == identity
    (run_dir / "00_metadata/effective_config.json").write_text('{"changed": true}\n')

    with pytest.raises(AgentStateError, match="snapshot drift"):
        store.verify_snapshots(write_drift_receipt=True)

    receipt = json.loads(store.drift_path.read_text())
    assert receipt["status"] == "FAIL"
    assert receipt["drift"][0]["field"] == "effective_config_sha256"


def test_identity_cannot_be_initialized_twice(tmp_path: Path) -> None:
    run_dir, identity, _state, _ledger = _control_plane(tmp_path)

    with pytest.raises(AgentStateError, match="already exists"):
        IdentityStore(run_dir).initialize(identity)


@pytest.mark.parametrize("failure_point", ["after_pending", "after_state", "after_event"])
def test_transaction_recovery_covers_every_crash_window(
    tmp_path: Path,
    failure_point: str,
) -> None:
    run_dir, _identity, state, _ledger = _control_plane(tmp_path)

    def fail(point: str, _pending: object) -> None:
        if point == failure_point:
            raise RuntimeError(f"injected {point}")

    crashing = StateStore(run_dir, fault_injector=fail)
    with pytest.raises(RuntimeError, match="injected"):
        crashing.transition(
            state,
            RunPhase.INPUT_VALIDATION,
            action="VALIDATE_INPUT",
            reason_codes=["TEST_TRANSITION"],
        )

    recovered_store = StateStore(run_dir)
    recovered = recovered_store.load()

    assert recovered.state == RunPhase.INPUT_VALIDATION
    assert recovered.sequence == 2
    assert len(recovered_store.load_events()) == 2
    assert not list(recovered_store.pending_dir.glob("*.json"))


def test_initial_transaction_recovers_when_only_pending_exists(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    files = [
        _write(run_dir / "resolved", "a"),
        _write(run_dir / "effective", "b"),
        _write(run_dir / "inputs", "c"),
        _write(run_dir / "environment", "d"),
        _write(run_dir / "policy", "e"),
    ]
    identity = RunIdentity.create(
        sample_id="sample",
        run_dir=run_dir,
        code_commit="abc",
        package_version=__version__,
        config=files[0],
        effective_config=files[1],
        input_manifest=files[2],
        environment_manifest=files[3],
        comparison_policy=files[4],
    )

    def fail(point: str, _pending: object) -> None:
        if point == "after_pending":
            raise RuntimeError("initial crash")

    with pytest.raises(RuntimeError, match="initial crash"):
        StateStore(run_dir, fault_injector=fail).initialize(identity)

    recovered = StateStore(run_dir).load()
    assert recovered.state == RunPhase.INITIALIZING
    assert recovered.sequence == 1


def test_event_trace_is_appended_and_not_rewritten(tmp_path: Path) -> None:
    run_dir, _identity, state, _ledger = _control_plane(tmp_path)
    store = StateStore(run_dir)
    original = store.trace_path.read_bytes()

    updated = store.transition(
        state,
        RunPhase.INPUT_VALIDATION,
        action="VALIDATE_INPUT",
        reason_codes=["PASS"],
    )

    assert updated.sequence == 2
    assert store.trace_path.read_bytes().startswith(original)
    assert len(store.trace_path.read_text().splitlines()) == 2


def test_illegal_transition_does_not_mutate_control_plane(tmp_path: Path) -> None:
    run_dir, _identity, state, _ledger = _control_plane(tmp_path)
    store = StateStore(run_dir)
    before_state = store.state_path.read_text()
    before_trace = store.trace_path.read_text()

    with pytest.raises(IllegalStateTransitionError):
        store.transition(
            state,
            RunPhase.CANDIDATE_ASSEMBLY,
            action="SKIP_STATES",
            reason_codes=["ILLEGAL"],
        )

    assert store.state_path.read_text() == before_state
    assert store.trace_path.read_text() == before_trace


def test_transition_rejects_updates_to_protected_control_fields(tmp_path: Path) -> None:
    run_dir, _identity, state, _ledger = _control_plane(tmp_path)
    store = StateStore(run_dir)

    with pytest.raises(AgentStateError, match="protected"):
        store.transition(
            state,
            RunPhase.INPUT_VALIDATION,
            action="INVALID_UPDATE",
            reason_codes=["TEST"],
            updates={"sequence": 99},
        )


def test_state_control_field_tampering_is_detected(tmp_path: Path) -> None:
    run_dir, _identity, _state, _ledger = _control_plane(tmp_path)
    path = run_dir / "05_agent/run_state.json"
    payload = json.loads(path.read_text())
    payload["report_refs"] = ["forged.json"]
    path.write_text(json.dumps(payload))

    with pytest.raises(AgentStateError, match="checksum"):
        StateStore(run_dir).verify_read_only()


def test_state_schema_downgrade_is_rejected_without_repair(tmp_path: Path) -> None:
    run_dir, _identity, _state, _ledger = _control_plane(tmp_path)
    path = run_dir / "05_agent/run_state.json"
    payload = json.loads(path.read_text())
    payload["schema_id"] = "unsupported"
    path.write_text(json.dumps(payload))

    with pytest.raises(AgentStateError, match="state is invalid"):
        StateStore(run_dir).verify_read_only()


def test_live_writer_lock_rejects_a_second_writer(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    first = RunLock(
        run_dir,
        run_uuid="a" * 32,
        command=["assemble"],
        process_alive=lambda _pid: True,
    )
    first.acquire()
    second = RunLock(
        run_dir,
        run_uuid="a" * 32,
        command=["assemble"],
        process_alive=lambda _pid: True,
    )

    with pytest.raises(AgentStateError, match="locked"):
        second.acquire()

    first.release()


def test_stale_lock_requires_explicit_audited_takeover(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    abandoned = RunLock(
        run_dir,
        run_uuid="a" * 32,
        command=["assemble"],
        process_alive=lambda _pid: False,
    )
    old = abandoned.acquire()
    replacement = RunLock(
        run_dir,
        run_uuid="a" * 32,
        command=["assemble", "--resume"],
        process_alive=lambda _pid: False,
    )

    with pytest.raises(AgentStateError, match="explicit"):
        replacement.acquire()
    current = replacement.acquire(takeover_stale=True)

    assert current.takeover_of_lock_id == old.lock_id
    assert list((run_dir / "05_agent").glob("run.lock.stale.*.json"))
    replacement.release()


def test_budget_reservation_commit_release_and_resume_are_idempotent(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    ledger = BudgetLedger(run_dir)
    ledger.initialize(_limits())

    reserved = ledger.reserve(
        BudgetResource.ASSEMBLY,
        1,
        reservation_id="attempt_001",
        attempt_id="attempt_001",
        reason_code="BEFORE_LAUNCH",
    )
    repeated = ledger.reserve(
        BudgetResource.ASSEMBLY,
        1,
        reservation_id="attempt_001",
        attempt_id="attempt_001",
        reason_code="RESUME",
    )
    committed = ledger.commit("attempt_001", 1, reason_code="ACTUAL_USAGE")
    repeated_commit = ledger.commit("attempt_001", 1, reason_code="RESUME")
    ledger.reserve(
        BudgetResource.CPU_HOURS,
        5,
        reservation_id="cpu-attempt-2",
        reason_code="ESTIMATE",
    )
    ledger.release("cpu-attempt-2", reason_code="NOT_LAUNCHED")

    snapshot = BudgetLedger(run_dir).snapshot()
    assert repeated.entry_id == reserved.entry_id
    assert repeated_commit.entry_id == committed.entry_id
    assert snapshot.committed[BudgetResource.ASSEMBLY] == 1
    assert snapshot.balance[BudgetResource.ASSEMBLY] == 3
    assert snapshot.reserved[BudgetResource.CPU_HOURS] == 0
    assert snapshot.sequence == 4


def test_budget_exhaustion_disk_floor_and_llm_round_limit(tmp_path: Path) -> None:
    ledger = BudgetLedger(tmp_path / "run")
    ledger.initialize(_limits())
    ledger.reserve(
        BudgetResource.CPU_HOURS,
        20,
        reservation_id="cpu-all",
        reason_code="ESTIMATE",
    )
    with pytest.raises(AgentStateError, match="exhausted"):
        ledger.reserve(
            BudgetResource.CPU_HOURS,
            1,
            reservation_id="cpu-extra",
            reason_code="ESTIMATE",
        )
    ledger.reserve_disk(
        4,
        observed_free_gib=10,
        reservation_id="disk-1",
        reason_code="DISK_ESTIMATE",
    )
    with pytest.raises(AgentStateError, match="disk budget exhausted"):
        ledger.reserve_disk(
            2,
            observed_free_gib=10,
            reservation_id="disk-2",
            reason_code="DISK_ESTIMATE",
        )
    ledger.reserve(
        BudgetResource.LLM_CALL,
        1,
        reservation_id="llm-1",
        round_id="round_01",
        llm_call_id="llm-1",
        reason_code="LLM_CALL",
    )
    with pytest.raises(AgentStateError, match="per-round"):
        ledger.reserve(
            BudgetResource.LLM_CALL,
            1,
            reservation_id="llm-2",
            round_id="round_01",
            llm_call_id="llm-2",
            reason_code="LLM_CALL",
        )


def test_budget_adjustment_is_audited_and_cannot_go_negative(tmp_path: Path) -> None:
    ledger = BudgetLedger(tmp_path / "run")
    ledger.initialize(_limits())

    entry = ledger.adjust_limit(
        BudgetResource.CPU_HOURS,
        5,
        operation_id="operator-extension-1",
        reason_code="EXPLICIT_CLI_OVERRIDE",
    )

    assert ledger.snapshot().balance[BudgetResource.CPU_HOURS] == 25
    assert (
        ledger.adjust_limit(
            BudgetResource.CPU_HOURS,
            5,
            operation_id="operator-extension-1",
            reason_code="RESUME",
        ).entry_id
        == entry.entry_id
    )
    with pytest.raises(AgentStateError, match="negative"):
        ledger.adjust_limit(
            BudgetResource.CPU_HOURS,
            -30,
            operation_id="invalid-reduction",
            reason_code="INVALID",
        )


def test_budget_ledger_rejects_tampered_derived_balance(tmp_path: Path) -> None:
    ledger = BudgetLedger(tmp_path / "run")
    ledger.initialize(_limits())
    ledger.reserve(
        BudgetResource.CPU_HOURS,
        2,
        reservation_id="cpu-1",
        reason_code="ESTIMATE",
    )
    payload = json.loads(ledger.ledger_path.read_text())
    payload["balance_after"] += 1
    ledger.ledger_path.write_text(json.dumps(payload) + "\n")

    with pytest.raises(AgentStateError, match="balance_after"):
        ledger.snapshot()


def test_verify_run_is_read_only_and_detects_metadata_tampering(tmp_path: Path) -> None:
    run_dir, _identity, _state, _ledger = _control_plane(tmp_path)
    before = {
        path.relative_to(run_dir): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in run_dir.rglob("*")
        if path.is_file()
    }

    report = verify_run(run_dir, deep=True)

    after = {
        path.relative_to(run_dir): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert report.status == "PASS"
    assert before == after

    (run_dir / "00_metadata/effective_config.json").write_text("tampered\n")
    failed = verify_run(run_dir, deep=True)
    assert failed.status == "FAIL"
    assert any(check.check_id == "IDENTITY" for check in failed.checks)


def test_verify_run_rejects_tampered_event_sequence(tmp_path: Path) -> None:
    run_dir, _identity, _state, _ledger = _control_plane(tmp_path)
    path = run_dir / "05_agent/event_trace.jsonl"
    event = json.loads(path.read_text())
    event["sequence"] = 2
    path.write_text(json.dumps(event) + "\n")

    report = verify_run(run_dir, deep=True)

    assert report.status == "FAIL"
    assert any(
        check.check_id == "STATE_JOURNAL" and check.status == "FAIL" for check in report.checks
    )


def test_attempt_round_and_history_manifests_are_immutable_and_hash_chained(
    tmp_path: Path,
) -> None:
    run_dir, identity, _state, _ledger = _control_plane(tmp_path)
    store = ManifestStore(run_dir)
    now = datetime.now(UTC)
    attempt = AssemblyAttemptRecord(
        attempt_id="attempt_001",
        logical_run_id="baseline",
        round_id="round_00",
        round_index=0,
        attempt_index=1,
        status="FAILED",
        environment_manifest_sha256=identity.environment_manifest_sha256,
        started_at=now,
        completed_at=now,
        error="injected failure",
        comparison_eligible=False,
        ineligible_reason_codes=["ATTEMPT_FAILED"],
    )
    attempt_path = store.write_attempt(attempt)
    attempt_ref = ManifestReference.from_path(run_dir, attempt_path)
    round_record = RoundRecord(
        round_id="round_00",
        round_index=0,
        attempt_refs=[attempt_ref],
        round_outcome="FAILED_TOOL",
        stop_reason_codes=["ATTEMPT_FAILED"],
        created_at=now,
        completed_at=now,
    )
    round_path = store.write_round(round_record)
    latest = store.append_history(
        attempt_paths=[attempt_path],
        round_paths=[round_path],
    )

    assert latest.sequence == 2
    assert store.verify() == latest
    with pytest.raises(FileExistsError):
        store.write_attempt(attempt)

    attempt_path.write_text(attempt_path.read_text().replace("injected failure", "tampered"))
    with pytest.raises(AgentStateError, match="manifest drift"):
        store.verify()


def test_history_manifest_rejects_sequence_gap(tmp_path: Path) -> None:
    run_dir, _identity, _state, _ledger = _control_plane(tmp_path)
    store = ManifestStore(run_dir)
    payload = json.loads(store.history_path.read_text())
    payload["sequence"] = 2
    store.history_path.write_text(json.dumps(payload) + "\n")

    with pytest.raises(AgentStateError, match="sequence"):
        store.load_history()
