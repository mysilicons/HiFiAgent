"""Bounded candidate comparison and optimization APIs."""

from hifi_agent.optimization.comparator import CandidateComparator
from hifi_agent.optimization.evidence import (
    load_baseline_comparable,
    load_stage7_comparable,
)
from hifi_agent.optimization.loop import OptimizationLoop
from hifi_agent.optimization.loop_models import (
    LoopBudget,
    LoopDecisionContext,
    LoopDirective,
    OptimizationLoopState,
)
from hifi_agent.optimization.models import (
    CandidateAssessment,
    OptimizationResult,
    Stage11SyntheticScenario,
)
from hifi_agent.optimization.round_models import (
    ComparableRun,
    RoundComparison,
    RoundComparisonContext,
)
from hifi_agent.optimization.rounds import RoundComparator
from hifi_agent.optimization.runner import run_stage11_optimization
from hifi_agent.optimization.synthetic import (
    DEFAULT_STAGE11_SCENARIO,
    synthesize_candida_stage11_scenario,
)

__all__ = [
    "DEFAULT_STAGE11_SCENARIO",
    "CandidateAssessment",
    "CandidateComparator",
    "ComparableRun",
    "LoopBudget",
    "LoopDecisionContext",
    "LoopDirective",
    "OptimizationLoop",
    "OptimizationLoopState",
    "OptimizationResult",
    "RoundComparator",
    "RoundComparison",
    "RoundComparisonContext",
    "Stage11SyntheticScenario",
    "load_baseline_comparable",
    "load_stage7_comparable",
    "run_stage11_optimization",
    "synthesize_candida_stage11_scenario",
]
