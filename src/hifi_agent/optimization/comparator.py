"""Conservative multi-metric comparison for Stage 11 candidates."""

from __future__ import annotations

from dataclasses import dataclass

from hifi_agent.agent.models import AssemblyConfig
from hifi_agent.optimization.models import (
    CandidateAssessment,
    CandidateStatus,
    MetricAssessment,
    MetricDifference,
    MetricDirection,
    ParameterDifference,
)
from hifi_agent.schemas.metrics import AssemblyMetrics


@dataclass(frozen=True)
class MetricSpec:
    """Direction and material-change threshold for one comparison metric."""

    direction: MetricDirection
    material_delta: float
    note: str


METRIC_SPECS: dict[str, MetricSpec] = {
    "assembly_size_ratio": MetricSpec(
        "target_one", 0.05, "Closer to 1 is preferred only when genome size is trusted."
    ),
    "busco_complete": MetricSpec("higher", 1.0, "Gene-space completeness; not whole-genome proof."),
    "busco_duplicated": MetricSpec(
        "contextual_lower", 1.0, "Lower is useful only with size/ploidy agreement."
    ),
    "kmer_completeness": MetricSpec(
        "higher", 1.0, "Higher read-supported k-mer completeness is preferred."
    ),
    "kmer_qv": MetricSpec("higher", 1.0, "Higher consensus k-mer QV is preferred."),
    "mapped_read_fraction": MetricSpec(
        "higher", 0.01, "Higher read support is preferred but is not sufficient alone."
    ),
    "coverage_cv": MetricSpec("lower", 0.10, "Lower coverage anomaly is preferred."),
    "contig_n50": MetricSpec(
        "higher", 0.10, "Higher N50 is secondary and cannot override correctness regressions."
    ),
    "quast_misassemblies": MetricSpec(
        "lower", 0.10, "Lower reference-supported structural error is preferred when available."
    ),
}

CORE_AUTO_SELECTION_METRICS = frozenset(
    {
        "assembly_size_ratio",
        "busco_complete",
        "busco_duplicated",
        "kmer_completeness",
        "kmer_qv",
        "mapped_read_fraction",
        "coverage_cv",
        "contig_n50",
    }
)


class CandidateComparator:
    """Apply direction, dominance, and hard-regression safeguards."""

    def compare(
        self,
        baseline_config: AssemblyConfig,
        baseline: AssemblyMetrics,
        candidate_config: AssemblyConfig,
        candidate: AssemblyMetrics,
        *,
        metrics_source: str,
        synthetic: bool = False,
    ) -> CandidateAssessment:
        """Return a complete safety assessment for one candidate."""
        parameter_differences = _parameter_differences(baseline_config, candidate_config)
        differences = [
            _metric_difference(metric, spec, baseline, candidate)
            for metric, spec in METRIC_SPECS.items()
        ]
        improvements = [item.metric for item in differences if item.assessment == "IMPROVED"]
        regressions = [item.metric for item in differences if item.assessment == "REGRESSED"]
        material_improvements = [
            item.metric for item in differences if item.assessment == "IMPROVED" and item.material
        ]
        material_regressions = [
            item.metric for item in differences if item.assessment == "REGRESSED" and item.material
        ]
        hard_regressions = _hard_regressions(baseline, candidate)
        acceptance_failures = _acceptance_failures(candidate)
        missing = [
            metric
            for metric in CORE_AUTO_SELECTION_METRICS
            if getattr(baseline, metric) is None or getattr(candidate, metric) is None
        ]
        dominated = not improvements and bool(regressions)
        conflicts: list[str] = []
        if material_improvements and material_regressions:
            conflicts.append("MATERIAL_METRIC_DIRECTIONS_CONFLICT")
        if "contig_n50" in improvements and hard_regressions:
            conflicts.append("N50_GAIN_CANNOT_OVERRIDE_CORE_QUALITY_REGRESSION")
        if missing:
            conflicts.append("CORE_COMPARISON_METRICS_MISSING")

        if dominated:
            status: CandidateStatus = "DOMINATED"
            dominated_by = [baseline.run_id]
        elif hard_regressions or conflicts:
            status = "REJECTED_REGRESSION"
            dominated_by = []
        elif acceptance_failures or not material_improvements:
            status = "REJECTED_NO_GAIN"
            dominated_by = []
        else:
            status = "ACCEPTED"
            dominated_by = []

        tradeoffs = _tradeoffs(
            differences,
            hard_regressions,
            acceptance_failures,
            missing,
        )
        return CandidateAssessment(
            run_id=candidate.run_id,
            status=status,
            config=candidate_config,
            metrics=candidate,
            metrics_source=metrics_source,
            parameter_differences=parameter_differences,
            metric_differences=differences,
            dominated_by=dominated_by,
            improvements=improvements,
            regressions=regressions,
            hard_regressions=hard_regressions,
            acceptance_failures=acceptance_failures,
            conflicts=conflicts,
            tradeoffs=tradeoffs,
            synthetic=synthetic,
        )


def dominates(first: CandidateAssessment, second: CandidateAssessment) -> bool:
    """Return whether first is no worse in every available metric and better in one."""
    first_by_metric = {item.metric: item for item in first.metric_differences}
    second_by_metric = {item.metric: item for item in second.metric_differences}
    no_worse = True
    strictly_better = False
    for metric in METRIC_SPECS:
        left = first_by_metric[metric]
        right = second_by_metric[metric]
        if left.candidate_value is None or right.candidate_value is None:
            continue
        relation = _compare_values(
            left.candidate_value,
            right.candidate_value,
            METRIC_SPECS[metric].direction,
        )
        if relation < 0:
            no_worse = False
            break
        if relation > 0:
            strictly_better = True
    return no_worse and strictly_better


