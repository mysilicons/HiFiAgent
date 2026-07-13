import json
from collections import Counter
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hifi_agent.rules.context import RuleContext, load_rule_context
from hifi_agent.rules.engine import RuleEngine, load_default_rule_engine, write_rule_decision
from hifi_agent.rules.models import (
    WHITELISTED_PARAMETERS,
    ExpertRule,
    RuleSet,
)
from hifi_agent.schemas.metrics import AssemblyMetrics


def context_with(**overrides: object) -> RuleContext:
    values: dict[str, object] = {
        "input_type": "pacbio_hifi",
        "ploidy": 2,
        "inbred": False,
        "expected_genome_size": 100_000_000,
        "estimated_genome_size": 100_000_000,
        "estimated_coverage": 30.0,
        "kmer_source": "same_data_advisory",
        "kmer_peak_depth": 30.0,
        "genomescope_model_status": "success",
        "kmer_warning_count": 0,
        "hifiasm_hom_cov": 30.0,
        "assembly_size": 100_000_000,
        "assembly_size_ratio": 1.0,
        "contig_n50": 500_000,
        "quast_mode": "reference_based",
        "quast_misassemblies": 0,
        "busco_complete": 98.0,
        "busco_duplicated": 2.0,
        "kmer_completeness": 95.0,
        "mapped_read_fraction": 0.99,
        "coverage_cv": 0.25,
        "tool_failure_count": 0,
    }
    values.update(overrides)
    return RuleContext.model_validate(values)


POSITIVE_CASES: list[tuple[str, dict[str, object]]] = [
    ("INPUT_NOT_HIFI_STOP", {"input_type": "ont"}),
    ("INPUT_NOT_HIFI_STOP", {"input_type": "pacbio_clr"}),
    ("PLOIDY_OUTSIDE_DIPLOID_STOP", {"ploidy": 1}),
    ("PLOIDY_OUTSIDE_DIPLOID_STOP", {"ploidy": 4}),
    (
        "EVALUATION_TOOL_FAILURE_STOP",
        {"tool_failure_count": 1},
    ),
    (
        "EVALUATION_TOOL_FAILURE_STOP",
        {"tool_failure_count": 3},
    ),
    ("COVERAGE_INSUFFICIENT_STOP", {"estimated_coverage": 14.9}),
    ("COVERAGE_INSUFFICIENT_STOP", {"estimated_coverage": 0.0}),
    (
        "MULTI_METRIC_CONFLICT_STOP",
        {"assembly_size_ratio": 1.0, "busco_duplicated": 11.0},
    ),
    (
        "MULTI_METRIC_CONFLICT_STOP",
        {"assembly_size_ratio": 0.79, "busco_duplicated": 6.0},
    ),
    ("CORE_METRICS_MISSING_STOP", {"busco_complete": None}),
    ("CORE_METRICS_MISSING_STOP", {"mapped_read_fraction": None}),
    (
        "ASM_SIZE_TOO_LARGE_AND_DUPLICATED",
        {"assembly_size_ratio": 1.26, "busco_duplicated": 10.1},
    ),
    (
        "ASM_SIZE_TOO_LARGE_AND_DUPLICATED",
        {"assembly_size_ratio": 1.6, "busco_duplicated": 20.0},
    ),
    (
        "ASM_SIZE_LARGE_DUPLICATION_LOW_REVIEW",
        {"assembly_size_ratio": 1.26, "busco_duplicated": 5.0},
    ),
    (
        "ASM_SIZE_LARGE_DUPLICATION_LOW_REVIEW",
        {"assembly_size_ratio": 1.6, "busco_duplicated": 0.0},
    ),
    (
        "HIGH_N50_STRUCTURAL_ERROR_DISABLE_JOIN",
        {"contig_n50": 1_000_000, "quast_misassemblies": 11},
    ),
    (
        "HIGH_N50_STRUCTURAL_ERROR_DISABLE_JOIN",
        {
            "assembly_size": 200_000_000,
            "contig_n50": 2_000_000,
            "quast_misassemblies": 21,
        },
    ),
    ("HOM_COV_TRUSTED_KMER_CONFLICT", {"hifiasm_hom_cov": 46.0}),
    ("HOM_COV_TRUSTED_KMER_CONFLICT", {"hifiasm_hom_cov": 19.0}),
    ("COVERAGE_WARNING_KEEP_BASELINE", {"estimated_coverage": 15.0}),
    ("COVERAGE_WARNING_KEEP_BASELINE", {"estimated_coverage": 19.999}),
    (
        "GENOME_SIZE_UNKNOWN_KEEP_BASELINE",
        {"expected_genome_size": None, "estimated_genome_size": None},
    ),
    (
        "GENOME_SIZE_UNKNOWN_KEEP_BASELINE",
        {
            "expected_genome_size": None,
            "estimated_genome_size": None,
            "estimated_coverage": None,
        },
    ),
    ("INBRED_ALLOW_DISABLE_PURGE", {"inbred": True}),
    ("INBRED_ALLOW_DISABLE_PURGE", {"inbred": True, "estimated_coverage": 40.0}),
    ("METRICS_NORMAL_ACCEPT_BASELINE", {}),
    (
        "METRICS_NORMAL_ACCEPT_BASELINE",
        {
            "assembly_size_ratio": 0.85,
            "busco_complete": 95.0,
            "busco_duplicated": 5.0,
            "kmer_completeness": 90.0,
            "mapped_read_fraction": 0.95,
        },
    ),
]

