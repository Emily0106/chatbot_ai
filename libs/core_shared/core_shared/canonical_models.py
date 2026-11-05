from __future__ import annotations

from typing import Any, Dict, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


EntityType = Literal["person", "doc", "table_row"]


class SourceRef(BaseModel):
    """
    Định vị nguồn dữ liệu (Excel/CSV/PDF/TXT) để backend có thể trích dẫn.
    """
    source_uri: str
    sheet_name: Optional[str] = None
    row_index: Optional[int] = None
    page_index: Optional[int] = None


class Citation(BaseModel):
    """
    Citation chuẩn cho cả backend & ingestion.
    """
    source: SourceRef
    snippet: Optional[str] = None


class PersonData(BaseModel):
    """
    Payload dữ liệu người (dạng JSON) - ingestion ghi, backend đọc.
    Bạn có thể thêm/bớt field, nhưng nên giữ ổn định để tránh lệch pha.
    """
    code: Optional[str] = None
    full_name: str
    gender: Optional[str] = None
    dob: Optional[str] = None
    cccd: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    ward_commune: Optional[str] = None
    occupation: Optional[str] = None
    note: Optional[str] = None


class PersonPointPayload(BaseModel):
    """
    Payload lưu trong Qdrant (Point payload).
    """
    entity_type: EntityType = "person"

    doc_id: UUID
    row_id: UUID = Field(default_factory=uuid4)

    # để search / hiển thị
    name: str
    name_norm: str
    code: Optional[str] = None

    # citation & raw data
    citation: Citation
    data_content: Dict[str, Any]  # JSONB-friendly

    # optional metadata
    dataset_id: Optional[str] = None
    version: Optional[str] = None


class EmbeddedPoint(BaseModel):
    """
    Một unit upsert sang Qdrant.
    """
    point_id: UUID = Field(default_factory=uuid4)
    vector: list[float]
    payload: PersonPointPayload
