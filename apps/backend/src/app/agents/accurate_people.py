from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
import re
from dataclasses import dataclass
import logging
import uuid

from qdrant_client import QdrantClient

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode
from app.schemas.chat import ChatRequest, ChatResponse
from core_shared.text_utils import ascii_norm
from app.core.router import route_query
from app.core.retrieval_structured import scroll_exact_person
from app.core.db_sql import get_async_db, run_lookup_sql
from app.core.sql.executor import SQLExecutor
from app.core.sql.types import SecurityError, ValidationError, TimeoutError
from app.config import settings
from app.core.sql.generator import SQLGenerator

logger = logging.getLogger(__name__)

_FIELD_HINTS = {
    "cccd": ["cccd", "can cuoc", "so cccd", "can cuoc cong dan"],
    "phone": ["dien thoai", "sdt", "so dt", "phone"],
    "email": ["email", "mail"],
    "address": ["dia chi", "address"],
}

_LIST_ALL_HINTS = [
    "danh sach", "liet ke", "tat ca", "toan bo", "nhan su", "can bo",
]

_ROLE_HINTS = [
    "ai phu trach", "phu trach", "phu trach tiem chung", "tiem chung"
]

_HONORIFICS = ["ong", "ba", "anh", "chi", "co", "chu"]


@dataclass
class PeopleParsed:
    intent: str  # LIST_ALL | LIST_LOOKUP | FIELD_LOOKUP | EXACT_BY_CODE | EXACT_BY_NAME
    code: Optional[str] = None
    full_name: Optional[str] = None
    field: Optional[str] = None
    q_ascii: Optional[str] = None


def _guess_field(q_ascii: str) -> Optional[str]:
    for f, hints in _FIELD_HINTS.items():
        if any(h in q_ascii for h in hints):
            return f
    return None


def _extract_code(q_ascii: str) -> Optional[str]:
    # bắt mẫu "ông c", "người b", "ma a", "ten la c", hoặc cuối câu là a/b/c
    # (giúp cả typo kiểu "ngoi b" vì vẫn có token b)
    tokens = q_ascii.split()
    if not tokens:
        return None

    # 1) nếu query chỉ là "a"/"b"/"c"
    if len(tokens) == 1 and tokens[0] in ("a", "b", "c"):
        return tokens[0].upper()

    # 2) nếu token cuối là a/b/c và câu ngắn (2-3 token) -> coi như code
    if len(tokens) <= 3 and tokens[-1] in ("a", "b", "c"):
        return tokens[-1].upper()

    # 3) nếu có kính ngữ + a/b/c
    m = re.search(r"\b(" + "|".join(_HONORIFICS) + r")\s+([abc])\b", q_ascii)
    if m:
        return m.group(2).upper()

    # 4) "ten la c", "ma c", "nguoi c"
    m2 = re.search(r"\b(ten|ma|nguoi)\s+(la\s+)?([abc])\b", q_ascii)
    if m2:
        return m2.group(3).upper()

    return None