NEGATIVE_CASES: list[tuple[str, dict[str, object]]] = [
    ("INPUT_NOT_HIFI_STOP", {}),
    ("INPUT_NOT_HIFI_STOP", {"ploidy": 1}),
    ("PLOIDY_OUTSIDE_DIPLOID_STOP", {"ploidy": 2}),
    ("PLOIDY_OUTSIDE_DIPLOID_STOP", {"ploidy": None}),
    ("EVALUATION_TOOL_FAILURE_STOP", {"tool_failure_count": 0}),
    ("EVALUATION_TOOL_FAILURE_STOP", {"tool_failure_count": 0, "busco_complete": None}),
    ("COVERAGE_INSUFFICIENT_STOP", {"estimated_coverage": 15.0}),
    ("COVERAGE_INSUFFICIENT_STOP", {"estimated_coverage": 30.0}),
    (
        "MULTI_METRIC_CONFLICT_STOP",
        {"assembly_size_ratio": 1.3, "busco_duplicated": 11.0},
    ),
    (
        "MULTI_METRIC_CONFLICT_STOP",
        {"assembly_size_ratio": 0.79, "busco_duplicated": 5.0},
    ),
    ("CORE_METRICS_MISSING_STOP", {}),
    ("CORE_METRICS_MISSING_STOP", {"kmer_completeness": None}),
    (
        "ASM_SIZE_TOO_LARGE_AND_DUPLICATED",
        {"assembly_size_ratio": 1.25, "busco_duplicated": 11.0},
    ),
    (
        "ASM_SIZE_TOO_LARGE_AND_DUPLICATED",
        {"assembly_size_ratio": 1.3, "busco_duplicated": 10.0},
    ),
    (
        "ASM_SIZE_LARGE_DUPLICATION_LOW_REVIEW",
        {"assembly_size_ratio": 1.25, "busco_duplicated": 0.0},
    ),
    (
        "ASM_SIZE_LARGE_DUPLICATION_LOW_REVIEW",
        {"assembly_size_ratio": 1.3, "busco_duplicated": 5.1},
    ),
    (
        "HIGH_N50_STRUCTURAL_ERROR_DISABLE_JOIN",
        {"contig_n50": 999_999, "quast_misassemblies": 20},
    ),
    (
        "HIGH_N50_STRUCTURAL_ERROR_DISABLE_JOIN",
        {"contig_n50": 1_000_000, "quast_misassemblies": 10},
    ),
    ("HOM_COV_TRUSTED_KMER_CONFLICT", {"hifiasm_hom_cov": 45.0}),
    (
        "HOM_COV_TRUSTED_KMER_CONFLICT",
        {"hifiasm_hom_cov": 60.0, "kmer_source": "independent_high_confidence"},
    ),
    ("COVERAGE_WARNING_KEEP_BASELINE", {"estimated_coverage": 14.999}),
    ("COVERAGE_WARNING_KEEP_BASELINE", {"estimated_coverage": 20.0}),
    ("GENOME_SIZE_UNKNOWN_KEEP_BASELINE", {}),
    (
        "GENOME_SIZE_UNKNOWN_KEEP_BASELINE",
        {"expected_genome_size": None, "estimated_genome_size": 100_000_000},
    ),
    ("INBRED_ALLOW_DISABLE_PURGE", {"inbred": False}),
    ("INBRED_ALLOW_DISABLE_PURGE", {"inbred": None}),
    ("METRICS_NORMAL_ACCEPT_BASELINE", {"assembly_size_ratio": 0.849}),
    ("METRICS_NORMAL_ACCEPT_BASELINE", {"busco_complete": 94.9}),
]


