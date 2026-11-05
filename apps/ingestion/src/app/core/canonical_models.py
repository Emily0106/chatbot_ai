# preproc/canonical/models.py
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =========================
# Enums (strict + portable)
# =========================

from app.core.taxonomy import Scope, SecurityLevel, DocType


# =========================
# Enums (strict + portable)
# =========================

# Scope imported from taxonomy (SSoT)


class DocCategory(str, Enum):
    legal = "legal"
    list = "list"
    schedule = "schedule"
    report = "report"
    notice = "notice"
    procedure = "procedure"
    faq = "faq"
    mixed = "mixed"
    table = "table"


class ChunkKind(str, Enum):
    law_clause = "law_clause"
    paragraph = "paragraph"
    summary = "summary"
    row = "row"
    event = "event"


class AccessLevel(str, Enum):
    public = "public"
    internal = "internal"
    restricted = "restricted"


class DocStatus(str, Enum):
    active = "active"
    replaced = "replaced"
    inactive = "inactive"


# =========================
# Helpers
# =========================

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    """
    Convert common non-JSON types to JSON-safe types (recursively).
    Keep payloads small; drop Nones at call sites.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value if v is not None]
    # Fallback: best-effort stringify (avoid crashing ingestion)
    return str(value)


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# =========================
# Core security & citations
# =========================

class SecurityPolicy(BaseModel):
    """
    Security rules to be enforced downstream (retrieval/answer services).
    Frozen because it's part of canonical truth post-parse.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    access_level: AccessLevel = AccessLevel.public
    roles: List[str] = Field(default_factory=list)  # e.g. ["citizen", "officer"]


