"""Incumbent-aware current decision and candidate services."""

from hifi_agent.decision.client import (
    DeepSeekClient,
    LLMClientResult,
    RecordedLLMClient,
    RecordedLLMTranscript,
    StructuredLLMClient,
)
from hifi_agent.decision.context import DecisionContextStore, build_decision_context
from hifi_agent.decision.models import (
    ApprovedProposal,
    AuthorizedEvidence,
    DecisionContext,
    LLMProposalEnvelope,
    ProposalDecision,
    ProposalDirective,
    RawProposal,
    RejectedProposal,
    RetrievalTrace,
)
from hifi_agent.decision.retrieval import GovernedRetriever, LocalGovernedRetriever
from hifi_agent.decision.rules import build_rule_directive
from hifi_agent.decision.service import ProposalProvider, ProposalService

__all__ = [
    "ApprovedProposal",
    "AuthorizedEvidence",
    "DecisionContext",
    "DecisionContextStore",
    "DeepSeekClient",
    "GovernedRetriever",
    "LLMClientResult",
    "LLMProposalEnvelope",
    "LocalGovernedRetriever",
    "ProposalDecision",
    "ProposalDirective",
    "ProposalProvider",
    "ProposalService",
    "RawProposal",
    "RecordedLLMClient",
    "RecordedLLMTranscript",
    "RejectedProposal",
    "RetrievalTrace",
    "StructuredLLMClient",
    "build_decision_context",
    "build_rule_directive",
]
