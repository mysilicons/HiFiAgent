"""Expert-reviewed Stage 13 scenario registry."""

from __future__ import annotations

from hifi_agent.benchmarking.models import BenchmarkScenario
from hifi_agent.rules.context import RuleContext


def _context(**overrides: object) -> RuleContext:
    values: dict[str, object] = {
        "input_type": "pacbio_hifi",
        "ploidy": 2,
        "inbred": False,
        "expected_genome_size": 100_000_000,
        "estimated_genome_size": 100_000_000,
        "estimated_coverage": 30.0,
        "kmer_source": "independent_high_confidence",
        "kmer_peak_depth": 30.0,
        "genomescope_model_status": "success",
        "kmer_warning_count": 0,
        "kmer_peak_authorizes_hom_cov": True,
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


def stage13_scenarios() -> list[BenchmarkScenario]:
    """Return all deterministic boundary scenarios required by Stage 13."""
    return [
        BenchmarkScenario(
            scenario_id="normal_hifi_metrics",
            title="Normal diploid HiFi assembly",
            data_kind="synthetic_fixture",
            category="success",
            context=_context(),
            expected_decision="BASELINE",
            expected_action="ACCEPT_DEFAULT_PARAMETERS",
            expected_rule_id="METRICS_NORMAL_ACCEPT_BASELINE",
            construction="Audited central values inside every normal-acceptance boundary.",
        ),
        BenchmarkScenario(
            scenario_id="low_coverage_downsample",
            title="Low-coverage downsample equivalent",
            data_kind="real_derived_perturbation",
            category="input_quality",
            context=_context(estimated_coverage=10.0),
            expected_decision="STOP",
            expected_action="STOP_LOW_COVERAGE_SEARCH",
            expected_rule_id="COVERAGE_INSUFFICIENT_STOP",
            construction=(
                "Coverage is deterministically changed from 30x to 10x, equivalent to retaining "
                "one third of reads while preserving all unrelated metrics."
            ),
            limitation="Metric-level perturbation; it does not claim a new biological assembly.",
        ),
        BenchmarkScenario(
            scenario_id="oversized_duplicated_assembly",
            title="Oversized assembly with duplicated BUSCOs",
            data_kind="real_derived_perturbation",
            category="redundancy",
            context=_context(
                assembly_size=140_000_000,
                assembly_size_ratio=1.4,
                busco_duplicated=15.0,
            ),
            expected_decision="RETRY",
            expected_action="PROPOSE_STRONGER_PURGE",
            expected_parameters=[{"purge_similarity": 0.5}],
            expected_rule_id="ASM_SIZE_TOO_LARGE_AND_DUPLICATED",
            construction="Joint size-ratio and BUSCO-duplication boundary perturbation.",
        ),
        BenchmarkScenario(
            scenario_id="hom_cov_peak_conflict",
            title="hifiasm hom-cov conflicts with trusted k-mer peak",
            data_kind="real_derived_perturbation",
            category="coverage_model",
            context=_context(hifiasm_hom_cov=60.0),
            expected_decision="RETRY",
            expected_action="PROPOSE_HOM_COV",
            expected_parameters=[{"hom_cov": 30}],
            expected_rule_id="HOM_COV_TRUSTED_KMER_CONFLICT",
            construction=(
                "hifiasm threshold doubled while an independently derived trusted k-mer peak "
                "is held fixed."
            ),
        ),
        BenchmarkScenario(
            scenario_id="inbred_sample",
            title="Explicitly inbred sample",
            data_kind="synthetic_fixture",
            category="sample_metadata",
            context=_context(inbred=True),
            expected_decision="RETRY",
            expected_action="PROPOSE_DISABLE_PURGE",
            expected_parameters=[{"purge_level": 0}],
            expected_rule_id="INBRED_ALLOW_DISABLE_PURGE",
            construction="Only the explicit user-provided inbred flag is changed.",
            limitation="The rule permits a bounded candidate; it does not force acceptance of -l0.",
        ),
        BenchmarkScenario(
            scenario_id="high_n50_structural_error",
            title="High N50 with structural-error conflict",
            data_kind="real_derived_perturbation",
            category="metric_conflict",
            context=_context(contig_n50=1_500_000, quast_misassemblies=15),
            expected_decision="RETRY",
            expected_action="PROPOSE_DISABLE_POST_JOIN",
            expected_parameters=[{"disable_post_join": True}],
            expected_rule_id="HIGH_N50_STRUCTURAL_ERROR_DISABLE_JOIN",
            construction=(
                "N50 is improved while reference-supported misassemblies cross action level."
            ),
            limitation="Only one conservative, reversible candidate is allowed.",
        ),
        BenchmarkScenario(
            scenario_id="evaluation_tool_failure",
            title="Post-QC tool failure",
            data_kind="synthetic_fixture",
            category="engineering_failure",
            context=_context(tool_failure_count=1),
            expected_decision="STOP",
            expected_action="STOP_EVALUATION_INCOMPLETE",
            expected_rule_id="EVALUATION_TOOL_FAILURE_STOP",
            construction=(
                "A failed evaluation tool is injected without changing biological metrics."
            ),
        ),
        BenchmarkScenario(
            scenario_id="multi_metric_conflict",
            title="Size and duplication evidence conflict",
            data_kind="real_derived_perturbation",
            category="metric_conflict",
            context=_context(
                assembly_size=70_000_000,
                assembly_size_ratio=0.7,
                busco_duplicated=8.0,
            ),
            expected_decision="STOP",
            expected_action="REQUIRE_HUMAN_REVIEW",
            expected_rule_id="MULTI_METRIC_CONFLICT_STOP",
            construction=(
                "Assembly-size loss and BUSCO duplication are deliberately made contradictory."
            ),
        ),
        BenchmarkScenario(
            scenario_id="insufficient_evidence",
            title="No expert rule has sufficient evidence",
            data_kind="synthetic_fixture",
            category="safety_fallback",
            context=_context(
                assembly_size_ratio=1.2,
                busco_complete=94.0,
                busco_duplicated=6.0,
                kmer_completeness=85.0,
                mapped_read_fraction=0.94,
            ),
            expected_decision="STOP",
            expected_action="STOP_INSUFFICIENT_EVIDENCE",
            construction="Values are intentionally placed between audited rule regions.",
        ),
    ]
