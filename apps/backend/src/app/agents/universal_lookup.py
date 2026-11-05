# apps/backend/src/app/agents/universal_lookup.py
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Literal, Tuple

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.schemas.chat import ChatRequest, ChatResponse

from app.core.llm.structured_outputs import aextract_pydantic
from app.core.db_sql import run_lookup_sql, get_async_db
from app.agents.contract import TrustedContext, AgentResponse


# ---------- 1) CONTRACT: LLM chỉ được trả JSON theo schema này ----------

Category = Literal[
    "people",
    "poverty_household",
    "land_lookup",
    "schedule_lookup",
    "generic_rows",
]

class ExtractedLookup(BaseModel):
    category: Category = Field(..., description="Loại tra cứu")
    # Entity identifiers (ưu tiên exact)
    full_name: Optional[str] = None
    code: Optional[str] = None
    cccd: Optional[str] = None

    # Constraints / scope
    commune_id: Optional[str] = None
    year: Optional[int] = None

    # Field user wants (optional)
    want_field: Optional[str] = Field(
        default=None,
        description="Nếu user hỏi 1 trường cụ thể như phone/cccd/address thì điền vào đây",
    )

    missing: List[str] = Field(default_factory=list, description="Danh sách tham số còn thiếu")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


LOOKUP_CAPABILITIES = {
    "people": {
        "required_one_of": ["code", "cccd", "full_name"],
        "canonical_fields": ["full_name", "code", "cccd", "phone", "email", "address", "unit", "occupation", "note", "commune_id"],
    },
    "poverty_household": {
        "required_one_of": ["cccd", "full_name"],
        "canonical_fields": ["full_name", "cccd", "poverty_status", "year", "commune_id"],
        "notes": "Trả lời YES/NO dựa trên DB, không suy đoán.",
    },
    "land_lookup": {
        "required_one_of": ["map_sheet", "plot_number"],
        "canonical_fields": ["map_sheet", "plot_number", "owner_name", "status", "commune_id", "year"],
    },
    "schedule_lookup": {
        "required_one_of": ["topic", "date"],
        "canonical_fields": ["topic", "date", "location", "contact", "commune_id"],
    },
    "generic_rows": {
        "required_one_of": ["full_name"],
        "canonical_fields": ["*"],
    },
}


def _build_extractor_prompt(question: str) -> Tuple[str, str]:
    system = (
        "Bạn là hệ thống trích xuất tham số tra cứu cho Chính phủ điện tử.\n"
        "Nhiệm vụ: đọc câu hỏi và điền JSON theo schema đã cho.\n"
        "Luật quan trọng:\n"
        "- Không bịa dữ liệu.\n"
        "- Nếu thiếu tham số bắt buộc, điền vào missing (mảng string).\n"
        "- category phải thuộc danh sách cho phép.\n"
        "- Ưu tiên nhận diện code/cccd nếu có.\n"
    )

    user = (
        f"Các loại tra cứu hệ thống hỗ trợ (capabilities):\n{LOOKUP_CAPABILITIES}\n\n"
        f"Câu hỏi người dùng:\n{question}\n"
    )
    return system, user


def _validate_extracted(x: ExtractedLookup) -> ExtractedLookup:
    cap = LOOKUP_CAPABILITIES.get(x.category, {})
    required_one_of = cap.get("required_one_of") or []
    if required_one_of:
        has_any = any(getattr(x, k, None) for k in required_one_of)
        if not has_any:
            x.missing = sorted(set(x.missing + required_one_of))
    return x


class UniversalLookupAgent(BaseAgent):
    agent_id = "universal_lookup"
    name = "Universal Lookup Agent"
    description = "Tra cứu chính xác cao bằng LLM extraction + SQL deterministic"

    def __init__(self) -> None:
        super().__init__()
        self.llm_model = os.getenv("OPENAI_EXTRACT_MODEL", "gpt-4o-mini")  # model có Structured Outputs

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        question = (query or "").strip()
        if not question:
            return self.build_response(answer="Câu hỏi trống.")

        # 1) Extract
        system, user = _build_extractor_prompt(question)
        try:
            x = await aextract_pydantic(
                response_model=ExtractedLookup,
                llm_model=self.llm_model,
                system=system,
                user=user,
                schema_name="extracted_lookup",
            )
        except Exception as e:
            return self.build_response(answer=f"Lỗi khi xử lý câu hỏi: {e}")

        x = _validate_extracted(x)

        # 2) Ask for missing
        if x.missing:
            # hỏi lại đúng cái thiếu
            missing_str = ", ".join(x.missing)
            return self.build_response(
                answer=(
                    "Mình cần thêm thông tin để tra cứu chính xác.\n"
                    f"Bạn vui lòng cung cấp: **{missing_str}**.\n"
                    "Ví dụ: 'người A' hoặc 'CCCD 1090000001' hoặc 'Nguyễn Văn A'."
                )
            )

        # 3) Execute deterministic SQL
        rows = []
        async for session in get_async_db():
            rows = await run_lookup_sql(
                session, 
                category=x.category, 
                params=x.model_dump(), 
                user_security_level=ctx.security_level
            )
            break

        if not rows:
            return self.build_response(
                answer="Không tìm thấy dữ liệu phù hợp trong CSDL. Bạn kiểm tra lại tên/CCCD/mã hoặc phạm vi (xã/năm) nhé."
            )

        # 4) Render answer (NO hallucination)
        # rows: List[{"data":..., "citation":..., "score":...optional}]
        # Nếu nhiều kết quả -> disambiguation
        if len(rows) > 1 and x.category in ("people", "poverty_household"):
            options = []
            for r in rows[:5]:
                d = r["data"]
                options.append(f"- {d.get('full_name')} (mã {d.get('code')}, cccd {d.get('cccd')})")
            return self.build_response(
                answer="Mình thấy nhiều bản ghi gần giống, bạn chọn đúng người:\n" + "\n".join(options),
                citations=[self.make_citation_from_row(rows[0])],
            )

        best = rows[0]
        data: Dict[str, Any] = best["data"]
        citations = [self.make_citation_from_row(best)]

        # field-specific
        if x.want_field and x.want_field in data:
            return self.build_response(
                answer=f"{data.get('full_name','(không rõ)')} — {x.want_field}: {data.get(x.want_field)}",
                citations=citations,
            )

        # category-specific formatting
        if x.category == "poverty_household":
            status = data.get("poverty_status")
            if status:
                return self.build_response(
                    answer=f"{data.get('full_name')} ({data.get('cccd')}): **{status}** (năm {data.get('year')}).",
                    citations=citations,
                )
            return self.build_response(
                answer="Có bản ghi nhưng thiếu trường poverty_status trong dữ liệu. Cần kiểm tra ingestion/mapping cột.",
                citations=citations,
            )

        # default: show a “card”
        keys = [k for k in data.keys() if k not in ("search_text",)]
        lines = ["Thông tin tra cứu:"]
        for k in keys:
            lines.append(f"- {k}: {data.get(k)}")
        return self.build_response(answer="\n".join(lines), citations=citations)

    def make_citation_from_row(self, row: Dict[str, Any]):
        cit = row.get("citation") or {}
        return self.make_citation(
            chunk_id=str(row.get("row_id") or ""),
            file_url=cit.get("source_uri"),
            snippet=f"Sheet: {cit.get('sheet_name')}, Row: {cit.get('row_index')}",
            score=float(row.get("score") or 1.0),
        )
