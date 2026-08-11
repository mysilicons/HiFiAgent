"""Terminal reporting and verification boundary for the single current coordinator."""

from __future__ import annotations

from collections.abc import Callable

from hifi_agent.exceptions import AgentStateError
from hifi_agent.orchestration.coordinator_models import CoordinatorResult
from hifi_agent.orchestration.coordinator_support import required_attempt
from hifi_agent.orchestration.journal import StateStore
from hifi_agent.orchestration.runtime_models import RunPhase, RunState
from hifi_agent.orchestration.verifier import (
    VerificationReport,
    verify_run,
)
from hifi_agent.reporting.service import ReportService

FaultHook = Callable[[str, RunState], None]


class CoordinatorTerminal:
    """Generate, deep-verify, and recover canonical terminal report artifacts."""

    def __init__(self, fault: FaultHook) -> None:
        self.fault = fault

    def finish(self, state: RunState) -> CoordinatorResult:
        """Advance REPORTING/VERIFYING to a verified TERMINAL state."""
        run_dir = state.identity.run_dir
        reports = ReportService(run_dir)
        store = StateStore(run_dir)
        if state.state == RunPhase.REPORTING:
            self.fault("before_reporting", state)
            reports.generate(state, verification_status="PENDING")
            self.fault("after_reporting", state)
            state = store.transition(
                state,
                RunPhase.VERIFYING,
                action="START_DEEP_TERMINAL_VERIFICATION",
                reason_codes=["FIVE_REPORT_VIEWS_MATERIALIZED"],
                updates={
                    "report_refs": [path.relative_to(run_dir) for path in reports.bundle.paths()]
                },
            )
        if state.state == RunPhase.VERIFYING:
            self.fault("before_deep_verification", state)
            verification = verify_run(
                run_dir,
                deep=True,
                expected_writer_lock=True,
                verify_reports=False,
            )
            self.fault("after_deep_verification", state)
            reports.write_verification(verification)
            report_state = state
            if verification.status == "FAIL":
                report_state = state.model_copy(
                    update={
                        "terminal_outcome": "FAILED_STATE_INTEGRITY",
                        "outcome_class": "FAILED",
                        "terminal_reason_codes": ["TERMINAL_DEEP_VERIFICATION_FAILED"],
                    }
                )
            reports.generate(report_state, verification_status=verification.status)
            reports.write_verification(verification)
            state = store.transition(
                state,
                RunPhase.TERMINAL,
                action="COMMIT_TERMINAL_STATE",
                reason_codes=(
                    ["TERMINAL_VERIFICATION_PASS"]
                    if verification.status != "FAIL"
                    else ["TERMINAL_VERIFICATION_FAIL"]
                ),
                updates={
                    "terminal_outcome": report_state.terminal_outcome,
                    "outcome_class": report_state.outcome_class,
                    "terminal_reason_codes": report_state.terminal_reason_codes,
                    "report_refs": [path.relative_to(run_dir) for path in reports.bundle.paths()],
                },
            )
            self.fault("before_final_report_materialization", state)
            reports.generate(state, verification_status=verification.status)
            reports.write_verification(verification)
            self.fault("after_final_report_materialization", state)
        return self.result(state)

    def result(self, state: RunState) -> CoordinatorResult:
        """Load or recover the report bundle for an existing terminal state."""
        run_dir = state.identity.run_dir
        baseline = (
            required_attempt(run_dir, state.baseline_run_ref)
            if state.baseline_run_ref is not None
            else None
        )
        bundle = ReportService(run_dir).bundle
        missing = [path for path in bundle.paths() if not path.is_file()]
        if missing:
            reports = ReportService(run_dir)
            if bundle.verification.is_file():
                verification = VerificationReport.model_validate_json(
                    bundle.verification.read_text()
                )
            else:
                verification = verify_run(
                    run_dir,
                    deep=True,
                    expected_writer_lock=(run_dir / "05_agent/run.lock").is_file(),
                    verify_reports=False,
                )
            reports.generate(state, verification_status=verification.status)
            reports.write_verification(verification)
            missing = [path for path in bundle.paths() if not path.is_file()]
            if missing:
                raise AgentStateError(f"Terminal current run lacks report artifact(s): {missing}")
        return CoordinatorResult(
            run_dir=run_dir,
            state=state,
            baseline_attempt=baseline,
            report_bundle=bundle,
        )
