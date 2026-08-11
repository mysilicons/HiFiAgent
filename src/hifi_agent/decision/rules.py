"""Deterministic production rule directives for the unified proposal service."""

from __future__ import annotations

from typing import cast

from hifi_agent.decision.models import (
    DecisionContext,
    MetricEffect,
    ProposalDirective,
    RawProposal,
)


def build_rule_directive(context: DecisionContext) -> ProposalDirective:
    """Propose bounded single-variable changes only when trusted evidence shows a defect."""
    metric_id = _select_problem_metric(context)
    if metric_id is None:
        minimum_candidate_runs = context.sample_facts.get("minimum_candidate_runs")
        if minimum_candidate_runs == 1 and context.round_index == 1:
            return _controlled_candidate_directive(context)
        return ProposalDirective(
            directive_id=f"round_{context.round_index:02d}.rule-stop",
            action="STOP",
            reason_codes=("RULES_FOUND_NO_ACTIONABLE_TRUSTED_DEFECT",),
        )
    direction = context.qc_feature_bundle.features[metric_id].direction
    expected = cast(
        MetricEffect,
        {
            "higher": "increase",
            "lower": "decrease",
            "target_one": "toward_one",
            "fact": "diagnostic",
        }[direction],
    )
    parameters = context.incumbent_config.parameters
    proposals: list[RawProposal] = []
    next_purge_level = parameters.purge_level - 1 if parameters.purge_level > 0 else 1
    proposals.append(
        _proposal(
            context,
            suffix="purge-level",
            changes={"purge_level": next_purge_level},
            metric_id=metric_id,
            expected=expected,
            source_id="hifiasm_faq",
            rationale="Apply one conservative purge-level change to the current incumbent.",
        )
    )
    next_similarity = round(
        parameters.purge_similarity - 0.05
        if parameters.purge_similarity >= 0.05
        else parameters.purge_similarity + 0.05,
        6,
    )
    proposals.append(
        _proposal(
            context,
            suffix="purge-similarity",
            changes={"purge_similarity": next_similarity},
            metric_id=metric_id,
            expected=expected,
            source_id="hifiasm_parameters",
            rationale="Apply one conservative purge-similarity change to the current incumbent.",
        )
    )
    return ProposalDirective(
        directive_id=f"round_{context.round_index:02d}.rule-propose",
        action="PROPOSE",
        reason_codes=("RULES_IDENTIFIED_ACTIONABLE_TRUSTED_DEFECT", metric_id.upper()),
        proposals=tuple(proposals),
    )


def _controlled_candidate_directive(context: DecisionContext) -> ProposalDirective:
    """Register one conservative comparison when an explicit evidence run requires it."""
    metric_id = next(
        (
            candidate
            for candidate in ("contig_n50", *context.applicable_metric_ids)
            if candidate in context.applicable_metric_ids
            and candidate in context.qc_feature_bundle.features
        ),
        None,
    )
    if metric_id is None:
        return ProposalDirective(
            directive_id=f"round_{context.round_index:02d}.controlled-stop",
            action="STOP",
            reason_codes=("CONTROLLED_CANDIDATE_HAS_NO_APPLICABLE_METRIC",),
        )
    direction = context.qc_feature_bundle.features[metric_id].direction
    expected = cast(
        MetricEffect,
        {
            "higher": "increase",
            "lower": "decrease",
            "target_one": "toward_one",
            "fact": "diagnostic",
        }[direction],
    )
    current = context.incumbent_config.parameters.purge_similarity
    value = round(current - 0.05 if current >= 0.05 else current + 0.05, 6)
    proposal = _proposal(
        context,
        suffix="controlled-purge-similarity",
        changes={"purge_similarity": value},
        metric_id=metric_id,
        expected=expected,
        source_id="hifiasm_parameters",
        rationale=(
            "Run one preregistered conservative single-parameter comparison required by the "
            "configured evidence policy."
        ),
    )
    return ProposalDirective(
        directive_id=f"round_{context.round_index:02d}.controlled-propose",
        action="PROPOSE",
        reason_codes=("MINIMUM_CANDIDATE_EVIDENCE_REQUIRED",),
        proposals=(proposal,),
    )


def _select_problem_metric(context: DecisionContext) -> str | None:
    values = context.incumbent_metrics
    actionable = set(context.applicable_metric_ids)
    if (
        "busco_duplicated" in actionable
        and values.busco_duplicated is not None
        and values.busco_duplicated > 2.0
    ):
        return "busco_duplicated"
    if (
        "assembly_size_ratio" in actionable
        and values.assembly_size_ratio is not None
        and abs(values.assembly_size_ratio - 1.0) >= 0.05
    ):
        return "assembly_size_ratio"
    if (
        "coverage_cv" in actionable
        and values.coverage_cv is not None
        and values.coverage_cv >= 0.35
    ):
        return "coverage_cv"
    if (
        "kmer_completeness" in actionable
        and values.kmer_completeness is not None
        and values.kmer_completeness < 90.0
    ):
        return "kmer_completeness"
    if (
        "busco_complete" in actionable
        and values.busco_complete is not None
        and values.busco_complete < 95.0
    ):
        return "busco_complete"
    return None


def _proposal(
    context: DecisionContext,
    *,
    suffix: str,
    changes: dict[str, bool | int | float | str | None],
    metric_id: str,
    expected: MetricEffect,
    source_id: str,
    rationale: str,
) -> RawProposal:
    return RawProposal(
        proposal_id=f"round_{context.round_index:02d}.{suffix}",
        origin="rule",
        changes=changes,
        source_ids=(source_id,),
        metric_ids=(metric_id,),
        expected_metric_effects={metric_id: expected},
        rationale=rationale,
        risk_level="low",
    )
