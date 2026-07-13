"""Optional, constrained retrieval and explanation support."""

from hifi_agent.rag.client import DeepSeekClient
from hifi_agent.rag.explainer import explain_run
from hifi_agent.rag.indexer import (
    DEFAULT_INDEX_PATH,
    DEFAULT_SOURCE_CATALOG,
    build_knowledge_index,
    load_knowledge_index,
)
from hifi_agent.rag.models import ExplanationBundle, LLMExplanation, RetrievalHit
from hifi_agent.rag.retriever import LocalRetriever

__all__ = [
    "DEFAULT_INDEX_PATH",
    "DEFAULT_SOURCE_CATALOG",
    "DeepSeekClient",
    "ExplanationBundle",
    "LLMExplanation",
    "LocalRetriever",
    "RetrievalHit",
    "build_knowledge_index",
    "explain_run",
    "load_knowledge_index",
]
