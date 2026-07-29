import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from hifi_agent.exceptions import RuleConfigurationError
from hifi_agent.rag.indexer import build_knowledge_index, load_source_catalog
from hifi_agent.rag.models import (
    IndexedSource,
    KnowledgeChunk,
    KnowledgeIndex,
    KnowledgeIndexManifest,
    KnowledgeSource,
    RetrievalTrace,
)
from hifi_agent.rag.retriever import LocalRetriever
from hifi_agent.rules.models import WHITELISTED_PARAMETERS


def _source(
    source_id: str,
    *,
    version: str = "0.25.0-r726",
    sha256: str = "0" * 64,
    review_after: date = date(2027, 1, 1),
) -> KnowledgeSource:
    return KnowledgeSource(
        source_id=source_id,
        title=source_id,
        file_path=Path(f"document/{source_id}.md"),
        url=f"https://example.test/{source_id}",
        version_url=f"https://example.test/{source_id}/{version}",
        content_kind="official_documentation",
        tool="hifiasm",
        tool_version=version,
        scope="v1",
        evidence_level="official",
        authorization_scope=["parameter_guidance"],
        expected_sha256=sha256,
        review_after=review_after,
        parameter_tags=["purge_similarity"],
        problem_tags=["duplication"],
        input_tags=["pacbio_hifi"],
    )


def _catalog(tmp_path: Path, text: str, *, review_after: str = "2027-01-01") -> Path:
    document = tmp_path / "document/source.md"
    document.parent.mkdir(parents=True)
    document.write_text(text)
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    catalog: dict[str, Any] = {
        "schema_version": "2.0",
        "catalog_version": "test-v2",
        "retrieved_at": "2026-07-13",
        "target_hifiasm_version": "0.25.0-r726",
        "required_parameters": [],
        "sources": [
            {
                **_source(
                    "source", sha256=digest, review_after=date.fromisoformat(review_after)
                ).model_dump(mode="json"),
                "file_path": "document/source.md",
            }
        ],
    }
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(catalog, sort_keys=False))
    return path


def test_default_catalog_has_official_evidence_for_every_whitelisted_parameter() -> None:
    catalog = load_source_catalog()

    assert catalog.schema_version == "2.0"
    assert set(catalog.required_parameters) == WHITELISTED_PARAMETERS
    for parameter in WHITELISTED_PARAMETERS:
        evidence = [
            source
            for source in catalog.sources
            if parameter in source.parameter_tags
            and source.evidence_level == "official"
            and "parameter_guidance" in source.authorization_scope
        ]
        assert evidence, parameter
        assert all(source.tool == "hifiasm" for source in evidence)
        assert all(source.version_url for source in evidence)


