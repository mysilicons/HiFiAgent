"""Optional, constrained retrieval and explanation support."""

from hifi_agent.rag.client import DeepSeekClient
from hifi_agent.rag.explainer import explain_run
from hifi_agent.rag.indexer import (
    DEFAULT_INDEX_PATH,
    DEFAULT_SOURCE_CATALOG,
    build_knowledge_index,
    load_knowledge_index,
)
from hifi_agent.rag.models import (
    ApprovedCandidate,
    ExplanationBundle,
    LLMExplanation,
    LLMProposalBundle,
    ProposalDecisionBundle,
    RetrievalHit,
)
from hifi_agent.rag.proposer import propose_run
from hifi_agent.rag.retriever import LocalRetriever, authorized_parameters

__all__ = [
    "DEFAULT_INDEX_PATH",
    "DEFAULT_SOURCE_CATALOG",
    "ApprovedCandidate",
    "DeepSeekClient",
    "ExplanationBundle",
    "LLMExplanation",
    "LLMProposalBundle",
    "LocalRetriever",
    "ProposalDecisionBundle",
    "RetrievalHit",
    "authorized_parameters",
    "build_knowledge_index",
    "explain_run",
    "load_knowledge_index",
    "propose_run",
]
