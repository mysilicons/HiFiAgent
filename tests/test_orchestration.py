"""Portable acceptance matrix for production stages 5 through 7."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import cast

import pytest
import yaml
from pydantic import ValidationError

import hifi_agent.orchestration.controller as controller_module
from hifi_agent.decision.client import LLMClientResult, StructuredLLMClient
from hifi_agent.decision.models import (
    AuthorizedEvidence,
    DecisionContext,
    ProposalDirective,
    RawProposal,
    RetrievalTrace,
)
from hifi_agent.decision.rules import build_rule_directive
from hifi_agent.decision.service import ProposalService
from hifi_agent.exceptions import (
    AgentStateError,
    InterruptedExecutionError,
    LLMProviderError,
    ToolExecutionError,
)
from hifi_agent.executors.models import (
    AssemblyInputManifest,
    AttemptCoordinate,
    ExecutionEstimate,
    InputArtifact,
    WorkflowInvocation,
    WorkflowResult,
)
from hifi_agent.orchestration.budget import BudgetLedger, BudgetResource
from hifi_agent.orchestration.comparison import (
    BaselineReview,
    CandidateComparison,
    RoundComparator,
    RoundComparison,
)
from hifi_agent.orchestration.controller import (
    CoordinatorResult,
    ProposalServiceFactory,
    RunCoordinator,
)
from hifi_agent.orchestration.lock import RunLock
from hifi_agent.orchestration.manifests import ResourceUsage
from hifi_agent.orchestration.runtime_models import RunPhase, RunState
from hifi_agent.orchestration.verifier import verify_run
from hifi_agent.reporting.models import FinalSummary
from hifi_agent.reporting.service import ReportService
from hifi_agent.schemas.assembly import RiskLevel
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.schemas.sample import SampleConfig


class StaticRetriever:
    """Return frozen authorization for every portable candidate parameter."""

    def __init__(self, calls: list[int] | None = None) -> None:
        self.calls = calls

    def retrieve(
        self,
        context: DecisionContext,
        directive: ProposalDirective,
    ) -> RetrievalTrace:
        del directive
        if self.calls is not None:
            self.calls.append(context.round_index)
        evidence = tuple(
            AuthorizedEvidence(
                source_id=source_id,
                chunk_id=f"{source_id}-chunk",
                chunk_sha256=character * 64,
                index_sha256="d" * 64,
                authorized_parameters=(
                    "purge_level",
                    "purge_similarity",
                    "hom_cov",
                    "disable_post_join",
                ),
                source_version="0.25.0",
                target_hifiasm_version="0.25.0",
                review_after=date(2099, 1, 1),
                text="Reviewed fixture guidance for one bounded parameter change.",
            )
            for source_id, character in (
                ("official", "a"),
                ("hifiasm_faq", "b"),
                ("hifiasm_parameters", "c"),
            )
        )
        return RetrievalTrace(
            query=f"round {context.round_index} current incumbent",
            index_sha256="d" * 64,
            evidence=evidence,
        )


class MetricsRunner:
    """Portable assembly runner whose action stream is tied to real current coordinates."""

    def __init__(self, actions: list[AssemblyMetrics | str]) -> None:
        self.actions = list(actions)
        self.calls: list[WorkflowInvocation] = []

    def run(self, invocation: WorkflowInvocation) -> WorkflowResult:
        self.calls.append(invocation)
        if not self.actions:
            raise AssertionError("portable runner action stream was exhausted")
        action = self.actions.pop(0)
        if action == "interrupt":
            raise InterruptedExecutionError("fixture SIGTERM")
        if action == "fail":
            raise ToolExecutionError("fixture hifiasm failure")
        if isinstance(action, str):
            metrics = _complete_metrics()
        else:
            metrics = action
        assembly = invocation.attempt_root / "assembly/fasta/primary.fa"
        post_qc = invocation.attempt_root / "post_qc/assembly_metrics.json"
        assembly.parent.mkdir(parents=True, exist_ok=True)
        post_qc.parent.mkdir(parents=True, exist_ok=True)
        assembly.write_text(">contig\nACGT\n")
        post_qc.write_text(
            metrics.model_copy(
                update={"run_id": invocation.coordinate.logical_run_id}
            ).model_dump_json(indent=2)
            + "\n"
        )
        realized = list(invocation.rendered_hifiasm_argv)
        if action == "mismatch":
            realized[realized.index("-l") + 1] = (
                "1" if realized[realized.index("-l") + 1] != "1" else "2"
            )
        return WorkflowResult(
            command=("fixture-nextflow", "run"),
            realized_hifiasm_argv=tuple(realized),
            artifacts=(assembly, post_qc),
            tool_versions={"hifiasm": "0.25.0", "fixture": "hifi-agent"},
            resource_usage=ResourceUsage(cpu_hours=1.0, walltime_hours=0.5),
        )


class TimeoutClient:
    """Structured provider that deterministically represents a timeout."""

    provider = "fixture"
    model = "timeout-production"

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMClientResult:
        del system_prompt, user_prompt
        raise LLMProviderError("fixture provider timeout")


def _complete_metrics(
    *,
    busco_complete: float = 94.0,
    busco_duplicated: float = 8.0,
    contig_n50: int = 1_000,
    mapped_read_fraction: float = 0.99,
) -> AssemblyMetrics:
    return AssemblyMetrics(
        run_id="fixture",
        assembly_size=10_000,
        contig_count=10,
        contig_n50=contig_n50,
        busco_complete=busco_complete,
        busco_duplicated=busco_duplicated,
        kmer_completeness=96.0,
        kmer_qv=40.0,
        mapped_read_fraction=mapped_read_fraction,
        coverage_mean=30.0,
        coverage_cv=0.20,
    )


def _config(
    tmp_path: Path,
    *,
    optimization: dict[str, object] | None = None,
    budget: dict[str, object] | None = None,
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
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
                "resources": {"max_threads": 4, "max_memory_gb": 16},
                "optimization": {
                    "max_rounds": 3,
                    "max_candidates_per_round": 1,
                    **(optimization or {}),
                },
                "execution_budget": {
                    "min_free_disk_gib": 0,
                    **(budget or {}),
                },
            }
        )
    )
    return path


def _pre_qc(
    sample: SampleConfig,
    *,
    resume: bool,
) -> AssemblyInputManifest:
    del resume
    metadata = sample.outdir / "00_metadata"
    reads_manifest = metadata / "hifi_reads.list"
    reads_manifest.write_text(f"{sample.hifi_reads[0]}\n")
    raw = sample.outdir / "01_pre_qc/raw_metrics.json"
    meryl = sample.outdir / "01_pre_qc/kmer/read.meryl"
    histogram = sample.outdir / "01_pre_qc/kmer/kmer_histogram.tsv"
    inventory = sample.outdir / "01_pre_qc/artifacts_manifest.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    meryl.mkdir(parents=True, exist_ok=True)
    (meryl / "data").write_text("fixture meryl db")
    raw.write_text('{"schema_id": "hifi-agent"}\n')
    histogram.write_text("1\t1\n")
    inventory.write_text('{"schema_id": "hifi-agent"}\n')
    return AssemblyInputManifest(
        artifacts={
            role: InputArtifact.from_path(path)
            for role, path in {
                "resolved_config": metadata / "resolved_config.yaml",
                "validation_receipt": metadata / "validation_receipt.json",
                "input_checksums": metadata / "input_checksums.tsv",
                "reads_manifest": reads_manifest,
                "raw_metrics": raw,
                "meryl_db": meryl,
                "kmer_histogram": histogram,
                "pre_qc_inventory": inventory,
            }.items()
        }
    )


def _provider_factory(
    retrieval_calls: list[int] | None = None,
) -> ProposalServiceFactory:
    def factory(
        run_dir: Path,
        budget: BudgetLedger,
        confirmation_risk_levels: set[RiskLevel],
    ) -> ProposalService:
        return ProposalService(
            run_dir,
            budget=budget,
            retriever=StaticRetriever(retrieval_calls),
            confirmation_risk_levels=confirmation_risk_levels,
        )

    return factory


def _proposal(
    round_index: int,
    proposal_index: int,
    changes: dict[str, bool | int | float | str | None],
    *,
    risk_level: RiskLevel = "low",
) -> RawProposal:
    return RawProposal(
        proposal_id=f"round_{round_index:02d}.fixture_{proposal_index:02d}",
        origin="rule",
        changes=changes,
        source_ids=("official",),
        metric_ids=("busco_complete",),
        expected_metric_effects={"busco_complete": "increase"},
        rationale="Apply one reviewed change to the current incumbent.",
        risk_level=risk_level,
    )


def _sequence_directive(
    sequence: dict[int, tuple[dict[str, bool | int | float | str | None], ...]],
) -> Callable[[DecisionContext], ProposalDirective]:
    def provider(context: DecisionContext) -> ProposalDirective:
        changes = sequence[context.round_index]
        return ProposalDirective(
            directive_id=f"round_{context.round_index:02d}.fixture",
            action="PROPOSE",
            reason_codes=("PORTABLE_ACCEPTANCE_SCENARIO",),
            proposals=tuple(
                _proposal(context.round_index, index, item)
                for index, item in enumerate(changes, start=1)
            ),
        )

    return provider


def _coordinator(
    config: Path,
    runner: MetricsRunner,
    monkeypatch: pytest.MonkeyPatch,
    *,
    directive_provider: Callable[[DecisionContext], ProposalDirective] | None = None,
    fault_injector: Callable[[str, RunState], None] | None = None,
    estimate_provider: Callable[[AttemptCoordinate], ExecutionEstimate] | None = None,
    llm_client: StructuredLLMClient | None = None,
    retrieval_calls: list[int] | None = None,
) -> RunCoordinator:
    monkeypatch.setattr(controller_module, "run_environment_preflight", lambda _sample: object())
    monkeypatch.setattr(controller_module, "require_environment_preflight", lambda _value: None)

    def materialize(_manifest: object, output: Path) -> Path:
        output.write_text('{"schema_id": "hifi-agent"}\n')
        return output

    monkeypatch.setattr(controller_module, "materialize_environment_manifest", materialize)
    return RunCoordinator(
        config,
        workflow_runner=runner,
        pre_qc_runner=_pre_qc,
        directive_provider=directive_provider or build_rule_directive,
        proposal_service_factory=_provider_factory(retrieval_calls),
        fault_injector=fault_injector,
        estimate_provider=estimate_provider,
        llm_client=llm_client,
    )


def _summary(result: CoordinatorResult) -> FinalSummary:
    return FinalSummary.model_validate_json(result.report_bundle.summary.read_text())


def test_baseline_direct_acceptance_and_disabled_optimization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted_runner = MetricsRunner([_complete_metrics(busco_complete=98.0)])
    accepted = _coordinator(
        _config(tmp_path / "accepted"),
        accepted_runner,
        monkeypatch,
    ).run()
    assert accepted.state.state == RunPhase.TERMINAL
    assert accepted.state.terminal_outcome == "ACCEPTED_BASELINE"
    assert len(accepted_runner.calls) == 1
    assert _summary(accepted).process_exit_code == 0

    disabled_runner = MetricsRunner([AssemblyMetrics(run_id="fixture")])
    disabled = _coordinator(
        _config(tmp_path / "disabled", optimization={"enabled": False}),
        disabled_runner,
        monkeypatch,
    ).run()
    assert disabled.state.terminal_outcome == "ACCEPTED_BASELINE"
    assert _summary(disabled).stop_reason_codes == ("OPTIMIZATION_DISABLED_BY_CONFIG",)


def test_explicit_minimum_candidate_runs_one_controlled_real_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner(
        [
            _complete_metrics(busco_complete=98.0, busco_duplicated=1.0),
            _complete_metrics(busco_complete=98.0, busco_duplicated=1.0),
        ]
    )
    result = _coordinator(
        _config(
            tmp_path,
            optimization={"max_rounds": 1, "minimum_candidate_runs": 1},
        ),
        runner,
        monkeypatch,
    ).run()

    assert len(runner.calls) == 2
    assert result.state.terminal_outcome == "STOP_PLATEAU"
    decision = json.loads(
        (tmp_path / "run/04_decisions/round_01/proposal_decision.json").read_text()
    )
    assert decision["approved"][0]["approved_diff"] == {"purge_similarity": 0.5}
    assert len(decision["approved"][0]["approved_diff"]) == 1


def test_zero_round_policy_and_baseline_failures_have_explicit_terminal_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zero_round = _coordinator(
        _config(tmp_path / "zero", optimization={"max_rounds": 0}),
        MetricsRunner([_complete_metrics()]),
        monkeypatch,
    ).run()
    assert zero_round.state.terminal_outcome == "STOP_MAX_ROUNDS"
    assert _summary(zero_round).process_exit_code == 0

    tool_failure = _coordinator(
        _config(tmp_path / "tool-failure", budget={"max_tool_retries": 0}),
        MetricsRunner(["fail"]),
        monkeypatch,
    ).run()
    assert tool_failure.state.terminal_outcome == "FAILED_TOOL"
    assert _summary(tool_failure).attempts[0].status == "FAILED"

    contract_failure = _coordinator(
        _config(tmp_path / "contract-failure"),
        MetricsRunner(["mismatch"]),
        monkeypatch,
    ).run()
    assert contract_failure.state.terminal_outcome == "FAILED_PARAMETER_CONTRACT"
    assert _summary(contract_failure).process_exit_code == 4


def test_rule_stop_is_terminal_and_never_retrieves_or_calls_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrieval_calls: list[int] = []
    runner = MetricsRunner(
        [
            _complete_metrics(
                busco_complete=98.0,
                busco_duplicated=1.0,
                mapped_read_fraction=0.94,
            )
        ]
    )
    result = _coordinator(
        _config(tmp_path),
        runner,
        monkeypatch,
        retrieval_calls=retrieval_calls,
    ).run()
    assert result.state.terminal_outcome == "STOP_RULE_DECISION"
    assert retrieval_calls == []
    assert _summary(result).llm_activity[0].status == "NOT_CALLED"

    context = DecisionContext.model_validate_json(
        (tmp_path / "run/04_decisions/round_01/decision_context.json").read_text()
    )

    def with_metric(metric_id: str, value: float) -> DecisionContext:
        features = dict(context.qc_feature_bundle.features)
        features[metric_id] = features[metric_id].model_copy(
            update={
                "value": value,
                "availability": "AVAILABLE",
                "applicability": "APPLICABLE",
                "confidence": "high",
            }
        )
        return context.model_copy(
            update={
                "incumbent_metrics": context.incumbent_metrics.model_copy(
                    update={metric_id: value}
                ),
                "qc_feature_bundle": context.qc_feature_bundle.model_copy(
                    update={"features": features}
                ),
                "applicable_metric_ids": tuple(sorted({*context.applicable_metric_ids, metric_id})),
            }
        )

    for metric_id, value in (
        ("assembly_size_ratio", 1.2),
        ("coverage_cv", 0.4),
        ("kmer_completeness", 89.0),
        ("busco_complete", 94.0),
    ):
        directive = build_rule_directive(with_metric(metric_id, value))
        assert directive.action == "PROPOSE"
        assert metric_id.upper() in directive.reason_codes


def test_production_rule_proposal_accepts_round_one_improvement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner([_complete_metrics(), _complete_metrics(busco_complete=96.0)])
    result = _coordinator(
        _config(tmp_path, optimization={"max_rounds": 1}),
        runner,
        monkeypatch,
    ).run()
    assert result.state.terminal_outcome == "STOP_MAX_ROUNDS"
    decision = json.loads(
        (tmp_path / "run/04_decisions/round_01/proposal_decision.json").read_text()
    )
    assert len(decision["approved"]) == 1
    assert decision["approved"][0]["approved_diff"] == {"purge_level": 2}
    assert "CANDIDATE_LIMIT_EXCEEDED" in decision["rejected"][0]["reason_codes"]


def test_candidate_retry_is_a_new_attempt_and_budgeted_once_per_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner([_complete_metrics(), "fail", _complete_metrics(busco_complete=96.0)])
    result = _coordinator(
        _config(tmp_path, optimization={"max_rounds": 1}),
        runner,
        monkeypatch,
        directive_provider=_sequence_directive({1: ({"purge_level": 2},)}),
    ).run()
    summary = _summary(result)
    assert result.state.terminal_outcome == "STOP_MAX_ROUNDS"
    assert [item.status for item in summary.attempts] == ["COMPLETED", "FAILED", "COMPLETED"]
    assert summary.attempts[-1].attempt_id.endswith("attempt_002")
    assert summary.budget_committed[BudgetResource.ASSEMBLY.value] == 3
    assert summary.budget_committed[BudgetResource.TOOL_RETRY.value] == 1


def test_confirmation_gate_stops_medium_high_risk_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def risky(context: DecisionContext) -> ProposalDirective:
        return ProposalDirective(
            directive_id=f"round_{context.round_index:02d}.risk",
            action="PROPOSE",
            reason_codes=("FIXTURE_RISK",),
            proposals=(
                _proposal(
                    context.round_index,
                    1,
                    {"purge_level": 2},
                    risk_level="medium_high",
                ),
            ),
        )

    runner = MetricsRunner([_complete_metrics()])
    result = _coordinator(
        _config(tmp_path, optimization={"max_rounds": 1}),
        runner,
        monkeypatch,
        directive_provider=risky,
    ).run()
    assert result.state.terminal_outcome == "STOP_CONFIRMATION_REQUIRED"
    assert len(runner.calls) == 1
    assert _summary(result).process_exit_code == 3


def test_round_one_improvement_then_round_two_plateau_and_all_fault_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hooks: list[str] = []
    runner = MetricsRunner(
        [
            _complete_metrics(busco_complete=94.0),
            _complete_metrics(busco_complete=95.5),
            _complete_metrics(busco_complete=95.5),
        ]
    )
    result = _coordinator(
        _config(tmp_path),
        runner,
        monkeypatch,
        directive_provider=_sequence_directive(
            {1: ({"purge_level": 2},), 2: ({"purge_similarity": 0.50},)}
        ),
        fault_injector=lambda hook, _state: hooks.append(hook),
    ).run()
    assert result.state.terminal_outcome == "STOP_PLATEAU"
    assert result.state.round_index == 2
    assert len(runner.calls) == 3
    expected_hooks = {
        "before_pre_qc",
        "after_pre_qc",
        "before_baseline_attempt",
        "after_baseline_attempt",
        "before_proposal",
        "after_proposal",
        "before_candidate_attempt",
        "after_candidate_attempt",
        "before_round_comparison",
        "after_round_comparison",
        "before_reporting",
        "after_reporting",
        "before_deep_verification",
        "after_deep_verification",
        "before_final_report_materialization",
        "after_final_report_materialization",
    }
    assert expected_hooks <= set(hooks)


def test_three_round_improvement_builds_real_incumbent_chain_and_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner(
        [
            _complete_metrics(busco_complete=94.0),
            _complete_metrics(busco_complete=95.2),
            _complete_metrics(busco_complete=96.4),
            _complete_metrics(busco_complete=97.6),
        ]
    )
    result = _coordinator(
        _config(tmp_path),
        runner,
        monkeypatch,
        directive_provider=_sequence_directive(
            {
                1: ({"purge_level": 2},),
                2: ({"purge_similarity": 0.50},),
                3: ({"hom_cov": 20},),
            }
        ),
    ).run()
    assert result.state.terminal_outcome == "STOP_MAX_ROUNDS"
    summary = _summary(result)
    assert len(summary.incumbent_chain) == 4
    assert len(summary.attempts) == 4
    assert len(summary.rounds) == 4
    assert len(summary.proposals) == 3
    assert summary.selected_run_ref == result.state.incumbent_run_ref
    assert summary.budget_committed[BudgetResource.ASSEMBLY.value] == 4
    assert summary.budget_reserved[BudgetResource.ASSEMBLY.value] == 0
    for round_index in range(1, 4):
        round_dir = tmp_path / f"run/04_decisions/round_{round_index:02d}"
        assert (round_dir / "round_manifest.json").is_file()
        assert (round_dir / "comparison.json").is_file()
    round_two_context = json.loads(
        (tmp_path / "run/04_decisions/round_02/decision_context.json").read_text()
    )
    assert "round_01" in round_two_context["incumbent_attempt_ref"]
    assert verify_run(tmp_path / "run", deep=True).status == "PASS"

    with result.report_bundle.runs_tsv.open(newline="") as handle:
        run_rows = list(csv.DictReader(handle, delimiter="\t"))
    with result.report_bundle.parameters_tsv.open(newline="") as handle:
        parameter_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(run_rows) == len(summary.attempts)
    assert len(parameter_rows) == len(summary.attempts) * 4
    assert {"requested", "approved", "rendered_argv_json", "realized"} <= set(parameter_rows[0])

    def summary_payload() -> dict[str, object]:
        return cast(dict[str, object], json.loads(summary.model_dump_json()))

    invalid_attempt = summary_payload()
    cast(list[dict[str, object]], invalid_attempt["attempts"])[0]["attempt_ref"] = "../escape"
    with pytest.raises(ValidationError, match="run-relative"):
        FinalSummary.model_validate(invalid_attempt)
    invalid_proposal = summary_payload()
    cast(list[dict[str, object]], invalid_proposal["proposals"])[0]["executed_attempt_refs"] = [
        "/outside"
    ]
    with pytest.raises(ValidationError, match="run-relative"):
        FinalSummary.model_validate(invalid_proposal)
    invalid_selected = summary_payload()
    invalid_selected["selected_run_ref"] = "/outside"
    with pytest.raises(ValidationError, match="run-relative"):
        FinalSummary.model_validate(invalid_selected)
    invalid_chain = summary_payload()
    invalid_chain["incumbent_chain"] = ["/outside"]
    with pytest.raises(ValidationError, match="run-relative"):
        FinalSummary.model_validate(invalid_chain)
    wrong_start = summary_payload()
    cast(list[str], wrong_start["incumbent_chain"])[0] = "wrong-baseline"
    with pytest.raises(ValidationError, match="does not start"):
        FinalSummary.model_validate(wrong_start)
    wrong_tail = summary_payload()
    wrong_tail["selected_run_ref"] = cast(list[str], wrong_tail["incumbent_chain"])[0]
    with pytest.raises(ValidationError, match="chain tail"):
        FinalSummary.model_validate(wrong_tail)

    service = ReportService(tmp_path / "run")
    before = {path: path.read_bytes() for path in service.bundle.paths()}
    service.generate(result.state, verification_status=summary.verification_status)
    after = {path: path.read_bytes() for path in service.bundle.paths()}
    assert after == before


@pytest.mark.parametrize(
    ("candidate_metrics", "expected_outcome", "expected_selected"),
    [
        (
            (
                _complete_metrics(busco_complete=96.0),
                _complete_metrics(busco_complete=94.0),
            ),
            "STOP_MAX_ROUNDS",
            1,
        ),
        (
            (
                _complete_metrics(busco_complete=96.0),
                _complete_metrics(busco_complete=94.0, contig_n50=1_200),
            ),
            "STOP_HUMAN_REVIEW",
            None,
        ),
    ],
)
def test_two_candidate_unique_winner_and_pareto_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_metrics: tuple[AssemblyMetrics, AssemblyMetrics],
    expected_outcome: str,
    expected_selected: int | None,
) -> None:
    runner = MetricsRunner([_complete_metrics(), *candidate_metrics])
    result = _coordinator(
        _config(
            tmp_path,
            optimization={"max_rounds": 1, "max_candidates_per_round": 2},
        ),
        runner,
        monkeypatch,
        directive_provider=_sequence_directive(
            {1: ({"purge_level": 2}, {"purge_similarity": 0.50})}
        ),
    ).run()
    assert result.state.terminal_outcome == expected_outcome
    comparison = json.loads((tmp_path / "run/04_decisions/round_01/comparison.json").read_text())
    selected = comparison["selected_attempt_ref"]
    if expected_selected is None:
        assert selected is None
        assert _summary(result).process_exit_code == 3
    else:
        assert f"candidate_{expected_selected:02d}" in selected


def test_comparator_fails_closed_for_missing_and_regressed_evidence(
    tmp_path: Path,
) -> None:
    comparator = RoundComparator(Path(__file__).parents[1] / "configs/comparison_policy.yaml")
    incumbent = _complete_metrics()
    missing = incumbent.model_copy(update={"busco_complete": 96.0, "kmer_qv": None})
    missing_result = comparator.compare(
        round_index=1,
        incumbent_attempt_ref=Path("02_assembly/baseline/attempt_001/attempt_manifest.json"),
        incumbent_metrics=incumbent,
        candidates=((1, Path("candidate-missing.json"), missing),),
        reference_available=False,
        trusted_genome_size=False,
    )
    assert missing_result.outcome == "INSUFFICIENT_EVIDENCE"
    assert missing_result.candidates[0].missing_required_metric_ids == ("kmer_qv",)

    hard_regression = incumbent.model_copy(update={"busco_complete": 90.0, "contig_n50": 2_000})
    hard_result = comparator.compare(
        round_index=1,
        incumbent_attempt_ref=Path("incumbent.json"),
        incumbent_metrics=incumbent,
        candidates=((1, Path("candidate-hard.json"), hard_regression),),
        reference_available=False,
        trusted_genome_size=False,
    )
    assert hard_result.outcome == "KEEP_INCUMBENT"
    assert "busco_complete" in hard_result.candidates[0].hard_regression_metric_ids

    material_regression = incumbent.model_copy(update={"busco_complete": 92.5, "contig_n50": 2_000})
    regression_result = comparator.compare(
        round_index=1,
        incumbent_attempt_ref=Path("incumbent.json"),
        incumbent_metrics=incumbent,
        candidates=((1, Path("candidate-regression.json"), material_regression),),
        reference_available=False,
        trusted_genome_size=False,
    )
    assert regression_result.outcome == "KEEP_INCUMBENT"
    assert "busco_complete" in regression_result.candidates[0].regressed_metric_ids

    dominant_result = comparator.compare(
        round_index=1,
        incumbent_attempt_ref=Path("incumbent.json"),
        incumbent_metrics=incumbent,
        candidates=(
            (1, Path("candidate-one.json"), incumbent.model_copy(update={"busco_complete": 97.0})),
            (2, Path("candidate-two.json"), incumbent.model_copy(update={"busco_complete": 96.0})),
        ),
        reference_available=False,
        trusted_genome_size=False,
    )
    assert dominant_result.outcome == "ACCEPT_CANDIDATE"
    assert dominant_result.reason_codes == ("UNIQUE_PARETO_DOMINANT_CANDIDATE",)

    ratio_result = comparator.compare(
        round_index=1,
        incumbent_attempt_ref=Path("incumbent.json"),
        incumbent_metrics=incumbent.model_copy(update={"assembly_size_ratio": 1.2}),
        candidates=(
            (
                1,
                Path("candidate-ratio.json"),
                incumbent.model_copy(update={"assembly_size_ratio": 1.0}),
            ),
        ),
        reference_available=False,
        trusted_genome_size=True,
    )
    assert ratio_result.outcome == "ACCEPT_CANDIDATE"

    with pytest.raises(AgentStateError, match="comparison policy is invalid"):
        RoundComparator(tmp_path / "missing-policy.yaml")

    with pytest.raises(ValidationError, match="run-relative"):
        BaselineReview(
            status="ACCEPTED",
            baseline_attempt_ref=Path("/outside/baseline.json"),
            policy_sha256="a" * 64,
            checked_metric_ids=(),
            reason_codes=("TEST",),
        )
    with pytest.raises(ValidationError, match="run-relative"):
        CandidateComparison(
            candidate_index=1,
            candidate_attempt_ref=Path("../outside.json"),
            comparison_eligible=False,
            metrics=(),
            reason_codes=("TEST",),
        )
    with pytest.raises(ValidationError, match="run-relative"):
        RoundComparison(
            round_index=1,
            incumbent_before_ref=Path("incumbent.json"),
            policy_id="fixture",
            policy_sha256="a" * 64,
            outcome="KEEP_INCUMBENT",
            selected_attempt_ref=Path("/outside/selected.json"),
            candidates=(),
            reason_codes=("TEST",),
        )


def test_all_candidates_failed_and_parameter_contract_violation_are_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed_runner = MetricsRunner([_complete_metrics(), "fail", "fail"])
    failed = _coordinator(
        _config(
            tmp_path / "failed",
            optimization={"max_rounds": 1, "max_candidates_per_round": 2},
            budget={"max_tool_retries": 0},
        ),
        failed_runner,
        monkeypatch,
        directive_provider=_sequence_directive(
            {1: ({"purge_level": 2}, {"purge_similarity": 0.50})}
        ),
    ).run()
    assert failed.state.terminal_outcome == "FAILED_TOOL"
    assert _summary(failed).process_exit_code == 4
    assert [item.status for item in _summary(failed).attempts] == [
        "COMPLETED",
        "FAILED",
        "FAILED",
    ]
    failed_service = ReportService(tmp_path / "failed/run")
    before = {path: path.read_bytes() for path in failed_service.bundle.paths()}
    failed_service.generate(failed.state, verification_status="PASS")
    assert {path: path.read_bytes() for path in failed_service.bundle.paths()} == before

    mismatch_runner = MetricsRunner([_complete_metrics(), "mismatch"])
    mismatch = _coordinator(
        _config(tmp_path / "mismatch", optimization={"max_rounds": 1}),
        mismatch_runner,
        monkeypatch,
        directive_provider=_sequence_directive({1: ({"purge_level": 2},)}),
    ).run()
    assert mismatch.state.terminal_outcome == "FAILED_PARAMETER_CONTRACT"
    assert _summary(mismatch).attempts[-1].status == "CONTRACT_VIOLATION"


def test_round_two_budget_stop_occurs_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner([_complete_metrics(), _complete_metrics(busco_complete=96.0)])
    result = _coordinator(
        _config(tmp_path, budget={"max_total_assemblies": 2}),
        runner,
        monkeypatch,
        directive_provider=_sequence_directive(
            {1: ({"purge_level": 2},), 2: ({"purge_similarity": 0.50},)}
        ),
    ).run()
    assert result.state.terminal_outcome == "STOP_BUDGET"
    assert len(runner.calls) == 2
    summary = _summary(result)
    assert summary.process_exit_code == 3
    assert summary.proposals[-1].disposition == "REJECTED"
    assert "ASSEMBLY_BUDGET_EXHAUSTED" in summary.proposals[-1].reason_codes


def test_round_two_interruption_resumes_same_attempt_without_rebilling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner(
        [
            _complete_metrics(),
            _complete_metrics(busco_complete=96.0),
            "interrupt",
            _complete_metrics(busco_complete=96.0),
        ]
    )
    config = _config(tmp_path)
    directive = _sequence_directive({1: ({"purge_level": 2},), 2: ({"purge_similarity": 0.50},)})
    coordinator = _coordinator(
        config,
        runner,
        monkeypatch,
        directive_provider=directive,
    )
    with pytest.raises(InterruptedExecutionError, match="rerun with --resume"):
        coordinator.run()
    interrupted_state = json.loads((tmp_path / "run/05_agent/run_state.json").read_text())
    assert interrupted_state["state"] == "CANDIDATE_ASSEMBLY"
    assert interrupted_state["round_index"] == 2

    result = _coordinator(
        config,
        runner,
        monkeypatch,
        directive_provider=directive,
    ).run(resume=True)
    assert result.state.terminal_outcome == "STOP_PLATEAU"
    assert runner.calls[-1].resume is True
    assert runner.calls[-1].coordinate.round_index == 2
    ledger = BudgetLedger(tmp_path / "run").snapshot()
    assert ledger.committed[BudgetResource.ASSEMBLY] == 3
    assert ledger.reserved[BudgetResource.ASSEMBLY] == 0


def test_completed_candidate_survives_post_launch_controller_fault_without_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired = False

    def fault(hook: str, _state: RunState) -> None:
        nonlocal fired
        if hook == "after_candidate_attempt" and not fired:
            fired = True
            raise InterruptedExecutionError("fixture controller terminated after manifest")

    runner = MetricsRunner([_complete_metrics(), _complete_metrics(busco_complete=96.0)])
    config = _config(tmp_path, optimization={"max_rounds": 1})
    directive = _sequence_directive({1: ({"purge_level": 2},)})
    coordinator = _coordinator(
        config,
        runner,
        monkeypatch,
        directive_provider=directive,
        fault_injector=fault,
    )
    with pytest.raises(InterruptedExecutionError, match="after manifest"):
        coordinator.run()
    manifest = tmp_path / "run/02_assembly/round_01/candidate_01/attempt_001/attempt_manifest.json"
    assert manifest.is_file()
    assert len(runner.calls) == 2
    before = BudgetLedger(tmp_path / "run").snapshot()

    result = _coordinator(
        config,
        runner,
        monkeypatch,
        directive_provider=directive,
        fault_injector=fault,
    ).run(resume=True)
    after = BudgetLedger(tmp_path / "run").snapshot()
    assert result.state.terminal_outcome == "STOP_MAX_ROUNDS"
    assert len(runner.calls) == 2
    assert before.committed[BudgetResource.ASSEMBLY] == 2
    assert after.committed[BudgetResource.ASSEMBLY] == 2


def test_round_three_global_duplicates_stop_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner(
        [
            _complete_metrics(),
            _complete_metrics(busco_complete=96.0),
            _complete_metrics(busco_complete=97.5),
        ]
    )
    result = _coordinator(
        _config(tmp_path),
        runner,
        monkeypatch,
        directive_provider=_sequence_directive(
            {
                1: ({"purge_level": 2},),
                2: ({"purge_similarity": 0.50},),
                3: ({"purge_similarity": 0.55},),
            }
        ),
    ).run()
    assert result.state.terminal_outcome == "STOP_NO_LEGAL_CANDIDATE"
    assert len(runner.calls) == 3
    assert not (tmp_path / "run/02_assembly/round_03").exists()
    summary = _summary(result)
    assert "GLOBAL_PARAMETER_FINGERPRINT_DUPLICATE" in summary.proposals[-1].reason_codes


def test_required_llm_timeout_has_exit_five_and_no_candidate_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner([_complete_metrics()])
    result = _coordinator(
        _config(
            tmp_path,
            optimization={"decision_mode": "hybrid", "require_llm": True},
        ),
        runner,
        monkeypatch,
        directive_provider=_sequence_directive({1: ({"purge_level": 2},)}),
        llm_client=TimeoutClient(),
    ).run()
    summary = _summary(result)
    assert result.state.terminal_outcome == "FAILED_REQUIRED_LLM"
    assert summary.process_exit_code == 5
    assert summary.llm_activity[0].status == "FAILED"
    assert len(runner.calls) == 1
    receipt = tmp_path / "run/04_decisions/round_01/llm_call_receipt.json"
    receipt.write_text("tampered receipt\n")
    verification = verify_run(tmp_path / "run", deep=True)
    assert verification.status == "FAIL"
    assert any(
        item.check_id == "MANIFEST_HISTORY" and item.status == "FAIL"
        for item in verification.checks
    )


def test_optional_llm_timeout_falls_back_to_rules_and_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner([_complete_metrics(), _complete_metrics(busco_complete=96.0)])
    result = _coordinator(
        _config(
            tmp_path,
            optimization={
                "max_rounds": 1,
                "decision_mode": "hybrid",
                "require_llm": False,
            },
        ),
        runner,
        monkeypatch,
        directive_provider=_sequence_directive({1: ({"purge_level": 2},)}),
        llm_client=TimeoutClient(),
    ).run()
    summary = _summary(result)
    assert result.state.terminal_outcome == "STOP_MAX_ROUNDS"
    assert summary.llm_activity[0].status == "FAILED"
    assert summary.process_exit_code == 0


def test_disk_floor_stops_before_baseline_launch_and_reports_action_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner([])
    result = _coordinator(
        _config(tmp_path),
        runner,
        monkeypatch,
        estimate_provider=lambda _coordinate: ExecutionEstimate(
            artifact_gib=1.0,
            observed_free_gib=0.5,
        ),
    ).run()
    assert result.state.terminal_outcome == "STOP_BUDGET"
    assert len(runner.calls) == 0
    assert _summary(result).process_exit_code == 3


def test_terminal_report_recovery_concurrency_and_tamper_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner([_complete_metrics(busco_complete=98.0)])
    config = _config(tmp_path)
    coordinator = _coordinator(config, runner, monkeypatch)
    result = coordinator.run()
    original_summary = result.report_bundle.summary.read_bytes()
    result.report_bundle.markdown.unlink()
    result.report_bundle.verification.unlink()
    recovered = _coordinator(config, runner, monkeypatch).run(resume=True)
    assert recovered.report_bundle.markdown.is_file()
    assert recovered.report_bundle.summary.read_bytes() == original_summary
    assert len(runner.calls) == 1

    lock = RunLock(
        tmp_path / "run",
        run_uuid=result.state.identity.run_uuid,
        command=["fixture", "assemble"],
    )
    lock.acquire()
    with pytest.raises(AgentStateError, match="locked"):
        coordinator.run(resume=True)
    lock.release()

    state_path = tmp_path / "run/05_agent/run_state.json"
    payload = json.loads(state_path.read_text())
    payload["terminal_outcome"] = "FORGED"
    state_path.write_text(json.dumps(payload))
    with pytest.raises(AgentStateError, match="checksum"):
        coordinator.run(resume=True)


def test_internal_deep_verification_failure_overrides_scientific_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def corrupt_after_reporting(hook: str, state: RunState) -> None:
        if hook == "after_reporting":
            primary = (
                state.identity.run_dir
                / "02_assembly/baseline/attempt_001/assembly/fasta/primary.fa"
            )
            primary.write_text("fault-injected corruption\n")

    result = _coordinator(
        _config(tmp_path),
        MetricsRunner([_complete_metrics(busco_complete=98.0)]),
        monkeypatch,
        fault_injector=corrupt_after_reporting,
    ).run()
    summary = _summary(result)
    assert result.state.terminal_outcome == "FAILED_STATE_INTEGRITY"
    assert summary.verification_status == "FAIL"
    assert summary.process_exit_code == 4


def test_report_and_critical_artifact_tampering_fail_deep_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MetricsRunner([_complete_metrics(busco_complete=98.0)])
    result = _coordinator(_config(tmp_path), runner, monkeypatch).run()
    result.report_bundle.parameters_tsv.write_text("tampered\n")
    report_failure = verify_run(tmp_path / "run", deep=True)
    assert report_failure.status == "FAIL"
    assert any(
        item.check_id == "TERMINAL_REPORTS" and item.status == "FAIL"
        for item in report_failure.checks
    )

    ReportService(tmp_path / "run").generate(
        result.state,
        verification_status="PASS",
    )
    summary_payload = json.loads(result.report_bundle.summary.read_text())
    summary_payload["process_exit_code"] = 4
    result.report_bundle.summary.write_text(json.dumps(summary_payload))
    exit_contract_failure = verify_run(tmp_path / "run", deep=True)
    assert exit_contract_failure.status == "FAIL"
    assert any(
        item.check_id == "TERMINAL_REPORTS" and item.status == "FAIL"
        for item in exit_contract_failure.checks
    )
    ReportService(tmp_path / "run").generate(
        result.state,
        verification_status="PASS",
    )
    primary = tmp_path / "run/02_assembly/baseline/attempt_001/assembly/fasta/primary.fa"
    primary.write_text("tampered artifact\n")
    artifact_failure = verify_run(tmp_path / "run", deep=True)
    assert artifact_failure.status == "FAIL"
    assert any(
        item.check_id == "DEEP_ARTIFACTS" and item.status == "FAIL"
        for item in artifact_failure.checks
    )
