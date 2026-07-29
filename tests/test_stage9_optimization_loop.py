import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from hifi_agent.agent.models import AssemblyConfig, AssemblyParameters
from hifi_agent.optimization.loop import OptimizationLoop
from hifi_agent.optimization.loop_models import LoopBudget, LoopDirective
from hifi_agent.optimization.round_models import (
    ComparableRun,
    RoundComparison,
    RoundComparisonContext,
)
from hifi_agent.optimization.rounds import RoundComparator
from hifi_agent.rag.models import ApprovedCandidate
from hifi_agent.rules.models import CandidateParameters
from hifi_agent.schemas.metrics import AssemblyMetrics


def _metrics(run_id: str, **updates: object) -> AssemblyMetrics:
    values: dict[str, object] = {
        "run_id": run_id,
        "assembly_size_ratio": 1.0,
        "contig_n50": 1_000_000,
        "quast_misassemblies": 20,
        "busco_complete": 98.0,
        "busco_duplicated": 1.0,
        "kmer_completeness": 95.0,
        "kmer_qv": 30.0,
        "mapped_read_fraction": 0.99,
        "coverage_cv": 0.30,
        "tool_failures": [],
    }
    values.update(updates)
    return AssemblyMetrics.model_validate(values)


def _config(run_id: str, round_index: int, parameters: AssemblyParameters) -> AssemblyConfig:
    return AssemblyConfig(
        run_id=run_id,
        input_reads=[Path("reads.fastq")],
        threads=8,
        parameters=parameters,
        reason_codes=["STAGE9_TEST"],
        risk_level="medium",
        retry_kind="NONE" if run_id == "baseline" else "PARAMETER_OPTIMIZATION",
        optimization_round=round_index,
    )


def _baseline() -> ComparableRun:
    return ComparableRun(
        run_id="baseline",
        attempt_id="attempt_001",
        config=_config("baseline", 0, AssemblyParameters()),
        metrics=_metrics("baseline"),
        metrics_path=Path("baseline.json"),
        parameter_contract_status="PASS",
        execution_status="COMPLETED",
        cpu_hours=1.0,
        walltime_hours=0.1,
    )


def _approved(candidate_id: str, parameters: CandidateParameters) -> ApprovedCandidate:
    payload = json.dumps(
        parameters.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return ApprovedCandidate(
        candidate_id=candidate_id,
        origin="rule",
        requested_parameters=parameters,
        approved_parameters=parameters,
        source_ids=["hifiasm_parameters"],
        metric_ids=["contig_n50"],
        reason_codes=["MATERIAL_IMPROVEMENT_TEST"],
        risk_level="medium",
        requires_user_confirmation=False,
        confidence=0.8,
        parameter_fingerprint=hashlib.sha256(payload.encode()).hexdigest(),
    )


APPROVALS = {
    1: _approved("round_one_join", CandidateParameters(disable_post_join=True)),
    2: _approved("round_two_similarity", CandidateParameters(purge_similarity=0.5)),
    3: _approved("round_three_purge", CandidateParameters(purge_level=2)),
}


def _retry(*candidates: ApprovedCandidate) -> LoopDirective:
    return LoopDirective(
        action="RETRY",
        reason_codes=["RETRY_AUTHORIZED"],
        approved_candidates=list(candidates),
    )


def _accept() -> LoopDirective:
    return LoopDirective(action="ACCEPT", reason_codes=["INCUMBENT_ACCEPTED"])


class ScriptedProvider:
    def __init__(self, directives: dict[int, LoopDirective]) -> None:
        self.directives = directives
        self.contexts: list[Any] = []

    def __call__(self, context: Any) -> LoopDirective:
        self.contexts.append(context)
        return self.directives[context.round_index]


class ScriptedRunner:
    def __init__(
        self,
        metrics_by_coordinate: dict[tuple[int, int], dict[str, object]],
        *,
        interrupt_once: tuple[int, int] | None = None,
    ) -> None:
        self.metrics_by_coordinate = metrics_by_coordinate
        self.interrupt_once = interrupt_once
        self.interrupted = False
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        approved: ApprovedCandidate,
        *,
        round_index: int,
        candidate_index: int,
        resume: bool,
    ) -> ComparableRun:
        self.calls.append(
            {
                "approved": approved,
                "round_index": round_index,
                "candidate_index": candidate_index,
                "resume": resume,
            }
        )
        coordinate = (round_index, candidate_index)
        if coordinate == self.interrupt_once and not self.interrupted:
            self.interrupted = True
            raise KeyboardInterrupt
        run_id = f"candidate_r{round_index:02d}_c{candidate_index:02d}"
        parameter_values = AssemblyParameters().model_dump(mode="json")
        if round_index >= 2:
            parameter_values["disable_post_join"] = True
        if round_index >= 3:
            parameter_values["purge_similarity"] = 0.5
        parameter_values.update(approved.approved_parameters.model_dump(exclude_none=True))
        parameters = AssemblyParameters.model_validate(parameter_values)
        return ComparableRun(
            run_id=run_id,
            attempt_id="attempt_001",
            config=_config(run_id, round_index, parameters),
            metrics=_metrics(run_id, **self.metrics_by_coordinate[coordinate]),
            metrics_path=Path(f"{run_id}.json"),
            parameter_contract_status="PASS",
            execution_status="COMPLETED",
            cpu_hours=0.6,
            walltime_hours=0.1,
        )


