"""Gated Stage 8/9 acceptance over genuine retained Candida artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hifi_agent.config import verify_recorded_input_checksums
from hifi_agent.optimization.evidence import (
    load_baseline_comparable,
    load_stage7_comparable,
)
from hifi_agent.optimization.loop import OptimizationLoop
from hifi_agent.optimization.loop_models import (
    LoopBudget,
    LoopDecisionContext,
    LoopDirective,
)
from hifi_agent.optimization.round_models import ComparableRun, RoundComparisonContext
from hifi_agent.optimization.rounds import RoundComparator
from hifi_agent.rag.models import ApprovedCandidate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUN = PROJECT_ROOT / "Data/Candida_albicans/hifiAgent"
STAGE7_ATTEMPT = (
    PROJECT_ROOT / "results/v2_stage7_candida/02_assembly/round_01/candidate_01/attempt_002"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "results/v2_stage8_stage9_candida"
APPROVAL_PATH = STAGE7_ATTEMPT / "approved_candidate.json"


def _required_real_artifacts() -> list[Path]:
    return [
        SOURCE_RUN / "00_metadata/input_checksums.tsv",
        SOURCE_RUN / "03_post_qc/baseline/assembly_metrics.json",
        STAGE7_ATTEMPT / "stage7_execution.json",
        STAGE7_ATTEMPT / "parameter_lineage.json",
        STAGE7_ATTEMPT / "post_qc_homology.json",
        APPROVAL_PATH,
    ]


def test_real_candida_stage8_comparison_and_stage9_plateau_loop() -> None:
    if os.environ.get("HIFI_AGENT_REAL_ACCEPTANCE") != "1":
        pytest.skip("set HIFI_AGENT_REAL_ACCEPTANCE=1 for retained Stage 8/9 acceptance")
    missing = [str(path) for path in _required_real_artifacts() if not path.is_file()]
    assert not missing, f"retained Stage 8/9 artifact(s) missing: {missing}"
    output = Path(os.environ.get("HIFI_AGENT_STAGE89_ACCEPTANCE_ROOT", DEFAULT_OUTPUT))
    before = {
        path: (path.stat().st_size, path.stat().st_mtime_ns) for path in _required_real_artifacts()
    }

    verify_recorded_input_checksums(SOURCE_RUN / "00_metadata/input_checksums.tsv")
    incumbent = load_baseline_comparable(SOURCE_RUN)
    candidate = load_stage7_comparable(STAGE7_ATTEMPT)
    context = RoundComparisonContext(
        reference_available=True,
        genome_size_trusted=False,
    )
    comparison = RoundComparator().compare_round(
        round_index=1,
        incumbent=incumbent,
        candidates=[candidate],
        context=context,
        output_dir=output / "stage8/round_01",
    )

    assert comparison.policy_version == "2.0.0"
    assert comparison.outcome == "STOP_PLATEAU"
    assert comparison.incumbent_before == comparison.incumbent_after == "baseline"
    assert comparison.selected_run_id is None
    assessment = comparison.candidates[0]
    assert assessment.run_id == "candidate_r01_c01"
    assert assessment.attempt_id == "attempt_002"
    assert assessment.status == "PLATEAU"
    assert assessment.material_improvements == []
    assert assessment.material_regressions == []
    assert assessment.hard_regressions == []
    assert assessment.acceptance_failures == []
    assert assessment.unavailable_metrics == []
    assert assessment.parameter_differences[0].parameter == "disable_post_join"
    assert assessment.parameter_differences[0].candidate_value is True
    differences = {item.metric: item for item in assessment.metric_differences}
    assert differences["assembly_size_ratio"].result == "NOT_APPLICABLE"
    assert differences["quast_misassemblies"].result == "UNCHANGED"
    for metric, difference in differences.items():
        if metric != "assembly_size_ratio":
            assert difference.result == "UNCHANGED"
            assert difference.incumbent_value == difference.candidate_value

    approval = ApprovedCandidate.model_validate_json(APPROVAL_PATH.read_text())
    provider_calls: list[LoopDecisionContext] = []
    runner_calls: list[dict[str, object]] = []

    def provider(decision_context: LoopDecisionContext) -> LoopDirective:
        provider_calls.append(decision_context)
        return LoopDirective(
            action="RETRY",
            reason_codes=["REAL_STAGE7_CANDIDATE_REPLAY"],
            approved_candidates=[approval],
        )

    def runner(
        observed: ApprovedCandidate,
        *,
        round_index: int,
        candidate_index: int,
        resume: bool,
    ) -> ComparableRun:
        runner_calls.append(
            {
                "candidate": observed,
                "round_index": round_index,
                "candidate_index": candidate_index,
                "resume": resume,
            }
        )
        assert observed == approval
        assert round_index == candidate_index == 1
        return candidate

    loop_root = output / "stage9"
    loop = OptimizationLoop(
        loop_root,
        sample_id="Candida_albicans",
        baseline=incumbent,
        proposal_provider=provider,
        candidate_runner=runner,
        comparison_context=context,
        budget=LoopBudget(
            max_cpu_hours=1.0,
            max_walltime_hours=1.0,
            estimated_candidate_cpu_hours=0.2,
            estimated_candidate_walltime_hours=0.2,
        ),
        max_rounds=3,
        max_candidates_per_round=1,
    )
    resume = loop.state_path.is_file()
    state = loop.run(resume=resume)

    assert state.terminal_outcome == "STOP_PLATEAU"
    assert state.phase == "TERMINAL"
    assert state.round_index == 1
    assert state.incumbent.run_id == "baseline"
    assert state.selected_run_id is None
    assert len(state.rounds) == 1
    assert state.rounds[0].comparison.outcome == "STOP_PLATEAU"
    assert state.budget.candidates_started == 1
    assert state.budget.consumed_cpu_hours == pytest.approx(candidate.cpu_hours)
    assert state.budget.consumed_walltime_hours == pytest.approx(candidate.walltime_hours)
    if not resume:
        assert len(provider_calls) == len(runner_calls) == 1
    else:
        assert provider_calls == []
        assert runner_calls == []
    trace = [json.loads(line) for line in loop.trace_path.read_text().splitlines() if line]
    assert [item["sequence"] for item in trace] == list(range(1, len(trace) + 1))
    assert trace[-1]["action"] == "STOP_PLATEAU"

    after = {
        path: (path.stat().st_size, path.stat().st_mtime_ns) for path in _required_real_artifacts()
    }
    assert after == before
