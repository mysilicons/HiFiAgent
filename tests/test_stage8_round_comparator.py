from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from hifi_agent.agent.models import AssemblyConfig, AssemblyParameters
from hifi_agent.optimization.round_models import (
    ComparableRun,
    RoundComparisonContext,
)
from hifi_agent.optimization.rounds import RoundComparator
from hifi_agent.schemas.metrics import AssemblyMetrics

FIXED_TIME = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _config(
    run_id: str,
    *,
    round_index: int,
    purge_similarity: float = 0.55,
    disable_post_join: bool = False,
) -> AssemblyConfig:
    return AssemblyConfig(
        run_id=run_id,
        input_reads=[Path("reads.fastq")],
        threads=8,
        parameters=AssemblyParameters(
            purge_similarity=purge_similarity,
            disable_post_join=disable_post_join,
        ),
        reason_codes=["STAGE8_TEST"],
        risk_level="medium",
        retry_kind="NONE" if run_id == "baseline" else "PARAMETER_OPTIMIZATION",
        optimization_round=round_index,
    )


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


def _run(
    run_id: str,
    *,
    round_index: int,
    metrics: AssemblyMetrics | None = None,
    contract: Literal["PASS", "FAIL", "MISSING"] = "PASS",
    execution_status: Literal["COMPLETED", "FAILED"] = "COMPLETED",
    purge_similarity: float = 0.55,
    disable_post_join: bool = False,
) -> ComparableRun:
    return ComparableRun(
        run_id=run_id,
        attempt_id="attempt_001",
        config=_config(
            run_id,
            round_index=round_index,
            purge_similarity=purge_similarity,
            disable_post_join=disable_post_join,
        ),
        metrics=metrics,
        metrics_path=Path(f"{run_id}.json"),
        parameter_contract_status=contract,
        execution_status=execution_status,
    )


def _context(
    *,
    reference_available: bool = True,
    genome_size_trusted: bool = True,
) -> RoundComparisonContext:
    return RoundComparisonContext(
        reference_available=reference_available,
        genome_size_trusted=genome_size_trusted,
    )


def test_n50_gain_cannot_override_busco_and_kmer_hard_regression() -> None:
    incumbent = _run("baseline", round_index=0, metrics=_metrics("baseline"))
    candidate = _run(
        "candidate_r01_c01",
        round_index=1,
        metrics=_metrics(
            "candidate_r01_c01",
            contig_n50=1_500_000,
            busco_complete=94.0,
            kmer_qv=27.0,
        ),
        disable_post_join=True,
    )

    result = RoundComparator().compare_round(
        round_index=1,
        incumbent=incumbent,
        candidates=[candidate],
        context=_context(),
        generated_at=FIXED_TIME,
    )

    assessment = result.candidates[0]
    assert assessment.status == "HARD_REGRESSION"
    assert set(assessment.hard_regressions) == {"busco_complete", "kmer_qv"}
    assert "contig_n50" in assessment.material_improvements
    assert result.outcome == "NO_UNIQUE_CANDIDATE"


def test_all_changes_below_material_threshold_stop_plateau() -> None:
    incumbent = _run("baseline", round_index=0, metrics=_metrics("baseline"))
    candidate = _run(
        "candidate_r01_c01",
        round_index=1,
        metrics=_metrics(
            "candidate_r01_c01",
            contig_n50=1_050_000,
            busco_complete=98.2,
            kmer_qv=30.2,
        ),
        disable_post_join=True,
    )

    result = RoundComparator().compare_round(
        round_index=1,
        incumbent=incumbent,
        candidates=[candidate],
        context=_context(),
        generated_at=FIXED_TIME,
    )

    assert result.candidates[0].status == "PLATEAU"
    assert result.outcome == "STOP_PLATEAU"
    assert result.incumbent_after == "baseline"


def test_unique_material_improvement_updates_arbitrary_incumbent(tmp_path: Path) -> None:
    incumbent = _run(
        "candidate_r01_c01",
        round_index=1,
        metrics=_metrics("candidate_r01_c01"),
        disable_post_join=True,
    )
    candidate = _run(
        "candidate_r02_c01",
        round_index=2,
        metrics=_metrics(
            "candidate_r02_c01",
            contig_n50=1_250_000,
            busco_complete=99.1,
            kmer_qv=31.2,
        ),
        purge_similarity=0.5,
        disable_post_join=True,
    )

    result = RoundComparator().compare_round(
        round_index=2,
        incumbent=incumbent,
        candidates=[candidate],
        context=_context(),
        output_dir=tmp_path,
        generated_at=FIXED_TIME,
    )

    assert result.outcome == "INCUMBENT_UPDATED"
    assert result.selected_run_id == "candidate_r02_c01"
    assert result.incumbent_before == "candidate_r01_c01"
    assert result.incumbent_after == "candidate_r02_c01"
    for name in (
        "round_comparison.json",
        "round_comparison.tsv",
        "parameter_diff.tsv",
        "selection_tradeoffs.md",
    ):
        assert (tmp_path / name).is_file()