def _budget(
    *,
    max_cpu: float = 10.0,
    estimated_cpu: float = 0.5,
) -> LoopBudget:
    return LoopBudget(
        max_cpu_hours=max_cpu,
        max_walltime_hours=10.0,
        estimated_candidate_cpu_hours=estimated_cpu,
        estimated_candidate_walltime_hours=0.1,
    )


def _loop(
    root: Path,
    provider: ScriptedProvider,
    runner: ScriptedRunner,
    *,
    max_candidates: int = 1,
    budget: LoopBudget | None = None,
    comparator: RoundComparator | None = None,
) -> OptimizationLoop:
    return OptimizationLoop(
        root,
        sample_id="sample",
        baseline=_baseline(),
        proposal_provider=provider,
        candidate_runner=runner,
        comparison_context=RoundComparisonContext(
            reference_available=True,
            genome_size_trusted=True,
        ),
        budget=budget or _budget(),
        max_rounds=3,
        max_candidates_per_round=max_candidates,
        comparator=comparator,
    )


def test_baseline_direct_acceptance_launches_no_candidate(tmp_path: Path) -> None:
    provider = ScriptedProvider({1: _accept()})
    runner = ScriptedRunner({})

    state = _loop(tmp_path, provider, runner).run()

    assert state.terminal_outcome == "ACCEPTED_BASELINE"
    assert state.selected_run_id == "baseline"
    assert state.rounds == []
    assert runner.calls == []


def test_round_one_improves_then_current_incumbent_is_accepted(tmp_path: Path) -> None:
    provider = ScriptedProvider({1: _retry(APPROVALS[1]), 2: _accept()})
    runner = ScriptedRunner(
        {
            (1, 1): {
                "contig_n50": 1_300_000,
                "busco_complete": 99.1,
                "kmer_qv": 31.1,
            }
        }
    )

    state = _loop(tmp_path, provider, runner).run()

    assert state.terminal_outcome == "ACCEPTED_CURRENT_INCUMBENT"
    assert state.selected_run_id == "candidate_r01_c01"
    assert len(state.rounds) == 1
    assert state.round_index == 2
    assert len(runner.calls) == 1


def test_round_one_improves_and_round_two_stops_plateau(tmp_path: Path) -> None:
    provider = ScriptedProvider({1: _retry(APPROVALS[1]), 2: _retry(APPROVALS[2])})
    runner = ScriptedRunner(
        {
            (1, 1): {"contig_n50": 1_300_000, "busco_complete": 99.1},
            (2, 1): {"contig_n50": 1_300_000, "busco_complete": 99.1},
        }
    )

    state = _loop(tmp_path, provider, runner).run()

    assert state.terminal_outcome == "STOP_PLATEAU"
    assert state.incumbent.run_id == "candidate_r01_c01"
    assert [item.round_index for item in state.rounds] == [1, 2]
    assert state.rounds[1].comparison.outcome == "STOP_PLATEAU"
    assert [item.incumbent_run_id for item in provider.contexts] == [
        "baseline",
        "candidate_r01_c01",
    ]
    assert provider.contexts[1].incumbent_metrics.contig_n50 == 1_300_000


def test_three_consecutive_improvements_stop_at_max_rounds(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        {
            1: _retry(APPROVALS[1]),
            2: _retry(APPROVALS[2]),
            3: _retry(APPROVALS[3]),
        }
    )
    runner = ScriptedRunner(
        {
            (1, 1): {"contig_n50": 1_300_000, "busco_complete": 99.1},
            (2, 1): {"contig_n50": 1_600_000, "busco_complete": 99.1},
            (3, 1): {"contig_n50": 2_000_000, "busco_complete": 99.1},
        }
    )

    state = _loop(tmp_path, provider, runner).run()

    assert state.terminal_outcome == "STOP_MAX_ROUNDS"
    assert state.selected_run_id == "candidate_r03_c01"
    assert state.incumbent.run_id == "candidate_r03_c01"
    assert [item.round_index for item in state.rounds] == [1, 2, 3]
    assert [call["round_index"] for call in runner.calls] == [1, 2, 3]