@pytest.fixture(scope="module")
def engine() -> RuleEngine:
    return load_default_rule_engine()


@pytest.mark.parametrize(
    ("rule_id", "overrides"),
    POSITIVE_CASES,
    ids=[
        f"{rule_id}-positive-{index % 2 + 1}" for index, (rule_id, _) in enumerate(POSITIVE_CASES)
    ],
)
def test_each_rule_has_positive_cases(
    engine: RuleEngine,
    rule_id: str,
    overrides: dict[str, object],
) -> None:
    assert engine.rule_matches(rule_id, context_with(**overrides))


@pytest.mark.parametrize(
    ("rule_id", "overrides"),
    NEGATIVE_CASES,
    ids=[
        f"{rule_id}-negative-{index % 2 + 1}" for index, (rule_id, _) in enumerate(NEGATIVE_CASES)
    ],
)
def test_each_rule_has_negative_cases(
    engine: RuleEngine,
    rule_id: str,
    overrides: dict[str, object],
) -> None:
    assert not engine.rule_matches(rule_id, context_with(**overrides))


def test_rule_inventory_has_at_least_ten_rules_and_reason_codes(engine: RuleEngine) -> None:
    assert len(engine.rule_set.rules) >= 10
    assert all(rule.reason_codes for rule in engine.rule_set.rules)


def test_every_rule_has_two_positive_and_two_negative_cases(engine: RuleEngine) -> None:
    expected_ids = {rule.rule_id for rule in engine.rule_set.rules}
    positive_counts = Counter(rule_id for rule_id, _overrides in POSITIVE_CASES)
    negative_counts = Counter(rule_id for rule_id, _overrides in NEGATIVE_CASES)

    assert set(positive_counts) == expected_ids
    assert set(negative_counts) == expected_ids
    assert all(count >= 2 for count in positive_counts.values())
    assert all(count >= 2 for count in negative_counts.values())


def test_thresholds_have_versions_sources_and_distinct_levels(engine: RuleEngine) -> None:
    catalog = engine.thresholds
    assert {entry.level for entry in catalog.thresholds.values()} == {
        "warning",
        "action",
        "acceptance",
    }
    for entry in catalog.thresholds.values():
        assert entry.source_id in catalog.sources
        assert entry.source_version == catalog.sources[entry.source_id].version
        assert entry.description


def test_normal_low_coverage_and_retry_decisions_need_no_llm(engine: RuleEngine) -> None:
    baseline = engine.evaluate(context_with())
    stopped = engine.evaluate(context_with(estimated_coverage=10.0))
    retried = engine.evaluate(context_with(assembly_size_ratio=1.4, busco_duplicated=15.0))

    assert (baseline.decision, baseline.action) == ("BASELINE", "ACCEPT_DEFAULT_PARAMETERS")
    assert (stopped.decision, stopped.action) == ("STOP", "STOP_LOW_COVERAGE_SEARCH")
    assert (retried.decision, retried.action) == ("RETRY", "PROPOSE_STRONGER_PURGE")
    assert retried.candidates[0].parameters.purge_similarity == 0.5


def test_dynamic_and_discrete_candidates_are_validated(engine: RuleEngine) -> None:
    hom_cov = engine.evaluate(context_with(hifiasm_hom_cov=60.0))
    inbred = engine.evaluate(context_with(inbred=True))
    structural = engine.evaluate(context_with(contig_n50=1_000_000, quast_misassemblies=11))

    assert hom_cov.candidates[0].parameters.hom_cov == 30
    assert inbred.candidates[0].parameters.purge_level == 0
    assert structural.candidates[0].parameters.disable_post_join is True


def test_all_emitted_candidate_parameters_are_whitelisted(engine: RuleEngine) -> None:
    contexts = [
        context_with(assembly_size_ratio=1.4, busco_duplicated=15.0),
        context_with(hifiasm_hom_cov=60.0),
        context_with(inbred=True),
        context_with(contig_n50=1_000_000, quast_misassemblies=11),
    ]
    for context in contexts:
        decision = engine.evaluate(context)
        for candidate in decision.candidates:
            assert set(candidate.parameters.model_dump(exclude_none=True)) <= WHITELISTED_PARAMETERS


def test_non_whitelisted_candidate_is_rejected(engine: RuleEngine) -> None:
    rule_data = engine.rule_set.rules[6].model_dump(mode="json")
    rule_data["candidates"][0]["parameters"]["kmer_length"] = {"value": 51}

    with pytest.raises(ValidationError, match="non-whitelisted"):
        ExpertRule.model_validate(rule_data)


