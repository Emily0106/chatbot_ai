# preproc/pipeline/interfaces.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, Union

from app.core.canonical_models import (
    CanonicalChunk,
    CanonicalDocument,
    CanonicalStructuredRow,
    DocCategory,
    ExtractedBlock,
    ExtractedDoc,
    Scope,
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# -------------------------
# Errors (robustness)
# -------------------------

class IngestionError(Exception):
    """Base class for ingestion errors (safe to surface to API)."""


class UnsupportedMimeTypeError(IngestionError):
    pass


class ExtractionError(IngestionError):
    pass


class ClassificationError(IngestionError):
    pass


class ParseError(IngestionError):
    pass


class EmbedError(IngestionError):
    pass


# -------------------------
# Ingestion request metadata
# -------------------------

@dataclass(frozen=True)
class IngestMeta:
    """
    Metadata that travels through the ingestion pipeline.
    """
    tenant_id: str  # Strictly TenantId but used as str for dataclass simplicity or import types
    doc_type: str   # Strictly DocType
    scope: str      # Strictly Scope
    security_level: int # Strictly SecurityLevel

    source_uri: str
    checksum: str
    mime_type: str

    title: str
    pipeline_version: str

    # Context
    department_id: Optional[str] = None
    geo_code: Optional[str] = None
    domain: Optional[str] = None

    issued_date: Optional[date] = None
    effective_date: Optional[date] = None

    # Hints
    strategy: str = "auto"
    ingest_lane: str = "auto"
    
    # Legacy/Mapping
    commune_id: Optional[str] = None
    doc_category_hint: Optional[DocCategory] = None

    # Security / extra metadata
    security: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Embedding safety
    embed_batch_size: int = 64
    created_at: datetime = field(default_factory=now_utc)


@dataclass(frozen=True)
class ClassificationResult:
    """
    Output of Classifier.

    block_overrides: optional per-block overrides for routing:
      key = stable block key, value = {"route_kind": "text"|"table"|"figure", ...}
    """
    doc_category: DocCategory
    confidence: float = 0.0
    block_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def is_low_confidence(self, threshold: float = 0.6) -> bool:
        return self.confidence < threshold


# -------------------------
# Protocols (interfaces)
# -------------------------

class Extractor(Protocol):
    """
    Extract raw file -> ExtractedDoc(blocks, tables, layout).

    Error handling contract:
    - raise ExtractionError for corrupt/unsupported content
    - never return None
    """
    def extract(self, file_path: str, meta: IngestMeta) -> ExtractedDoc: ...


class Classifier(Protocol):
    """
    ExtractedDoc -> doc_category + confidence (+ optional block overrides)

    Error handling contract:
    - raise ClassificationError only for unexpected internal failure
    """
    def classify(self, extracted: ExtractedDoc, meta: IngestMeta) -> ClassificationResult: ...


class BlockParser(Protocol):
    """
    Parse a single extracted block into canonical outputs.
    This is the key to Mixed-Content robustness.

    Error handling contract:
    - raise ParseError for parse failure on a block (or return empty outputs)
    """
    def parse_block(
        self,
        block: ExtractedBlock,
        meta: IngestMeta,
        classification: ClassificationResult,
        doc: CanonicalDocument,
    ) -> Tuple[List[CanonicalChunk], List[CanonicalStructuredRow]]: ...


class Embedder(Protocol):
    """
    Local embedding (no external APIs).
    Implementations should prefer internal batching, but orchestrator also enforces batching.
    """
    def embed(self, texts: Sequence[str]) -> List[List[float]]: ...


class PostgresRepo(Protocol):
    """Canonical truth store (documents/chunks/rows)."""
    def upsert_document(self, doc: CanonicalDocument) -> None: ...
    def upsert_chunks(self, chunks: Sequence[CanonicalChunk]) -> None: ...
    def upsert_rows(self, rows: Sequence[CanonicalStructuredRow]) -> None: ...

    # Optional job hooks (implement as no-op if you don't need them)
    def mark_job_running(self, job_id: str) -> None: ...
    def mark_job_done(self, job_id: str, stats: Dict[str, Any]) -> None: ...
    def mark_job_failed(self, job_id: str, error: str) -> None: ...


class QdrantRepo(Protocol):
    """Vector store."""
    def upsert_chunks(self, chunks: Sequence[CanonicalChunk], vectors: Sequence[Sequence[float]]) -> None: ...


# -------------------------
# Utilities
# -------------------------

def block_key(block: ExtractedBlock) -> str:
    """
    Stable key to reference a block when you want per-block overrides.
    """
    p = block.page_index if block.page_index is not None else -1
    return f"p{p}|o{block.order_index}|k{block.kind.value}"
