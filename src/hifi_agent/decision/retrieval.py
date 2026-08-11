"""Governed local retrieval for parameter authorization evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Protocol, cast

from hifi_agent.decision.models import (
    AuthorizedEvidence,
    DecisionContext,
    ProposalDirective,
    RetrievalTrace,
)
from hifi_agent.exceptions import RuleEvaluationError
from hifi_agent.orchestration.runtime_models import sha256_file
from hifi_agent.schemas.assembly import ParameterName

_INJECTION = re.compile(
    r"ignore\s+(?:all\s+)?previous|system\s+prompt|developer\s+message|"
    r"reveal\s+(?:the\s+)?(?:secret|token)|execute\s+(?:this\s+)?command",
    re.IGNORECASE,
)


class GovernedRetriever(Protocol):
    """Typed retrieval port used by the proposal service."""

    def retrieve(
        self,
        context: DecisionContext,
        directive: ProposalDirective,
    ) -> RetrievalTrace:
        """Return only allowlisted, current, compatible evidence chunks."""


class LocalGovernedRetriever:
    """Load the frozen index and filter evidence before it reaches an LLM."""

    def __init__(
        self,
        index_path: Path,
        *,
        actual_hifiasm_version: str,
        source_allowlist: set[str] | None = None,
        today: date | None = None,
    ) -> None:
        self.index_path = index_path.resolve()
        self.actual_hifiasm_version = actual_hifiasm_version
        self.source_allowlist = source_allowlist
        self.today = today or date.today()

    def retrieve(
        self,
        context: DecisionContext,
        directive: ProposalDirective,
    ) -> RetrievalTrace:
        """Return deterministic matching chunks with complete filtering lineage."""
        try:
            payload = json.loads(self.index_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise RuleEvaluationError(f"RAG index is unreadable: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_id") != "hifi-agent":
            raise RuleEvaluationError("RAG index has an unsupported schema identifier")
        sources_raw = payload.get("sources")
        chunks_raw = payload.get("chunks")
        if not isinstance(sources_raw, list) or not isinstance(chunks_raw, list):
            raise RuleEvaluationError("RAG index lacks sources or chunks")
        index_hash = sha256_file(self.index_path)
        sources: dict[str, dict[str, object]] = {}
        for indexed in sources_raw:
            if isinstance(indexed, dict) and isinstance(indexed.get("source"), dict):
                source = cast(dict[str, object], indexed["source"])
                source_id = source.get("source_id")
                if isinstance(source_id, str):
                    sources[source_id] = {**source, "stale": bool(indexed.get("stale"))}
        requested = {
            parameter
            for proposal in directive.proposals
            for parameter in proposal.changes
            if parameter
            in {
                "purge_level",
                "purge_similarity",
                "hom_cov",
                "disable_post_join",
            }
        }
        query = " ".join(
            [
                *directive.reason_codes,
                *sorted(requested),
                *(metric for proposal in directive.proposals for metric in proposal.metric_ids),
            ]
        )
        eligible_evidence: list[AuthorizedEvidence] = []
        filters: dict[str, tuple[str, ...]] = {}
        for raw in chunks_raw:
            if not isinstance(raw, dict):
                continue
            chunk_id = raw.get("chunk_id")
            source_id = raw.get("source_id")
            text = raw.get("text")
            if (
                not isinstance(chunk_id, str)
                or not isinstance(source_id, str)
                or not isinstance(text, str)
            ):
                continue
            source_details = sources.get(source_id)
            reasons = _source_rejections(
                source_details,
                source_id=source_id,
                requested=requested,
                allowlist=self.source_allowlist,
                actual_version=self.actual_hifiasm_version,
                today=self.today,
            )
            if bool(raw.get("quarantined")) or _INJECTION.search(text):
                reasons.append("PROMPT_INJECTION_QUARANTINED")
            authorized_raw = raw.get("authorized_parameter_tags")
            authorized = (
                {value for value in authorized_raw if isinstance(value, str) and value in requested}
                if isinstance(authorized_raw, list)
                else set()
            )
            if not authorized:
                reasons.append("NO_REQUESTED_PARAMETER_AUTHORIZATION")
            if reasons:
                filters[chunk_id] = tuple(sorted(set(reasons)))
                continue
            assert source_details is not None
            review_after = source_details.get("review_after")
            version = source_details.get("tool_version")
            target_version = (
                str(version) if str(source_details.get("tool", "")).lower() == "hifiasm" else None
            )
            eligible_evidence.append(
                AuthorizedEvidence(
                    source_id=source_id,
                    chunk_id=chunk_id,
                    chunk_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    index_sha256=index_hash,
                    authorized_parameters=tuple(
                        cast(ParameterName, item) for item in sorted(authorized)
                    ),
                    source_version=str(version),
                    target_hifiasm_version=target_version,
                    review_after=date.fromisoformat(str(review_after)),
                    text=text,
                )
            )
        return RetrievalTrace(
            query=query,
            index_sha256=index_hash,
            evidence=tuple(_diverse_evidence(eligible_evidence, limit=8)),
            filter_reason_codes=filters,
        )


def _diverse_evidence(
    evidence: list[AuthorizedEvidence],
    *,
    limit: int,
) -> list[AuthorizedEvidence]:
    """Round-robin eligible sources so a leading source cannot crowd out another authority."""
    grouped: dict[str, list[AuthorizedEvidence]] = {}
    for item in evidence:
        grouped.setdefault(item.source_id, []).append(item)
    selected: list[AuthorizedEvidence] = []
    offset = 0
    while len(selected) < limit:
        added = False
        for group in grouped.values():
            if offset < len(group):
                selected.append(group[offset])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        offset += 1
    return selected


def _source_rejections(
    source: dict[str, object] | None,
    *,
    source_id: str,
    requested: set[str],
    allowlist: set[str] | None,
    actual_version: str,
    today: date,
) -> list[str]:
    if source is None:
        return ["UNKNOWN_SOURCE"]
    reasons: list[str] = []
    if allowlist is not None and source_id not in allowlist:
        reasons.append("SOURCE_NOT_ALLOWLISTED")
    if source.get("scope") != "production":
        reasons.append("SOURCE_OUTSIDE_SCOPE")
    if bool(source.get("stale")):
        reasons.append("SOURCE_MARKED_STALE")
    authorization = source.get("authorization_scope")
    if not isinstance(authorization, list) or "parameter_guidance" not in authorization:
        reasons.append("SOURCE_NOT_PARAMETER_AUTHORITY")
    tags = source.get("parameter_tags")
    if not isinstance(tags, list) or not requested.intersection(
        item for item in tags if isinstance(item, str)
    ):
        reasons.append("SOURCE_PARAMETER_SCOPE_MISMATCH")
    try:
        if date.fromisoformat(str(source.get("review_after"))) < today:
            reasons.append("SOURCE_REVIEW_EXPIRED")
    except ValueError:
        reasons.append("SOURCE_REVIEW_DATE_INVALID")
    if str(source.get("tool", "")).lower() == "hifiasm" and not _version_evidence_matches(
        str(source.get("tool_version")), actual_version
    ):
        reasons.append("HIFIASM_VERSION_MISMATCH")
    return reasons


def _version_evidence_matches(expected: str, observed: str) -> bool:
    """Accept an exact version or a tool banner containing that complete version token."""
    if expected == observed:
        return True
    return (
        re.search(
            rf"(?<![A-Za-z0-9.]){re.escape(expected)}(?![A-Za-z0-9.])",
            observed,
        )
        is not None
    )