def test_multiple_nondominated_tradeoffs_stop_for_review() -> None:
    incumbent = _run("baseline", round_index=0, metrics=_metrics("baseline"))
    first = _run(
        "candidate_r01_c01",
        round_index=1,
        metrics=_metrics(
            "candidate_r01_c01",
            contig_n50=1_300_000,
            busco_complete=97.0,
        ),
        disable_post_join=True,
    )
    second = _run(
        "candidate_r01_c02",
        round_index=1,
        metrics=_metrics(
            "candidate_r01_c02",
            contig_n50=900_000,
            busco_complete=99.5,
        ),
        purge_similarity=0.5,
    )

    result = RoundComparator().compare_round(
        round_index=1,
        incumbent=incumbent,
        candidates=[first, second],
        context=_context(),
        generated_at=FIXED_TIME,
    )

    assert result.outcome == "STOP_CONFLICT"
    assert set(result.nondominated_run_ids) == {
        "candidate_r01_c01",
        "candidate_r01_c02",
    }
    assert all(item.status == "TRADEOFF" for item in result.candidates)


def test_missing_core_metric_prevents_automatic_selection() -> None:
    incumbent = _run("baseline", round_index=0, metrics=_metrics("baseline"))
    candidate = _run(
        "candidate_r01_c01",
        round_index=1,
        metrics=_metrics("candidate_r01_c01", kmer_qv=None, contig_n50=1_500_000),
        disable_post_join=True,
    )

    result = RoundComparator().compare_round(
        round_index=1,
        incumbent=incumbent,
        candidates=[candidate],
        context=_context(),
        generated_at=FIXED_TIME,
    )

    assert result.candidates[0].status == "UNAVAILABLE"
    assert result.candidates[0].unavailable_metrics == ["kmer_qv"]
    assert result.outcome == "STOP_INSUFFICIENT_METRICS"


def test_candidate_crossing_acceptance_floor_is_classified_separately() -> None:
    incumbent = _run(
        "baseline",
        round_index=0,
        metrics=_metrics("baseline", kmer_completeness=90.5),
    )
    candidate = _run(
        "candidate_r01_c01",
        round_index=1,
        metrics=_metrics(
            "candidate_r01_c01",
            kmer_completeness=89.5,
            contig_n50=1_300_000,
        ),
        disable_post_join=True,
    )

    result = RoundComparator().compare_round(
        round_index=1,
        incumbent=incumbent,
        candidates=[candidate],
        context=_context(),
        generated_at=FIXED_TIME,
    )

    assessment = result.candidates[0]
    assert assessment.status == "ACCEPTANCE_FAILURE"
    assert assessment.hard_regressions == []
    assert assessment.acceptance_failures == ["KMER_COMPLETENESS_BELOW_ACCEPTANCE_MIN"]
    assert result.outcome == "NO_UNIQUE_CANDIDATE"


def test_reference_and_untrusted_genome_size_metrics_are_not_applicable() -> None:
    incumbent = _run(
        "baseline",
        round_index=0,
        metrics=_metrics("baseline", assembly_size_ratio=1.4, quast_misassemblies=10),
    )
    candidate = _run(
        "candidate_r01_c01",
        round_index=1,
        metrics=_metrics(
            "candidate_r01_c01",
            assembly_size_ratio=2.0,
            quast_misassemblies=100,
            contig_n50=1_300_000,
        ),
        disable_post_join=True,
    )

    result = RoundComparator().compare_round(
        round_index=1,
        incumbent=incumbent,
        candidates=[candidate],
        context=_context(reference_available=False, genome_size_trusted=False),
        generated_at=FIXED_TIME,
    )

    by_metric = {item.metric: item.result for item in result.candidates[0].metric_differences}
    assert by_metric["assembly_size_ratio"] == "NOT_APPLICABLE"
    assert by_metric["quast_misassemblies"] == "NOT_APPLICABLE"
    assert result.outcome == "INCUMBENT_UPDATED"


def test_invalid_parameter_contract_never_enters_selection() -> None:
    incumbent = _run("baseline", round_index=0, metrics=_metrics("baseline"))
    candidate = _run(
        "candidate_r01_c01",
        round_index=1,
        metrics=_metrics("candidate_r01_c01", contig_n50=2_000_000),
        contract="FAIL",
        disable_post_join=True,
    )

    result = RoundComparator().compare_round(
        round_index=1,
        incumbent=incumbent,
        candidates=[candidate],
        context=_context(),
        generated_at=FIXED_TIME,
    )

    assert result.candidates[0].status == "INVALID_CONTRACT"
    assert result.nondominated_run_ids == []
    assert result.outcome == "NO_UNIQUE_CANDIDATE"


def test_better_candidate_dominates_other_candidate() -> None:
    incumbent = _run("baseline", round_index=0, metrics=_metrics("baseline"))
    winner = _run(
        "candidate_r01_c01",
        round_index=1,
        metrics=_metrics(
            "candidate_r01_c01",
            contig_n50=1_300_000,
            busco_complete=99.5,
            kmer_qv=31.5,
        ),
        disable_post_join=True,
    )
    weaker = _run(
        "candidate_r01_c02",
        round_index=1,
        metrics=_metrics(
            "candidate_r01_c02",
            contig_n50=1_150_000,
            busco_complete=99.1,
            kmer_qv=31.0,
        ),
        purge_similarity=0.5,
    )

    result = RoundComparator().compare_round(
        round_index=1,
        incumbent=incumbent,
        candidates=[winner, weaker],
        context=_context(),
        generated_at=FIXED_TIME,
    )

    assert result.outcome == "INCUMBENT_UPDATED"
    assert result.selected_run_id == winner.run_id
    assert result.candidates[1].status == "DOMINATED"
    assert result.candidates[1].dominated_by == [winner.run_id]
