import json
import os
from pathlib import Path

import pytest

from hifi_agent.agent import AgentController, AgentState, ExistingRunAgentTools
from hifi_agent.agent.models import TransitionEvent

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_ACCEPTANCE = os.environ.get("HIFI_AGENT_REAL_ACCEPTANCE") == "1"

pytestmark = pytest.mark.skipif(
    not REAL_ACCEPTANCE,
    reason="set HIFI_AGENT_REAL_ACCEPTANCE=1 to verify retained real-data artifacts",
)


def test_real_candida_stage9_controller_reaches_safe_recoverable_terminal_state() -> None:
    run_dir = PROJECT_ROOT / "results" / "Candida_albicans_phase6"
    config = run_dir / "00_metadata" / "resolved_config.yaml"
    controller = AgentController(run_dir, config, ExistingRunAgentTools(run_dir))
    resume = controller.store.state_path.exists()

    state = controller.run(resume=resume)

    assert state.state == AgentState.REPORT
    assert state.terminal_outcome == "STOP_UNCERTAIN"
    assert state.latest_decision is not None
    assert state.latest_decision.action == "REVIEW_GENOME_SIZE_ESTIMATE"
    assert state.latest_decision.candidates == []
    assert state.completed_run_ids == ["baseline"]
    assert state.budget.consumed_cpu_hours == pytest.approx(77620.022 / 3600)
    assert state.budget.consumed_walltime_hours == pytest.approx(1200.681 / 3600)
    trace = [
        TransitionEvent.model_validate_json(line)
        for line in controller.store.trace_path.read_text().splitlines()
        if line
    ]
    assert len(trace) == state.transition_sequence
    assert trace[-2].state_after == AgentState.STOP_UNCERTAIN
    assert trace[-1].state_after == AgentState.REPORT
    summary = json.loads((run_dir / "05_agent" / "agent_summary.json").read_text())
    assert summary["terminal_outcome"] == "STOP_UNCERTAIN"
    assert summary["final_state"] == "REPORT"
    assert summary["transition_count"] == state.transition_sequence
