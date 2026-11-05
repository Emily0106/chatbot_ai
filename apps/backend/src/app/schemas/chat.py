# app/schemas/chat.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field, AliasChoices, field_validator, model_validator


# -----------------------------
# INPUT SCHEMAS
# -----------------------------

class RetrievalFilters(BaseModel):
    """
    Bo loc dung cho Vector Search & SQL (gioi han pham vi truy xuat).
    Luu y: tenant_id KHONG dat o day (tenant_id nen lay tu token / ChatRequest).
    """
    doc_type: Optional[str] = Field(default=None, description="Loai tai lieu: law, procedure, report, news...")
    doc_types: Optional[List[str]] = Field(default=None, description="Internal: List of allowed doc types (Policy)")
    domain: Optional[str] = Field(default=None, description="Linh vuc: dat_dai, y_te, giao_duc...")
    status: Optional[str] = Field(default=None, description="Trang thai: con_hieu_luc, het_hieu_luc (optional)")
    security_level: Optional[int] = Field(
        default=1,
        ge=1,
        le=5,
        description="Muc do mat: 1(Public) - 2(Internal) - 3(Secret) ... (MVP co the dung mac dinh 1)",
    )
    from_date: Optional[str] = Field(default=None, description="YYYY-MM-DD (optional)")
    to_date: Optional[str] = Field(default=None, description="YYYY-MM-DD (optional)")

    model_config = {"extra": "forbid"}


class ChatRequest(BaseModel):
    """
    Request gui tu Frontend.
    tenant_id thuong duoc lay tu token (security.py), nhung cho phep truyen vao de test.
    """
    agent_id: str = Field(..., description="ID agent duoc chon tu UI (legal, citizen, report...)")
    message: str = Field(..., min_length=1, description="Cau hoi cua nguoi dung")

    # Context
    tenant_id: Optional[str] = Field(default=None, description="Ma xa/phuong (uu tien lay tu token)")
    session_id: Optional[str] = Field(default=None, description="ID hoi thoai (optional)")
    trace_id: Optional[str] = Field(default=None, description="Trace ID cho observability (optional)")
    user_role: Literal["citizen", "officer", "chairman"] = Field(
        default="citizen",
        description="Vai tro nguoi dung: citizen | officer | chairman",
    )

    # File context (ho tro nhieu file)
    # Tuong thich nguoc: FE co the gui 'file_id' (string) hoac 'file_ids' (list)
    file_ids: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("file_ids", "file_id"),
        description="Danh sach ID file/doc da ingestion (co the gui 1 file_id)",
    )

    # Retrieval config
    top_k: int = Field(default=8, ge=1, le=50, description="So chunk lay tu Vector DB")
    filters: Optional[RetrievalFilters] = Field(default=None, description="Bo loc truy xuat")

    # User Context (Dictionary for extensibility: department_id, permissions...)
    context: Optional[Dict[str, Any]] = Field(default=None, description="Context nguoi dung (department_id, etc)")

    # Temp Flow (Dual Data Flow)
    temp_doc_id: Optional[str] = Field(default=None, description="ID tai lieu tam thoi (Redis)")

    # Behavior
    stream: bool = Field(default=True, description="Bat che do Streaming Response (SSE/WebSocket)")
    security_level: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Requested security level for this interaction (cannot exceed user's max)"
    )

    @field_validator("file_ids", mode="before")
    @classmethod
    def _coerce_file_ids(cls, v: Any) -> Any:
        # Chap nhan: None | "abc" | ["a","b"]
        if v is None:
            return None
        if isinstance(v, str):
            return [v]
        return v

    model_config = {"extra": "forbid"}


# -----------------------------
# OUTPUT SCHEMAS
# -----------------------------

class Citation(BaseModel):
    """
    Trich dan nguon.
    Uu tien hien thi: title -> section -> page.
    """
    chunk_id: str = Field(..., description="ID chunk (Qdrant point id / SQL chunks.chunk_id)")
    document_id: Optional[str] = Field(default=None, description="ID tai lieu")

    title: Optional[str] = Field(default=None, description="Tieu de van ban goc")

    # Tuong thich nguoc: co the nhan 'source_url' tu code cu
    file_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("file_url", "source_url"),
        description="Link file goc (MinIO/noi bo/web)",
    )

    # Dinh vi theo luat: Dieu/Khoan/Muc... quan trong hon so trang
    section: Optional[str] = Field(default=None, description="Vi tri Dieu/Khoan/Muc (vd: 'Dieu 5, Khoan 2')")

    page_start: Optional[int] = Field(default=None, description="Trang bat dau (optional)")
    page_end: Optional[int] = Field(default=None, description="Trang ket thuc (optional)")

    # Metadata phu
    score: Optional[float] = Field(default=None, description="Diem tu vector/rerank (optional)")
    snippet: Optional[str] = Field(default=None, description="Doan trich ngan (optional)")

    # Tuong thich nguoc: neu he thong cu chi co page_number
    page_number: Optional[int] = Field(default=None, description="(Deprecated) Trang (neu chi co 1 trang)")

    @model_validator(mode="after")
    def _fill_page_range(self) -> "Citation":
        # Neu chi co page_number thi gan vao page_start/page_end
        if self.page_number is not None and self.page_start is None and self.page_end is None:
            self.page_start = self.page_number
            self.page_end = self.page_number
        return self

    model_config = {"extra": "forbid"}


class ChatMeta(BaseModel):
    """
    Metadata cho debug/quan sat.
    """
    cache_hit: bool = False
    used_tools: List[str] = Field(default_factory=list)  # ["vector_search", "sql", "web_search", "rerank"]
    latency_ms: Optional[int] = None
    total_tokens: Optional[int] = None
    top_k: Optional[int] = None

    # Chi de debug (production co the tat)
    sql_query: Optional[str] = None

    debug_info: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class Handoff(BaseModel):
    """
    Contract chuyen tiep hoi thoai sang Agent khac.
    """
    target_agent_id: str = Field(..., description="ID agent dich (vd: legal_assistant)")
    reason: str = Field(..., description="Ly do: legal_intent_detected | policy_conflict | user_request")
    suggested_message: str = Field(..., description="Message se gui qua agent dich")
    ui_hint: Optional[str] = Field(default=None, description="Goi y hien thi UI")

class ChatResponse(BaseModel):
    """
    Phan hoi tra ve FE.
    Neu stream: day la goi 'final' (answer + citations + meta).
    """
    answer: str = Field(..., description="Cau tra loi hoan chinh")
    citations: List[Citation] = Field(default_factory=list, description="Danh sach trich dan")
    meta: ChatMeta = Field(default_factory=ChatMeta)
    handoff: Optional[Handoff] = Field(default=None, description="Yeu cau chuyen tiep agent")

    model_config = {"extra": "forbid"}