def parse_people_intent(message: str) -> Optional[PeopleParsed]:
    # Use Tier 0 normalization (typo fix + lower + punctuation)
    # Then ascii_norm to remove accents for matching
    from core_shared.text_utils import normalize_query_for_router
    
    q_norm = normalize_query_for_router(message or "")
    q_ascii = ascii_norm(q_norm)
    q_ascii = " ".join(q_ascii.strip().split())

    if not q_ascii:
        return None

    # LIST_ALL
    if any(h in q_ascii for h in _LIST_ALL_HINTS) and ("nhan su" in q_ascii or "can bo" in q_ascii):
        return PeopleParsed(intent="LIST_ALL", q_ascii=q_ascii)

    # LIST_LOOKUP (role)
    if any(h in q_ascii for h in _ROLE_HINTS) or ("ai" in q_ascii and "phu trach" in q_ascii):
        return PeopleParsed(intent="LIST_LOOKUP", q_ascii=q_ascii)

    field = _guess_field(q_ascii)
    code = _extract_code(q_ascii)

    # FIELD_LOOKUP (cccd b / cccd của a / email ông c ...)
    if field and code:
        return PeopleParsed(intent="FIELD_LOOKUP", field=field, code=code, q_ascii=q_ascii)

    # EXACT BY CODE (ông c là ai / ai có tên là c / người b)
    if code and ("ai" in q_ascii or "la ai" in q_ascii or "thong tin" in q_ascii or "nguoi" in q_ascii or any(h in q_ascii for h in _HONORIFICS)):
        return PeopleParsed(intent="EXACT_BY_CODE", code=code, q_ascii=q_ascii)

    # EXACT BY NAME: nếu câu có >=2 token và chứa "la ai"/"thong tin"
    # Fix: "thong tin" quá chung chung, dễ bắt nhầm "thông tin về luật..."
    # Chỉ bắt nếu "thông tin" đi kèm "ông/bà/anh/chị/cô/chú" hoặc "của"
    if ("la ai" in q_ascii) and len(q_ascii.split()) >= 3:
         return PeopleParsed(intent="EXACT_BY_NAME", full_name=message.strip(), q_ascii=q_ascii)

    if ("thong tin" in q_ascii) and len(q_ascii.split()) >= 3:
        # Check honorifics or "cua"
        if any(h in q_ascii for h in _HONORIFICS) or "cua" in q_ascii or "ve ong" in q_ascii or "ve ba" in q_ascii:
             return PeopleParsed(intent="EXACT_BY_NAME", full_name=message.strip(), q_ascii=q_ascii)

    return None

class AccuratePeopleAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="accurate_people",
        name="Accurate People Agent",
        description="Correctness-first lookup/list people. No LLM facts.",
        doc_types=["structured_rows"]
    )
    
    policy = AgentPolicy(
        required_clearance=2, # Higher clearance for personal data
        required_scopes=["people:read"]
    )
    
    def __init__(self) -> None:
        super().__init__()
        self.qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        self.collection = os.getenv("QDRANT_COLLECTION_PEOPLE", "people_demo")
        self.client = QdrantClient(url=self.qdrant_url)
        self.executor = SQLExecutor()
        self.generator = SQLGenerator()

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        # Reconstruct ChatRequest for Legacy Logic fallback
        req = ChatRequest(
            **ctx.request_payload
        )
        req.message = query # ensure query is sync
        req.security_level = ctx.security_level
        # Note: ChatRequest fields might trigger defaults if missing in payload
        # but ctx.request_payload comes from ChatRequest.model_dump() usually.
        
        return await self._process_legacy(req)

    async def _process_legacy(self, req: ChatRequest) -> ChatResponse:
        q = getattr(req, "message", None) or getattr(req, "query", "") or ""
        
        # 0) Parse Intent (Deterministic)
        parsed_intent = parse_people_intent(q)
        
        intent_type = parsed_intent.intent if parsed_intent else None
        
        # 1) EXACT_LOOKUP (Code or Name)
        if intent_type in ("EXACT_BY_CODE", "EXACT_BY_NAME") or (not intent_type and route_query(q).intent == "EXACT_LOOKUP"):
            code = parsed_intent.code if parsed_intent and parsed_intent.intent == "EXACT_BY_CODE" else None
            name_ascii = ascii_norm(parsed_intent.full_name) if parsed_intent and parsed_intent.intent == "EXACT_BY_NAME" else None
            
            if not intent_type:
                old_parsed = route_query(q)
                code = old_parsed.person_code
                name_ascii = ascii_norm(old_parsed.person_name) if old_parsed.person_name else None

            payloads = scroll_exact_person(
                self.client,
                collection=self.collection,
                code=code,
                name_ascii=name_ascii,
                limit=3,
            )
            
            # Fallback scan for name if no exact match found
            if not payloads and name_ascii:
                all_pts = scroll_exact_person(self.client, collection=self.collection, limit=50)
                best_match = None
                for p in all_pts:
                    d = p.get("data_content") or {}
                    full_name = ascii_norm(d.get("full_name") or "")
                    if name_ascii in full_name or full_name in name_ascii:
                        best_match = p
                        break
                if best_match:
                    payloads = [best_match]

            if not payloads:
                return self.build_response(answer="Không tìm thấy người phù hợp. Bạn cung cấp rõ mã (A/B/C) hoặc họ tên đầy đủ nhé.")
            
            if len(payloads) > 1:
                opts = []
                for p in payloads:
                    d = p.get("data_content") or {}
                    opts.append(f"- {d.get('full_name')} (mã {d.get('code')})")
                return self.build_response(answer="Mình thấy nhiều kết quả, bạn chọn giúp:\n" + "\n".join(opts))

            return self._render_one(payloads[0], field=parsed_intent.field if parsed_intent and parsed_intent.intent == "FIELD_LOOKUP" else None)

        # 2) FIELD_LOOKUP (Code + Field)
        if intent_type == "FIELD_LOOKUP":
             payloads = scroll_exact_person(
                self.client,
                collection=self.collection,
                code=parsed_intent.code,
                limit=1,
            )
             if not payloads:
                 return self.build_response(answer=f"Không tìm thấy nhân sự mã {parsed_intent.code} để tra cứu {parsed_intent.field}.")
             return self._render_one(payloads[0], field=parsed_intent.field)

        # 3) LIST_LOOKUP or LIST_ALL
        if intent_type in ("LIST_LOOKUP", "LIST_ALL") or (not intent_type and route_query(q).intent == "LIST_LOOKUP"):
            
            search_term = parsed_intent.q_ascii if parsed_intent and parsed_intent.intent == "LIST_LOOKUP" else None
            is_list_all = (intent_type == "LIST_ALL")
            
            if not intent_type:
                 old_parsed = route_query(q)
                 q_norm = ascii_norm(q)
                 search_term = " ".join(old_parsed.keywords) if old_parsed.keywords else q_norm

            # Tenant ID
            tenant_id = getattr(req, "tenant_id", "default")
            trace_id = getattr(req, "trace_id", None) or str(uuid.uuid4())
            rows = []

            try:
                if settings.ENABLE_NEW_SQL_CORE:
                    # --- NEW CORE LANE (OPTIMIZED) ---
                    gen_result = await self.generator.generate(q) 
                    
                    sql_query = gen_result.get("sql")
                    sql_params = gen_result.get("params", {})
                    
                    exec_res = await self.executor.execute_safe(
                        sql=sql_query, 
                        tenant_id=tenant_id, 
                        params=sql_params,
                        trace_id=trace_id
                    )
                    rows = exec_res.get("data", [])
                else:
                    # --- LEGACY LANE (DEPRECATED) ---
                    from app.core.db_sql import run_lookup_sql, get_async_db
                    async for db in get_async_db():
                        legacy_res = await run_lookup_sql(db, category="people", params={
                            "q_ascii": search_term,
                            "list_all": is_list_all,
                            "commune_id": tenant_id
                        }, user_security_level=getattr(req, "security_level", 1))
                        rows = [r["data"] for r in legacy_res]
                        break

                    # --- SHADOW MODE (SQL-P2-04) ---
                    if settings.SQL_SHADOW_MODE:
                        try:
                            base_sql = "SELECT * FROM view_people"
                            query_params = {}
                            where_clauses = []
                            
                            if search_term:
                                where_clauses.append("full_name ILIKE :search_term")
                                query_params["search_term"] = f"%{search_term}%"
                            
                            if where_clauses:
                                base_sql += " WHERE " + " AND ".join(where_clauses)
                            
                            shadow_res = await self.executor.execute_safe(base_sql, tenant_id, params=query_params, trace_id=trace_id)
                            shadow_rows = shadow_res.get("data", [])
                            
                            match = len(rows) == len(shadow_rows)
                            logger.info(f"[SQL_SHADOW] Match={match}")
                        except Exception as e:
                            logger.warning(f"[SQL_SHADOW] Failed: {e}")

            except SecurityError as e:
                return self.build_response(answer=f"⚠️ Yêu cầu bị từ chối: Vi phạm chính sách bảo mật ({str(e)}).")
            except ValidationError as e:
                return self.build_response(answer=f"🤔 Không hiểu yêu cầu: Lỗi cú pháp SQL hoặc tham số ({str(e)}).")
            except TimeoutError as e:
                return self.build_response(answer="🐢 Hệ thống đang bận, vui lòng thử lại sau.")
            except Exception as e:
                return self.build_response(answer=f"❌ Lỗi hệ thống: {str(e)}")

            if not rows:
                 return self.build_response(answer="Không tìm thấy ai phù hợp với tiêu chí bạn nêu.")

            lines = []
            for r in rows:
                full_name = r.get('full_name')
                occupation = r.get('occupation')
                phone = r.get('phone')
                lines.append(f"- {full_name} — {occupation} — {phone}")
                
            return self.build_response(answer="Kết quả phù hợp:\n" + "\n".join(lines))

        # 4) GENERAL SQL FALLBACK (New Core Only)
        if settings.ENABLE_NEW_SQL_CORE:
            try:
                tenant_id = getattr(req, "tenant_id", "default")
                trace_id = getattr(req, "trace_id", None) or str(uuid.uuid4())

                gen_result = await self.generator.generate(q)
                sql_query = gen_result.get("sql")
                sql_params = gen_result.get("params", {})
                
                exec_res = await self.executor.execute_safe(sql_query, tenant_id, params=sql_params, trace_id=trace_id)
                rows = exec_res.get("data", [])
                
                if rows:
                    lines = []
                    for r in rows:
                        vals = []
                        for k, v in r.items():
                            if k == 'amount' and isinstance(v, (int, float)):
                                vals.append(f"{k}: {v:,.0f} VNĐ")
                            else:
                                vals.append(f"{k}: {v}")
                        lines.append(" | ".join(vals))
                    
                    return self.build_response(answer="Kết quả dữ liệu:\n" + "\n".join(lines))
                else:
                     return self.build_response(answer="Không tìm thấy dữ liệu phù hợp.")

            except Exception as e:
                logger.warning(f"General SQL Fallback failed: {e}")

        # fallback
        return self.build_response(
            answer="Câu hỏi này có vẻ là dạng giải thích/tài liệu. Bạn hãy dùng agent RAG (citizen/legal)."
        )

    def _render_one(self, payload: Dict[str, Any], field: Optional[str]) -> ChatResponse:
        data: Dict[str, Any] = payload.get("data_content") or {}

        # citations
        cit = payload.get("citation") or {}
        src = (cit.get("source") or {})
        citations = []
        if src.get("source_uri"):
            citations.append(self.make_citation(
                chunk_id=str(payload.get("row_id") or payload.get("chunk_id") or ""),
                file_url=src.get("source_uri"),
                snippet=f"Sheet: {src.get('sheet_name')}, Row: {src.get('row_index')}",
                score=1.0,
            ))

        if field and field in data:
            return self.build_response(answer=f"{data.get('full_name')} — {field}: {data.get(field)}", citations=citations)

        answer = (
            f"Thông tin người:\n"
            f"- Họ tên: {data.get('full_name')}\n"
            f"- Mã: {data.get('code')}\n"
            f"- CCCD: {data.get('cccd')}\n"
            f"- Điện thoại: {data.get('phone')}\n"
            f"- Email: {data.get('email')}\n"
            f"- Địa chỉ: {data.get('address')}\n"
            f"- Đơn vị: {data.get('ward_commune')}\n"
            f"- Chức danh: {data.get('occupation')}\n"
            f"- Ghi chú: {data.get('note')}\n"
        )
        return self.build_response(answer=answer, citations=citations)
