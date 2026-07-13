"""Build a provenance-preserving local full-text index from document/."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import yaml
from pydantic import ValidationError
from pypdf import PdfReader

from hifi_agent.exceptions import RuleConfigurationError
from hifi_agent.rag.models import (
    IndexedSource,
    KnowledgeChunk,
    KnowledgeIndex,
    KnowledgeSource,
    KnowledgeSourceCatalog,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_CATALOG = PROJECT_ROOT / "configs" / "knowledge_sources.yaml"
DEFAULT_INDEX_PATH = PROJECT_ROOT / "knowledge" / "index.json"
MAX_CHUNK_CHARS = 1800
CHUNK_OVERLAP_CHARS = 180

PARAMETER_PATTERNS = {
    "purge_level": re.compile(r"(?:purge level|purging|purge duplication|(?<!\w)-l\d?)", re.I),
    "purge_similarity": re.compile(r"(?:similarity threshold|haplotig|(?<!\w)-s\d?)", re.I),
    "hom_cov": re.compile(r"(?:--hom-cov|homozygous (?:read )?coverage)", re.I),
    "disable_post_join": re.compile(r"(?:post[- ]join|(?<!\w)-u\d?)", re.I),
}
PROBLEM_PATTERNS = {
    "assembly_size": re.compile(r"assembly size|genome size|too large|too small", re.I),
    "duplication": re.compile(r"duplicat|haplotig|redundan", re.I),
    "coverage": re.compile(r"coverage|depth|k-mer peak|kmer peak", re.I),
    "structural_error": re.compile(r"misassembl|structural error|breakpoint", re.I),
    "completeness": re.compile(r"complete|missing|BUSCO", re.I),
    "kmer_quality": re.compile(r"Merqury|quality value|\bQV\b|k-mer", re.I),
    "contiguity": re.compile(r"\bN50\b|contig|fragment", re.I),
    "ploidy": re.compile(r"ploid|haplotype|diploid|polyploid", re.I),
}


@dataclass(frozen=True)
class Section:
    """Intermediate titled text section extracted from one document."""

    title: str
    text: str


class _SectionHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sections: list[Section] = []
        self._heading = "Document"
        self._heading_parts: list[str] = []
        self._text_parts: list[str] = []
        self._heading_depth = 0
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Start headings, text blocks, or excluded markup regions."""
        del attrs
        if tag in {"script", "style", "svg"}:
            self._skip_depth += 1
        if tag in {"h1", "h2", "h3", "h4"} and self._skip_depth == 0:
            self._flush()
            self._heading_depth += 1
        if tag in {"p", "li", "br", "tr"} and self._skip_depth == 0:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """Finish headings and excluded markup regions."""
        if tag in {"h1", "h2", "h3", "h4"} and self._heading_depth:
            title = _normalize_text(" ".join(self._heading_parts))
            if title:
                self._heading = title
            self._heading_parts = []
            self._heading_depth -= 1
        if tag in {"script", "style", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        """Collect visible heading or section text."""
        if self._skip_depth:
            return
        if self._heading_depth:
            self._heading_parts.append(data)
        else:
            self._text_parts.append(data)

    def close(self) -> None:
        """Finish parsing and flush the final visible section."""
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = _normalize_text(" ".join(self._text_parts))
        if len(text) >= 20:
            self.sections.append(Section(self._heading, text))
        self._text_parts = []


def load_source_catalog(path: Path = DEFAULT_SOURCE_CATALOG) -> KnowledgeSourceCatalog:
    """Load and validate the versioned knowledge source catalog."""
    try:
        data = yaml.safe_load(path.read_text())
        catalog = KnowledgeSourceCatalog.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RuleConfigurationError(f"Knowledge source catalog is invalid: {path}: {exc}") from exc
    source_ids = [source.source_id for source in catalog.sources]
    if len(source_ids) != len(set(source_ids)):
        raise RuleConfigurationError("Knowledge source IDs must be unique")
    return catalog


def build_knowledge_index(
    *,
    catalog_path: Path = DEFAULT_SOURCE_CATALOG,
    output_path: Path = DEFAULT_INDEX_PATH,
    project_root: Path = PROJECT_ROOT,
    built_at: datetime | None = None,
) -> KnowledgeIndex:
    """Parse every allowlisted source, create stable chunks, and write the local index."""
    catalog = load_source_catalog(catalog_path)
    indexed_sources: list[IndexedSource] = []
    chunks: list[KnowledgeChunk] = []
    for source in catalog.sources:
        path = (
            source.file_path if source.file_path.is_absolute() else project_root / source.file_path
        )
        if not path.is_file():
            raise RuleConfigurationError(
                f"Knowledge source `{source.source_id}` is missing: {path}"
            )
        sections = _extract_sections(path)
        source_chunks = _chunk_sections(source, sections)
        if not source_chunks:
            raise RuleConfigurationError(
                f"Knowledge source `{source.source_id}` produced no usable chunks"
            )
        chunks.extend(source_chunks)
        indexed_sources.append(
            IndexedSource(
                source=source,
                sha256=_sha256(path),
                byte_size=path.stat().st_size,
                chunk_count=len(source_chunks),
            )
        )
    index = KnowledgeIndex(
        catalog_version=catalog.catalog_version,
        built_at=built_at or datetime.now(UTC),
        sources=indexed_sources,
        chunks=chunks,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(index.model_dump_json(indent=2) + "\n")
    return index


def load_knowledge_index(path: Path = DEFAULT_INDEX_PATH) -> KnowledgeIndex:
    """Load a previously built local knowledge index."""
    if not path.is_file():
        raise RuleConfigurationError(
            f"Knowledge index does not exist: {path}; run `hifi-agent rag-index`"
        )
    try:
        return KnowledgeIndex.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        raise RuleConfigurationError(f"Knowledge index is invalid: {path}: {exc}") from exc


def _extract_sections(path: Path) -> list[Section]:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return _markdown_sections(path)
    if suffix in {".html", ".htm"}:
        parser = _SectionHTMLParser()
        parser.feed(path.read_text(errors="replace"))
        parser.close()
        return parser.sections
    if suffix == ".pdf":
        reader = PdfReader(path)
        sections = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = _normalize_text(page.extract_text() or "")
            if len(text) >= 20:
                sections.append(Section(f"Page {page_number}", text))
        return sections
    raise RuleConfigurationError(f"Unsupported knowledge document format: {path}")


def _markdown_sections(path: Path) -> list[Section]:
    sections: list[Section] = []
    title = "Document"
    content: list[str] = []
    for line in path.read_text(errors="replace").splitlines():
        match = re.match(r"^#{1,4}\s+(.+?)\s*$", line)
        if match:
            text = _normalize_text("\n".join(content))
            if len(text) >= 20:
                sections.append(Section(title, text))
            title = match.group(1).strip()
            content = []
        else:
            content.append(line)
    text = _normalize_text("\n".join(content))
    if len(text) >= 20:
        sections.append(Section(title, text))
    return sections


def _chunk_sections(source: KnowledgeSource, sections: list[Section]) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    ordinal = 0
    for section in sections:
        for text in _split_text(section.text):
            ordinal += 1
            identity = f"{source.source_id}\n{section.title}\n{ordinal}\n{text}"
            digest = hashlib.sha256(identity.encode()).hexdigest()[:12]
            combined = f"{section.title} {text}"
            chunks.append(
                KnowledgeChunk(
                    chunk_id=f"{source.source_id}_{digest}",
                    source_id=source.source_id,
                    section=section.title[:300],
                    text=text,
                    ordinal=ordinal,
                    parameter_tags=sorted(
                        tag
                        for tag, pattern in PARAMETER_PATTERNS.items()
                        if pattern.search(combined)
                    ),
                    problem_tags=sorted(
                        tag for tag, pattern in PROBLEM_PATTERNS.items() if pattern.search(combined)
                    ),
                )
            )
    return chunks


def _split_text(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHUNK_CHARS, len(text))
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            if boundary > start + MAX_CHUNK_CHARS // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if len(chunk) >= 20:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
    return chunks


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
