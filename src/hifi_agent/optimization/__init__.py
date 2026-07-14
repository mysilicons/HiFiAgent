"""Bounded Stage 11 candidate optimization and comparison."""

from hifi_agent.optimization.comparator import CandidateComparator
from hifi_agent.optimization.models import (
    CandidateAssessment,
    OptimizationResult,
    Stage11SyntheticScenario,
)
from hifi_agent.optimization.runner import run_stage11_optimization
from hifi_agent.optimization.synthetic import (
    DEFAULT_STAGE11_SCENARIO,
    synthesize_candida_stage11_scenario,
)

__all__ = [
    "DEFAULT_STAGE11_SCENARIO",
    "CandidateAssessment",
    "CandidateComparator",
    "OptimizationResult",
    "Stage11SyntheticScenario",
    "run_stage11_optimization",
    "synthesize_candida_stage11_scenario",
]