def _parameter_differences(
    baseline: AssemblyConfig,
    candidate: AssemblyConfig,
) -> list[ParameterDifference]:
    baseline_values = baseline.parameters.model_dump()
    candidate_values = candidate.parameters.model_dump()
    return [
        ParameterDifference(
            parameter=parameter,
            baseline_value=baseline_values[parameter],
            candidate_value=value,
        )
        for parameter, value in candidate_values.items()
        if baseline_values[parameter] != value
    ]


def _metric_difference(
    metric: str,
    spec: MetricSpec,
    baseline: AssemblyMetrics,
    candidate: AssemblyMetrics,
) -> MetricDifference:
    baseline_value = getattr(baseline, metric)
    candidate_value = getattr(candidate, metric)
    if baseline_value is None or candidate_value is None:
        return MetricDifference(
            metric=metric,
            direction=spec.direction,
            baseline_value=baseline_value,
            candidate_value=candidate_value,
            delta=None,
            assessment="UNAVAILABLE",
            note=spec.note,
        )
    delta = candidate_value - baseline_value
    relation = _compare_values(candidate_value, baseline_value, spec.direction)
    assessment: MetricAssessment = (
        "IMPROVED" if relation > 0 else "REGRESSED" if relation < 0 else "UNCHANGED"
    )
    material = _is_material(metric, float(baseline_value), float(candidate_value), spec)
    return MetricDifference(
        metric=metric,
        direction=spec.direction,
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        delta=delta,
        assessment=assessment,
        material=material,
        note=spec.note,
    )


def _compare_values(candidate: float, baseline: float, direction: MetricDirection) -> int:
    if direction == "target_one":
        candidate_distance = abs(candidate - 1.0)
        baseline_distance = abs(baseline - 1.0)
        return (baseline_distance > candidate_distance) - (baseline_distance < candidate_distance)
    if direction in {"higher"}:
        return (candidate > baseline) - (candidate < baseline)
    return (candidate < baseline) - (candidate > baseline)


def _is_material(metric: str, baseline: float, candidate: float, spec: MetricSpec) -> bool:
    if metric in {"contig_n50", "quast_misassemblies"}:
        denominator = max(abs(baseline), 1.0)
        return abs(candidate - baseline) / denominator >= spec.material_delta
    if metric == "assembly_size_ratio":
        return abs(abs(candidate - 1.0) - abs(baseline - 1.0)) >= spec.material_delta
    return abs(candidate - baseline) >= spec.material_delta


def _hard_regressions(
    baseline: AssemblyMetrics,
    candidate: AssemblyMetrics,
) -> list[str]:
    regressions: list[str] = []
    checks = (
        ("BUSCO_COMPLETE_DROP_GT_2PP", baseline.busco_complete, candidate.busco_complete, 2.0),
        (
            "KMER_COMPLETENESS_DROP_GT_2PP",
            baseline.kmer_completeness,
            candidate.kmer_completeness,
            2.0,
        ),
        ("KMER_QV_DROP_GT_2", baseline.kmer_qv, candidate.kmer_qv, 2.0),
        (
            "MAPPED_READ_FRACTION_DROP_GT_0_02",
            baseline.mapped_read_fraction,
            candidate.mapped_read_fraction,
            0.02,
        ),
    )
    for code, baseline_value, candidate_value, threshold in checks:
        if (
            baseline_value is not None
            and candidate_value is not None
            and baseline_value - candidate_value > threshold
        ):
            regressions.append(code)
    if (
        baseline.coverage_cv is not None
        and candidate.coverage_cv is not None
        and candidate.coverage_cv - baseline.coverage_cv > 0.25
    ):
        regressions.append("COVERAGE_CV_INCREASE_GT_0_25")
    if (
        baseline.quast_misassemblies is not None
        and candidate.quast_misassemblies is not None
        and candidate.quast_misassemblies - baseline.quast_misassemblies >= 5
        and candidate.quast_misassemblies > baseline.quast_misassemblies * 1.20
    ):
        regressions.append("MISASSEMBLIES_INCREASE_GT_20_PERCENT")
    if candidate.tool_failures:
        regressions.append("CANDIDATE_POST_QC_TOOL_FAILURE")
    return regressions


def _acceptance_failures(candidate: AssemblyMetrics) -> list[str]:
    failures: list[str] = []
    ratio = candidate.assembly_size_ratio
    if ratio is not None and not 0.85 <= ratio <= 1.15:
        failures.append("ASSEMBLY_SIZE_RATIO_OUTSIDE_0_85_TO_1_15")
    thresholds = (
        ("BUSCO_COMPLETE_BELOW_95", candidate.busco_complete, 95.0),
        ("KMER_COMPLETENESS_BELOW_90", candidate.kmer_completeness, 90.0),
        ("MAPPED_READ_FRACTION_BELOW_0_95", candidate.mapped_read_fraction, 0.95),
    )
    for code, value, threshold in thresholds:
        if value is not None and value < threshold:
            failures.append(code)
    return failures


def _tradeoffs(
    differences: list[MetricDifference],
    hard_regressions: list[str],
    acceptance_failures: list[str],
    missing: list[str],
) -> list[str]:
    tradeoffs = [
        f"{item.metric}: {item.assessment} ({item.baseline_value} -> {item.candidate_value})"
        for item in differences
        if item.assessment not in {"UNCHANGED", "UNAVAILABLE"}
    ]
    tradeoffs.extend(f"hard regression: {code}" for code in hard_regressions)
    tradeoffs.extend(f"acceptance failure: {code}" for code in acceptance_failures)
    if missing:
        tradeoffs.append(f"missing core metrics: {', '.join(sorted(missing))}")
    return tradeoffs
