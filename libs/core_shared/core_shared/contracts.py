from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field

EntityType = Literal["person", "record", "schedule", "doc_chunk"]

class SourceRef(BaseModel):
    source_uri: str
    sheet_name: Optional[str] = None
    row_index: Optional[int] = None
    page_index: Optional[int] = None

class Citation(BaseModel):
    source: SourceRef

class RecordPayload(BaseModel):
    """
    Payload chuẩn cho Qdrant/DB (Correctness-first).
    """
    entity_type: EntityType
    doc_id: UUID
    row_id: UUID

    # deterministic lookup keys
    code: Optional[str] = None
    name: Optional[str] = None
    name_ascii: Optional[str] = None

    # lexical keys
    search_text_ascii: Optional[str] = None
    search_tokens: List[str] = Field(default_factory=list)

    # truth data
    data_content: Dict[str, Any] = Field(default_factory=dict)

    # citation
    citation: Optional[Citation] = None

class ParsedQuery(BaseModel):
    """
    Output chuẩn của router/parser.
    """
    intent: Literal["EXACT_LOOKUP", "LIST_LOOKUP", "DOC_QA", "MIXED", "UNKNOWN"] = "UNKNOWN"
    entity_type: Optional[EntityType] = None

    # slots
    person_code: Optional[str] = None
    person_name: Optional[str] = None
    field: Optional[Literal["cccd","phone","email","address","occupation","note"]] = None
    keywords: List[str] = Field(default_factory=list)