def test_round_one_multiple_tradeoffs_stop_conflict(tmp_path: Path) -> None:
    second = _approved(
        "round_one_second",
        CandidateParameters(purge_similarity=0.45),
    )
    provider = ScriptedProvider({1: _retry(APPROVALS[1], second)})
    runner = ScriptedRunner(
        {
            (1, 1): {"contig_n50": 1_300_000, "busco_complete": 97.0},
            (1, 2): {"contig_n50": 900_000, "busco_complete": 99.5},
        }
    )

    state = _loop(tmp_path, provider, runner, max_candidates=2).run()

    assert state.terminal_outcome == "STOP_CONFLICT"
    assert len(state.rounds) == 1
    assert state.rounds[0].comparison.outcome == "STOP_CONFLICT"


def test_round_two_interruption_resumes_round_two_without_rerunning_round_one(
    tmp_path: Path,
) -> None:
    directives = {1: _retry(APPROVALS[1]), 2: _retry(APPROVALS[2])}
    provider = ScriptedProvider(directives)
    runner = ScriptedRunner(
        {
            (1, 1): {"contig_n50": 1_300_000, "busco_complete": 99.1},
            (2, 1): {"contig_n50": 1_300_000, "busco_complete": 99.1},
        },
        interrupt_once=(2, 1),
    )
    first_loop = _loop(tmp_path, provider, runner)

    with pytest.raises(KeyboardInterrupt):
        first_loop.run()

    interrupted = json.loads((tmp_path / "optimization_loop_state.json").read_text())
    assert interrupted["round_index"] == 2
    assert interrupted["phase"] == "EXECUTE"
    assert interrupted["active_candidate_index"] == 1
    resumed = _loop(tmp_path, provider, runner).run(resume=True)

    assert resumed.terminal_outcome == "STOP_PLATEAU"
    assert [item.round_index for item in resumed.rounds] == [1, 2]
    assert sum(call["round_index"] == 1 for call in runner.calls) == 1
    round_two_calls = [call for call in runner.calls if call["round_index"] == 2]
    assert [call["resume"] for call in round_two_calls] == [False, True]


def test_seen_projected_parameter_set_stops_without_duplicate_execution(
    tmp_path: Path,
) -> None:
    provider = ScriptedProvider({1: _retry(APPROVALS[1]), 2: _retry(APPROVALS[1])})
    runner = ScriptedRunner({(1, 1): {"contig_n50": 1_300_000, "busco_complete": 99.1}})

    state = _loop(tmp_path, provider, runner).run()

    assert state.terminal_outcome == "NO_UNIQUE_CANDIDATE"
    assert len(runner.calls) == 1
    assert len(state.seen_parameter_fingerprints) == 2


def test_cpu_budget_allows_first_candidate_and_forbids_second(tmp_path: Path) -> None:
    second = _approved(
        "round_one_second",
        CandidateParameters(purge_similarity=0.45),
    )
    provider = ScriptedProvider({1: _retry(APPROVALS[1], second)})
    runner = ScriptedRunner({(1, 1): {"contig_n50": 1_300_000, "busco_complete": 99.1}})

    state = _loop(
        tmp_path,
        provider,
        runner,
        max_candidates=2,
        budget=_budget(max_cpu=1.0, estimated_cpu=0.6),
    ).run()

    assert state.terminal_outcome == "STOP_BUDGET"
    assert state.budget.candidates_started == 1
    assert state.budget.consumed_cpu_hours == pytest.approx(0.6)
    assert len(runner.calls) == 1
    assert state.next_candidate_index == 2


def test_interruption_after_post_qc_resumes_compare_without_rerunning_candidate(
    tmp_path: Path,
) -> None:
    class InterruptOnceComparator(RoundComparator):
        def __init__(self) -> None:
            super().__init__()
            self.interrupted = False

        def compare_round(self, **kwargs: Any) -> RoundComparison:
            if not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt
            return super().compare_round(**kwargs)

    provider = ScriptedProvider({1: _retry(APPROVALS[1]), 2: _accept()})
    runner = ScriptedRunner({(1, 1): {"contig_n50": 1_300_000, "busco_complete": 99.1}})
    comparator = InterruptOnceComparator()
    loop = _loop(tmp_path, provider, runner, comparator=comparator)

    with pytest.raises(KeyboardInterrupt):
        loop.run()

    interrupted = json.loads((tmp_path / "optimization_loop_state.json").read_text())
    assert interrupted["phase"] == "COMPARE"
    assert len(interrupted["candidate_results"]) == 1
    state = _loop(
        tmp_path,
        provider,
        runner,
        comparator=comparator,
    ).run(resume=True)

    assert state.terminal_outcome == "ACCEPTED_CURRENT_INCUMBENT"
    assert len(runner.calls) == 1