def test_default_index_build_verifies_hashes_and_writes_manifest(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    manifest_path = tmp_path / "index_manifest.json"

    index = build_knowledge_index(
        output_path=index_path,
        manifest_path=manifest_path,
        built_at=datetime(2026, 7, 15, tzinfo=UTC),
        as_of=date(2026, 7, 15),
    )
    manifest = KnowledgeIndexManifest.model_validate_json(manifest_path.read_text())

    assert all(source.checksum_verified for source in index.sources)
    assert index.warnings == []
    assert set(manifest.parameter_evidence) == WHITELISTED_PARAMETERS
    assert all(manifest.parameter_evidence.values())
    assert manifest.quarantined_chunk_count == 0


def test_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    catalog_path = _catalog(tmp_path, "# Guide\n\nOfficial purge similarity guidance for HiFi.")
    data = yaml.safe_load(catalog_path.read_text())
    data["sources"][0]["expected_sha256"] = "f" * 64
    catalog_path.write_text(yaml.safe_dump(data))

    with pytest.raises(RuleConfigurationError, match="SHA-256 mismatch"):
        build_knowledge_index(
            catalog_path=catalog_path,
            output_path=tmp_path / "index.json",
            project_root=tmp_path,
        )


def test_stale_source_warns_and_loses_parameter_authority(tmp_path: Path) -> None:
    catalog_path = _catalog(
        tmp_path,
        "# Purging\n\nReview haplotig similarity threshold using -s for duplicate sequence.",
        review_after="2026-01-01",
    )

    index = build_knowledge_index(
        catalog_path=catalog_path,
        output_path=tmp_path / "index.json",
        project_root=tmp_path,
        as_of=date(2026, 7, 15),
    )

    assert index.sources[0].stale is True
    assert index.warnings == ["STALE_SOURCE:source:2026-01-01"]
    assert all(not chunk.authorized_parameter_tags for chunk in index.chunks)


def test_version_mismatch_is_ranked_lower_and_warned() -> None:
    exact = _source("exact", version="0.25.0-r726")
    old = _source("old", version="0.24.0-r700")
    chunks = [
        KnowledgeChunk(
            chunk_id=f"{source_id}_aaaaaaaaaaaa",
            source_id=source_id,
            section="Purge similarity",
            text="Official haplotig purge similarity threshold guidance for duplicate sequence.",
            ordinal=1,
            parameter_tags=["purge_similarity"],
            problem_tags=["duplication"],
            input_tags=["pacbio_hifi"],
            authorized_parameter_tags=["purge_similarity"],
        )
        for source_id in ("exact", "old")
    ]
    index = KnowledgeIndex(
        catalog_version="test",
        catalog_sha256="f" * 64,
        target_hifiasm_version="0.25.0-r726",
        built_at=datetime(2026, 7, 15, tzinfo=UTC),
        sources=[
            IndexedSource(source=exact, sha256="0" * 64, byte_size=10, chunk_count=1, stale=False),
            IndexedSource(source=old, sha256="1" * 64, byte_size=10, chunk_count=1, stale=False),
        ],
        chunks=chunks,
    )

    hits = LocalRetriever(index).retrieve(
        "purge similarity duplicate haplotig",
        top_k=2,
        parameter_tags={"purge_similarity"},
    )

    assert [hit.source_id for hit in hits] == ["exact", "old"]
    assert hits[0].version_match == "exact"
    assert hits[1].version_match == "mismatch"
    assert hits[1].score < hits[0].score
    assert hits[1].warnings == ["HIFIASM_VERSION_MISMATCH:old:0.24.0-r700!=0.25.0-r726"]


def test_prompt_injection_chunk_is_quarantined_and_never_retrieved(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/rag/prompt_injection.md").read_text()
    catalog_path = _catalog(
        tmp_path,
        fixture,
    )

    index = build_knowledge_index(
        catalog_path=catalog_path,
        output_path=tmp_path / "index.json",
        project_root=tmp_path,
    )
    manifest = KnowledgeIndexManifest.model_validate_json(
        (tmp_path / "index_manifest.json").read_text()
    )

    assert index.chunks[0].quarantined is True
    assert index.chunks[0].security_warnings
    assert manifest.quarantined_chunk_count == 1
    assert LocalRetriever(index).retrieve("ignore system shell", top_k=5) == []


def test_index_rejects_chunks_from_unregistered_sources() -> None:
    source = _source("registered")
    data = {
        "schema_version": "2.0",
        "catalog_version": "test",
        "catalog_sha256": "f" * 64,
        "target_hifiasm_version": "0.25.0-r726",
        "parser_version": "2.0",
        "built_at": "2026-07-15T00:00:00Z",
        "sources": [
            IndexedSource(
                source=source,
                sha256="0" * 64,
                byte_size=10,
                chunk_count=1,
                stale=False,
            ).model_dump(mode="json")
        ],
        "chunks": [
            KnowledgeChunk(
                chunk_id="unknown_aaaaaaaaaaaa",
                source_id="unknown",
                section="Unknown",
                text="Unregistered evidence must never enter retrieval results.",
                ordinal=1,
            ).model_dump(mode="json")
        ],
    }

    with pytest.raises(ValidationError, match="unregistered source IDs"):
        KnowledgeIndex.model_validate(data)


def test_retrieval_trace_is_catalog_bounded_and_records_version_warning() -> None:
    source = _source("old", version="0.24.0-r700")
    index = KnowledgeIndex(
        catalog_version="test",
        catalog_sha256="f" * 64,
        target_hifiasm_version="0.25.0-r726",
        built_at=datetime(2026, 7, 15, tzinfo=UTC),
        sources=[
            IndexedSource(source=source, sha256="0" * 64, byte_size=10, chunk_count=1, stale=False)
        ],
        chunks=[
            KnowledgeChunk(
                chunk_id="old_aaaaaaaaaaaa",
                source_id="old",
                section="Purge",
                text="Official purge similarity evidence for duplicate haplotigs.",
                ordinal=1,
                parameter_tags=["purge_similarity"],
                authorized_parameter_tags=["purge_similarity"],
            )
        ],
    )
    retriever = LocalRetriever(index)
    hits = retriever.retrieve("purge similarity", parameter_tags={"purge_similarity"})

    trace = retriever.trace("purge similarity", hits, parameter_tags={"purge_similarity"})
    round_trip = RetrievalTrace.model_validate_json(trace.model_dump_json())

    assert set(round_trip.result_source_ids) <= set(round_trip.catalog_source_ids)
    assert round_trip.result_source_ids == ["old"]
    assert round_trip.warnings == ["HIFIASM_VERSION_MISMATCH:old:0.24.0-r700!=0.25.0-r726"]


def test_machine_readable_catalog_contains_no_unregistered_ids() -> None:
    catalog = load_source_catalog()
    payload = json.loads(catalog.model_dump_json())

    assert len({source["source_id"] for source in payload["sources"]}) == len(payload["sources"])
