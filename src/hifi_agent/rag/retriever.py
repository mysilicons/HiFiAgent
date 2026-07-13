"""Deterministic BM25 retrieval over the local Stage 10 index."""

from __future__ import annotations

import math
import re
from collections import Counter

from hifi_agent.rag.models import KnowledgeIndex, RetrievalHit
from hifi_agent.rules.models import RuleDecision

TOKEN_PATTERN = re.compile(r"--?[a-z][a-z0-9-]*|[a-z0-9]+", re.I)
QUERY_EXPANSIONS = {
    "ASSEMBLY_SIZE_EXCESSIVE": "assembly size much larger than estimated genome size",
    "BUSCO_DUPLICATION_HIGH": "BUSCO duplicated genes haplotig duplication",
    "BUSCO_DUPLICATION_NOT_HIGH": "BUSCO duplicated low assembly size discrepancy",
    "GENOME_SIZE_MAY_BE_INACCURATE": "genome size estimate uncertainty",
    "HIFIASM_HOM_COV_CONFLICT": "hifiasm homozygous read coverage threshold k-mer peak",
    "TRUSTED_COMPARABLE_HIFI_KMER_PEAK": "homozygous coverage k-mer plot",
    "REFERENCE_SUPPORTED_STRUCTURAL_ERRORS": "QUAST reference misassemblies structural errors",
    "POST_JOIN_RISK": "hifiasm post join misassembly",
    "SAMPLE_DECLARED_INBRED": "inbred homozygous genome disable purge",
    "PURGE_UNDERCORRECTION_SUSPECTED": "purge duplication haplotigs similarity threshold",
    "KMER_COMPLETENESS_ACCEPTABLE": "Merqury k-mer completeness quality value",
    "COVERAGE_BELOW_ACTION_THRESHOLD": "insufficient read coverage assembly",
}


class LocalRetriever:
    """Rank V1-scoped chunks using deterministic BM25 and tag boosts."""

    def __init__(self, index: KnowledgeIndex) -> None:
        self.index = index
        self._source_by_id = {indexed.source.source_id: indexed.source for indexed in index.sources}
        self._chunks = [
            chunk for chunk in index.chunks if self._source_by_id[chunk.source_id].scope == "v1"
        ]
        self._tokens = [_tokenize(f"{chunk.section} {chunk.text}") for chunk in self._chunks]
        self._document_frequency = Counter(
            token for tokens in self._tokens for token in set(tokens)
        )
        self._average_length = (
            sum(len(tokens) for tokens in self._tokens) / len(self._tokens) if self._tokens else 1.0
        )

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
        parameter_tags: set[str] | None = None,
        problem_tags: set[str] | None = None,
    ) -> list[RetrievalHit]:
        """Return top positive-scoring chunks with complete source provenance."""
        if top_k < 1:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens or not self._chunks:
            return []
        requested_parameters = parameter_tags or set()
        requested_problems = problem_tags or set()
        scored: list[tuple[float, int]] = []
        for index, (chunk, tokens) in enumerate(zip(self._chunks, self._tokens, strict=True)):
            score = self._bm25(query_tokens, tokens)
            score += 1.5 * len(requested_parameters.intersection(chunk.parameter_tags))
            score += 0.75 * len(requested_problems.intersection(chunk.problem_tags))
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], self._chunks[item[1]].chunk_id))
        hits: list[RetrievalHit] = []
        for score, index in scored[:top_k]:
            chunk = self._chunks[index]
            source = self._source_by_id[chunk.source_id]
            hits.append(
                RetrievalHit(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    source_title=source.title,
                    source_url=source.url,
                    tool=source.tool,
                    tool_version=source.tool_version,
                    section=chunk.section,
                    text=chunk.text,
                    score=round(score, 8),
                    parameter_tags=chunk.parameter_tags,
                    problem_tags=chunk.problem_tags,
                )
            )
        return hits

    def _bm25(self, query_tokens: list[str], document_tokens: list[str]) -> float:
        frequencies = Counter(document_tokens)
        document_count = len(self._chunks)
        document_length = len(document_tokens)
        score = 0.0
        for token in set(query_tokens):
            frequency = frequencies[token]
            if frequency == 0:
                continue
            document_frequency = self._document_frequency[token]
            inverse_document_frequency = math.log(
                1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * document_length / self._average_length
            )
            score += inverse_document_frequency * frequency * 2.5 / denominator
        return score


def build_decision_query(decision: RuleDecision) -> tuple[str, set[str], set[str]]:
    """Convert deterministic rule facts into a retrieval query and tag filters."""
    parts = [decision.decision, decision.action.replace("_", " ")]
    problem_tags: set[str] = set()
    for reason_code in decision.reason_codes:
        parts.append(reason_code.replace("_", " "))
        expansion = QUERY_EXPANSIONS.get(reason_code)
        if expansion:
            parts.append(expansion)
        _infer_problem_tags(reason_code, problem_tags)
    parts.extend(key.replace("_", " ") for key in decision.evidence)
    parameter_tags: set[str] = set()
    for candidate in decision.candidates:
        parameters = candidate.parameters.model_dump(exclude_none=True)
        parameter_tags.update(parameters)
        parts.extend(parameter.replace("_", " ") for parameter in parameters)
    if {"purge_level", "purge_similarity"}.intersection(parameter_tags):
        problem_tags.add("duplication")
    if "hom_cov" in parameter_tags:
        problem_tags.add("coverage")
    if "disable_post_join" in parameter_tags:
        problem_tags.add("structural_error")
    return " ".join(parts), parameter_tags, problem_tags


def _infer_problem_tags(reason_code: str, tags: set[str]) -> None:
    if "SIZE" in reason_code or "GENOME" in reason_code:
        tags.add("assembly_size")
    if "DUPLIC" in reason_code or "PURGE" in reason_code:
        tags.add("duplication")
    if "COVERAGE" in reason_code or "HOM_COV" in reason_code:
        tags.add("coverage")
    if "STRUCTURAL" in reason_code or "POST_JOIN" in reason_code:
        tags.add("structural_error")
    if "KMER" in reason_code:
        tags.add("kmer_quality")
    if "BUSCO_COMPLETE" in reason_code:
        tags.add("completeness")


def _tokenize(text: str) -> list[str]:
    normalized = text.lower().replace("_", " ")
    tokens = TOKEN_PATTERN.findall(normalized)
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        if token.startswith("--"):
            expanded.extend(token[2:].split("-"))
        elif token.startswith("-"):
            expanded.append(token[1:])
    return expanded
