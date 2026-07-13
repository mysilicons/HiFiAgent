"""Rule-backed evaluator and explicit decision-to-state mapping."""

from __future__ import annotations

from hifi_agent.agent.models import AgentState
from hifi_agent.rules.context import RuleContext
from hifi_agent.rules.engine import RuleEngine
from hifi_agent.rules.models import RuleDecision

LOW_QUALITY_ACTIONS = frozenset({"STOP_LOW_COVERAGE_SEARCH"})
INSUFFICIENT_METADATA_ACTIONS = frozenset(
    {"STOP_INSUFFICIENT_CORE_METRICS", "STOP_INSUFFICIENT_EVIDENCE"}
)
TOOL_FAILURE_ACTIONS = frozenset({"STOP_EVALUATION_INCOMPLETE"})


class Evaluator:
    """Evaluate normalized evidence using the Stage 8 deterministic rules."""

    def __init__(self, rule_engine: RuleEngine) -> None:
        self.rule_engine = rule_engine

    def evaluate(self, context: RuleContext) -> RuleDecision:
        """Return a rule decision without invoking an LLM."""
        return self.rule_engine.evaluate(context)

    def target_state(self, decision: RuleDecision) -> AgentState:
        """Map a Stage 8 decision to one legal Agent state."""
        if decision.decision == "BASELINE":
            return AgentState.ACCEPTED
        if decision.decision == "RETRY":
            return AgentState.PLAN_RETRY
        if decision.action in LOW_QUALITY_ACTIONS:
            return AgentState.STOP_LOW_QUALITY
        if decision.action in INSUFFICIENT_METADATA_ACTIONS:
            return AgentState.STOP_INSUFFICIENT_METADATA
        if decision.action in TOOL_FAILURE_ACTIONS:
            return AgentState.FAILED_TOOL_EXECUTION
        return AgentState.STOP_UNCERTAIN
