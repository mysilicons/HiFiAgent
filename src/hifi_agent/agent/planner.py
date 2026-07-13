"""Deterministic baseline and bounded candidate planning."""

from __future__ import annotations

from hifi_agent.agent.models import (
    AssemblyConfig,
    AssemblyParameters,
    PreQcMetrics,
)
from hifi_agent.rules.models import RuleDecision
from hifi_agent.schemas.sample import SampleConfig


class Planner:
    """Build validated hifiasm configurations without free-form commands."""

    def plan_baseline(self, config: SampleConfig, metrics: PreQcMetrics) -> AssemblyConfig:
        """Return the fixed V1 baseline configuration."""
        return AssemblyConfig(
            run_id="baseline",
            input_reads=config.hifi_reads,
            threads=config.resources.max_threads,
            parameters=AssemblyParameters(),
            reason_codes=["BASELINE_DEFAULT"],
            source_metrics=["pre_qc.estimated_coverage"],
            risk_level="low",
        )

    def propose_candidates(
        self,
        decision: RuleDecision,
        baseline: AssemblyConfig,
        *,
        optimization_round: int,
        max_candidates: int,
        seen_fingerprints: set[str],
    ) -> list[AssemblyConfig]:
        """Apply Stage 8 whitelisted deltas and remove duplicate parameter sets."""
        if decision.decision != "RETRY":
            return []
        candidates: list[AssemblyConfig] = []
        local_fingerprints: set[str] = set()
        for index, proposed in enumerate(decision.candidates, start=1):
            merged = baseline.parameters.model_dump()
            merged.update(proposed.parameters.model_dump(exclude_none=True))
            candidate = AssemblyConfig(
                run_id=f"candidate_r{optimization_round:02d}_c{index:02d}",
                input_reads=baseline.input_reads,
                threads=baseline.threads,
                parameters=AssemblyParameters.model_validate(merged),
                reason_codes=decision.reason_codes,
                source_metrics=sorted(decision.evidence),
                risk_level=proposed.risk_level,
                requires_user_confirmation=proposed.risk_level in {"medium_high", "high"},
                retry_kind="PARAMETER_OPTIMIZATION",
                optimization_round=optimization_round,
            )
            fingerprint = candidate.parameter_fingerprint()
            if fingerprint in seen_fingerprints or fingerprint in local_fingerprints:
                continue
            local_fingerprints.add(fingerprint)
            candidates.append(candidate)
            if len(candidates) == max_candidates:
                break
        return candidates