class SourceLocator(BaseModel):
    """
    Unified locator for citations across formats.

    - PDF/DOCX-like: page_start/page_end + anchor
    - XLSX/CSV-like: sheet_name + row/col range + optional anchor
    - Image/OCR: page_start/page_end or image index + anchor bbox id

    NOTE: page/row/col indices are 0-based internally.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_uri: str
    checksum: str
    mime_type: Optional[str] = None

    # Page-based (PDF/scan)
    page_start: Optional[int] = None
    page_end: Optional[int] = None

    # Spreadsheet-based
    sheet_name: Optional[str] = None
    row_start: Optional[int] = None
    row_end: Optional[int] = None
    col_start: Optional[int] = None
    col_end: Optional[int] = None

    # Generic anchor inside a page/sheet (block id, xml path, bbox id...)
    anchor: Optional[str] = None

    @field_validator("source_uri", "checksum")
    @classmethod
    def _required_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("source_uri/checksum must not be empty")
        return v

    @field_validator("page_start", "page_end")
    @classmethod
    def _non_negative_pages(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v < 0:
            raise ValueError("page_start/page_end must be >= 0")
        return v

    @field_validator("row_start", "row_end", "col_start", "col_end")
    @classmethod
    def _non_negative_sheet_coords(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v < 0:
            raise ValueError("sheet row/col indices must be >= 0")
        return v

    @model_validator(mode="after")
    def _check_ranges(self) -> "SourceLocator":
        # Page range
        if self.page_start is not None and self.page_end is not None:
            if self.page_end < self.page_start:
                raise ValueError(f"page_end ({self.page_end}) < page_start ({self.page_start})")

        # Row range
        if self.row_start is not None and self.row_end is not None:
            if self.row_end < self.row_start:
                raise ValueError(f"row_end ({self.row_end}) < row_start ({self.row_start})")

        # Col range
        if self.col_start is not None and self.col_end is not None:
            if self.col_end < self.col_start:
                raise ValueError(f"col_end ({self.col_end}) < col_start ({self.col_start})")

        return self

    def short(self) -> str:
        """
        Human-readable locator string for logs/UI.
        (Converts internal 0-based indices to 1-based for display.)
        """
        parts: List[str] = []

        if self.page_start is not None:
            if self.page_end is not None and self.page_end != self.page_start:
                parts.append(f"p{self.page_start + 1}-p{self.page_end + 1}")
            else:
                parts.append(f"p{self.page_start + 1}")

        if self.sheet_name:
            parts.append(f"sheet:{self.sheet_name}")

        if self.row_start is not None:
            if self.row_end is not None and self.row_end != self.row_start:
                parts.append(f"r{self.row_start + 1}-r{self.row_end + 1}")
            else:
                parts.append(f"r{self.row_start + 1}")

        if self.anchor:
            parts.append(str(self.anchor))

        return " | ".join(parts) if parts else "unlocated"


class Citation(BaseModel):
    """
    What Citation Guard expects:
    - must include a stable locator (SourceLocator)
    - optional char offsets for UI highlighting
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    locator: SourceLocator
    char_start: Optional[int] = None
    char_end: Optional[int] = None

    @field_validator("char_start", "char_end")
    @classmethod
    def _non_negative_chars(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v < 0:
            raise ValueError("char offsets must be >= 0")
        return v

    @model_validator(mode="after")
    def _check_char_range(self) -> "Citation":
        if self.char_start is not None and self.char_end is not None:
            if self.char_end < self.char_start:
                raise ValueError(f"char_end ({self.char_end}) < char_start ({self.char_start})")
        return self


# =========================
# Canonical storage entities
# =========================

class CanonicalDocument(BaseModel):
    """
    Canonical document metadata (stored in Postgres documents table).
    Frozen because this is "truth" post-parse.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: UUID
    tenant_id: str
    doc_type: str
    scope: Scope
    security_level: int
    
    department_id: Optional[str] = None
    geo_code: Optional[str] = None
    domain: Optional[str] = None
    
    commune_id: Optional[str] = None

    doc_category: DocCategory
    title: str

    source_uri: Optional[str] = None
    mime_type: Optional[str] = None

    checksum: str
    pipeline_version: str

    issued_date: Optional[date] = None
    effective_date: Optional[date] = None

    status: DocStatus = DocStatus.active
    replaced_by: Optional[UUID] = None

    security: SecurityPolicy = Field(default_factory=SecurityPolicy)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=_now_utc)

    @field_validator("title")
    @classmethod
    def _title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        return v

    @field_validator("checksum", "pipeline_version")
    @classmethod
    def _required_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("checksum/pipeline_version must not be empty")
        return v

    @field_validator("commune_id")
    @classmethod
    def _commune_id_strip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        return v or None

    @model_validator(mode="after")
    def _check_replaced_rules(self) -> "CanonicalDocument":
        if self.status == DocStatus.replaced and self.replaced_by is None:
            raise ValueError("status=replaced requires replaced_by")
        if self.replaced_by is not None and self.replaced_by == self.doc_id:
            raise ValueError("replaced_by must not equal doc_id")
        return self


class CanonicalChunk(BaseModel):
    """
    Canonical chunk:
    - display_text is the ONLY thing the LLM should quote.
    - embed_text is for embedding; MUST NOT introduce new facts.
      (We cannot enforce semantics here, but we default embed_text to display_text.)
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: UUID
    doc_id: UUID
    
    tenant_id: str
    doc_type: str
    scope: Scope
    security_level: int
    
    department_id: Optional[str] = None
    geo_code: Optional[str] = None
    domain: Optional[str] = None

    commune_id: Optional[str] = None
    doc_category: DocCategory

    chunk_kind: ChunkKind
    order_index: int = 0

    display_text: str
    embed_text: Optional[str] = None

    citation: Citation

    # Parent-child support (Small-to-Big retrieval)
    parent_chunk_id: Optional[UUID] = None

    # Law-specific (optional)
    law_ref: Optional[str] = None
    section_path: Optional[str] = None

    created_at: datetime = Field(default_factory=_now_utc)

    @field_validator("display_text")
    @classmethod
    def _display_text_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_text must not be empty")
        return v

    @field_validator("order_index")
    @classmethod
    def _order_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("order_index must be >= 0")
        return v

    @field_validator("embed_text")
    @classmethod
    def _embed_text_default(cls, v: Optional[str], info) -> Optional[str]:
        # If not provided, default to display_text (safe baseline).
        if v is None:
            return info.data.get("display_text", "")
        v2 = v.strip()
        return v2 if v2 else info.data.get("display_text", "")

    @model_validator(mode="after")
    def _check_parent(self) -> "CanonicalChunk":
        if self.parent_chunk_id is not None and self.parent_chunk_id == self.chunk_id:
            raise ValueError("parent_chunk_id must not equal chunk_id")
        return self

    def qdrant_payload(self) -> Dict[str, Any]:
        """
        Qdrant payload must be JSON-serializable and should stay small.
        Do NOT include long display_text.
        """
        loc = self.citation.locator

        payload = {
            # Contract SSoT Keys
            "tenant_id": self.tenant_id,
            "doc_type": self.doc_type,
            "scope": self.scope,
            "security_level": self.security_level,
            "department_id": self.department_id,
            "geo_code": self.geo_code,
            "domain": self.domain,

            # Standard Keys
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "parent_chunk_id": self.parent_chunk_id,
            
            # Legacy/Internal (Removed for Strict Producer)
            # "commune_id": self.commune_id,
            # "doc_category": self.doc_category,
            "chunk_kind": self.chunk_kind,
            "order_index": self.order_index,

            "source": {
                "source_uri": loc.source_uri,
                "mime_type": loc.mime_type,
                "checksum": loc.checksum,
                "page_start": loc.page_start,
                "page_end": loc.page_end,
                "sheet_name": loc.sheet_name,
                "row_start": loc.row_start,
                "row_end": loc.row_end,
                "col_start": loc.col_start,
                "col_end": loc.col_end,
                "anchor": loc.anchor,
            },
            "law": {
                "law_ref": self.law_ref,
                "section_path": self.section_path,
            },
        }

        # Convert to JSON-safe primitives; drop None values.
        return _jsonable(payload)


class CanonicalStructuredRow(BaseModel):
    """
    Structured row/event for SQL/JSONB truth.
    Frozen because rows are canonical "facts" post-parse.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    row_id: UUID
    doc_id: UUID

    commune_id: Optional[str] = None
    doc_category: DocCategory  # typically list|schedule

    row_index: int = 0
    data_content: Dict[str, Any] = Field(default_factory=dict)

    # Normalized concatenation of values for fast lookup (trgm/fts)
    search_text: str
    search_text_norm: str = ""

    citation: Citation
    created_at: datetime = Field(default_factory=_now_utc)

    @field_validator("row_index")
    @classmethod
    def _row_index_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("row_index must be >= 0")
        return v

    @field_validator("search_text", "search_text_norm")
    @classmethod
    def _search_text_strip(cls, v: str) -> str:
        return v.strip()


# =========================
# Extractor outputs (internal)
# (Mutable on purpose: extractors may enrich blocks progressively.)
# =========================

class ExtractedBlockKind(str, Enum):
    text = "text"
    table = "table"
    figure = "figure"


class ExtractedBlock(BaseModel):
    """
    Intermediate representation from Extractors (Docling/pdftext/openpyxl/OCR).
    Parsers will consume these blocks and produce canonical outputs.
    """
    model_config = ConfigDict(extra="forbid")

    kind: ExtractedBlockKind
    page_index: Optional[int] = None  # 0-based for PDF/scan; None for spreadsheets
    order_index: int = 0              # reading-order within doc (best effort)

    # For text blocks: markdown/plain text
    text: Optional[str] = None

    # For table blocks: 2D cells + optional header rows guess
    table: Optional[List[List[Any]]] = None
    table_header_rows: Optional[int] = None

    # For figures: optional caption text or placeholder id
    figure_id: Optional[str] = None
    figure_caption: Optional[str] = None

    # Anchor for citation (block id from Docling, OCR bbox id, etc.)
    anchor: Optional[str] = None

    # Metadata (e.g. source, mode, format)
    meta: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("order_index")
    @classmethod
    def _block_order_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("order_index must be >= 0")
        return v

    @field_validator("page_index")
    @classmethod
    def _page_index_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v < 0:
            raise ValueError("page_index must be >= 0")
        return v


class ExtractedDoc(BaseModel):
    """
    Single output type for all extractors.
    """
    model_config = ConfigDict(extra="forbid")

    mime_type: str
    blocks: List[ExtractedBlock] = Field(default_factory=list)

    # Optional physical-layer metadata
    page_count: Optional[int] = None
    has_text_layer: bool = False
    has_tables: bool = False

    # Metadata (e.g. extractor name, mode, timings)
    meta: Dict[str, Any] = Field(default_factory=dict)

    def iter_blocks(self) -> Sequence[ExtractedBlock]:
        """
        Ensure stable reading-order:
        - sort by page_index (None last)
        - then by order_index
        """
        def key(b: ExtractedBlock):
            page = b.page_index if b.page_index is not None else 10**9
            return (page, b.order_index)

        return sorted(self.blocks, key=key)


# =========================
# Admin / Cockpit Entities
# =========================

class IngestionProfileConfig(BaseModel):
    """
    Configuration payload for an ingestion profile.
    Defines default behaviors for ingestion jobs tied to this profile.
    """
    model_config = ConfigDict(extra="forbid")
    
    scope: Optional[Scope] = None
    security_level: Optional[int] = None
    doc_type: Optional[str] = None
    
    # Auto-tagging
    department_id_override: Optional[str] = None
    doc_category_override: Optional[DocCategory] = None
    
    # Processing rules
    auto_approve: bool = False  # If true, skips quarantine (future)
    priority: int = 10          # Job priority (future)


class IngestionProfile(BaseModel):
    """
    Named configuration template for ingestion.
    Managed by Admins to standardize ingestion policies.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)
    
    profile_id: UUID
    tenant_id: str
    
    name: str
    description: Optional[str] = None
    
    config: IngestionProfileConfig = Field(default_factory=IngestionProfileConfig)
    
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("profile name must not be empty")
        return v