def test_same_priority_conflict_stops_and_emits_no_candidate(engine: RuleEngine) -> None:
    baseline_rule = next(
        rule for rule in engine.rule_set.rules if rule.rule_id == "METRICS_NORMAL_ACCEPT_BASELINE"
    )
    conflicting_rule = baseline_rule.model_copy(
        update={
            "rule_id": "SYNTHETIC_CONFLICT_STOP",
            "decision": "STOP",
            "action": "REQUIRE_HUMAN_REVIEW",
            "reason_codes": ["SYNTHETIC_CONFLICT"],
            "risk_level": "high",
        }
    )
    rule_set = RuleSet(
        rule_set_version="test",
        threshold_catalog_version=engine.thresholds.catalog_version,
        rules=[baseline_rule, conflicting_rule],
    )

    decision = RuleEngine(rule_set, engine.thresholds).evaluate(context_with())

    assert decision.decision == "STOP"
    assert decision.candidates == []
    assert "RULE_DECISION_CONFLICT" in decision.conflicts


def test_decision_is_deterministic_and_json_is_byte_stable(
    engine: RuleEngine,
    tmp_path: Path,
) -> None:
    context = context_with(assembly_size_ratio=1.4, busco_duplicated=15.0)
    first = engine.evaluate(context)
    second = engine.evaluate(context)
    first_path = write_rule_decision(first, tmp_path / "first.json")
    second_path = write_rule_decision(second, tmp_path / "second.json")

    assert first == second
    assert first.decision_id == second.decision_id
    assert first_path.read_bytes() == second_path.read_bytes()


def test_unmatched_metrics_stop_with_insufficient_evidence(engine: RuleEngine) -> None:
    decision = engine.evaluate(
        context_with(
            assembly_size_ratio=1.2,
            busco_complete=94.0,
            busco_duplicated=6.0,
            kmer_completeness=85.0,
            mapped_read_fraction=0.94,
        )
    )

    assert decision.decision == "STOP"
    assert decision.action == "STOP_INSUFFICIENT_EVIDENCE"
    assert decision.reason_codes == ["NO_EXPERT_RULE_MATCHED"]


def test_rule_context_loads_all_stage_artifacts(tmp_path: Path) -> None:
    (tmp_path / "00_metadata").mkdir()
    (tmp_path / "01_pre_qc").mkdir()
    (tmp_path / "02_assembly" / "baseline" / "metadata").mkdir(parents=True)
    (tmp_path / "03_post_qc" / "baseline").mkdir(parents=True)
    (tmp_path / "03_post_qc" / "baseline" / "quast").mkdir()
    config = {
        "sample_id": "sample",
        "hifi_reads": ["/tmp/reads.fastq"],
        "outdir": str(tmp_path),
        "expected_genome_size": 100_000_000,
        "ploidy": 2,
        "inbred": False,
    }
    (tmp_path / "00_metadata" / "resolved_config.yaml").write_text(yaml.safe_dump(config))
    (tmp_path / "01_pre_qc" / "raw_metrics.json").write_text(
        json.dumps(
            {
                "estimated_genome_size": 100_000_000,
                "estimated_coverage": 30.0,
                "kmer_source": "independent_high_confidence",
                "kmer_peak_depth": 30,
                "genomescope_model_status": "success",
                "warnings": [],
            }
        )
    )
    (tmp_path / "02_assembly" / "baseline" / "metadata" / "assembly_manifest.json").write_text(
        json.dumps({"homozygous_coverage_threshold": 30})
    )
    metrics = AssemblyMetrics(
        run_id="baseline",
        assembly_size=100_000_000,
        assembly_size_ratio=1.0,
        contig_n50=500_000,
        quast_misassemblies=0,
        busco_complete=98.0,
        busco_duplicated=2.0,
        kmer_completeness=95.0,
        mapped_read_fraction=0.99,
    )
    (tmp_path / "03_post_qc" / "baseline" / "assembly_metrics.json").write_text(
        metrics.model_dump_json()
    )
    (tmp_path / "03_post_qc" / "baseline" / "quast" / "quast_metrics.json").write_text(
        json.dumps({"mode": "reference_based"})
    )

    context = load_rule_context(tmp_path)

    assert context.estimated_coverage == 30.0
    assert context.hifiasm_hom_cov == 30.0
    assert context.tool_failure_count == 0
