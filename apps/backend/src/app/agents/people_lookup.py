from __future__ import annotations

import os
import re
import unicodedata
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse
from app.schemas.chat import ChatRequest, ChatResponse

# -------------------------
# Normalize helpers
# -------------------------
_SPACES = re.compile(r"\s+", re.UNICODE)

def nfc_lower(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = s.strip().lower()
    s = _SPACES.sub(" ", s)
    return s

def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", s)

def normalize_ascii(s: str) -> str:
    return nfc_lower(strip_accents(s))


# -------------------------
# Field hints (FIX "địa chính" vs "địa chỉ")
# -------------------------
_FIELD_PATTERNS = {
    "cccd": [re.compile(r"\b(cccd|can cuoc|căn cước|so cccd|số cccd)\b", re.I)],
    "phone": [re.compile(r"\b(dien thoai|điện thoại|sdt|so dt|số dt|phone)\b", re.I)],
    "email": [re.compile(r"\b(email|mail)\b", re.I)],
    # match exact phrase "địa chỉ" only (avoid "địa chính")
    "address": [re.compile(r"\b(dia\s+chi|địa\s+chỉ)\b", re.I)],
    "occupation": [re.compile(r"\b(phu trach|phụ trách|linh vuc|lĩnh vực|chuc danh|chức danh|bo phan|bộ phận|địa chính|dia chinh|xây dựng|xay dung|tiêm chủng|tiem chung)\b", re.I)],
}

def _guess_field(question: str) -> Optional[str]:
    q = normalize_ascii(question)
    for field, pats in _FIELD_PATTERNS.items():
        if any(p.search(q) for p in pats):
            return field
    return None


# -------------------------
# Embedding providers
# NOTE: MUST MATCH ingestion vectors dimension.
# Choose via env PEOPLE_EMBED_PROVIDER=local|openai
# -------------------------
_ST_MODEL = None

def _local_embed_one(text: str, model_name: str = "all-MiniLM-L6-v2") -> List[float]:
    global _ST_MODEL
    from sentence_transformers import SentenceTransformer
    if _ST_MODEL is None:
        _ST_MODEL = SentenceTransformer(model_name)
    return _ST_MODEL.encode(text).tolist()

def _openai_embed_one(text: str, *, api_key: str, model: str) -> List[float]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    resp = client.embeddings.create(model=model, input=[text])
    return resp.data[0].embedding


# -------------------------
# Entity resolver (exact match first)
# -------------------------
_CODE_RE = re.compile(r"\b(nguoi|người|cua|của)\s*([abc])\b", re.I)

def _extract_code(question: str) -> Optional[str]:
    q = normalize_ascii(question)
    m = _CODE_RE.search(q)
    if m:
        return m.group(2).upper()
    return None

def _extract_name_ascii_hint(question: str) -> Optional[str]:
    """
    Demo-focused: detect A/B/C by name (bỏ dấu).
    Có thể mở rộng sau bằng NER.
    """
    q = normalize_ascii(question)
    for name_ascii in ["nguyen van a", "tran thi b", "le van c"]:
        if name_ascii in q:
            return name_ascii
    return None


class PeopleLookupAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="people_lookup",
        name="People Lookup Agent",
        description="Tra cứu thông tin người (demo A/B/C) từ Qdrant payload.",
        doc_types=["vectors"]
    )
    
    policy = AgentPolicy(
        required_clearance=2,
        required_scopes=["people:read"]
    )
    
    def __init__(self) -> None:
        super().__init__()
        self.qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        self.collection_name = os.getenv("QDRANT_COLLECTION_PEOPLE", "people_demo")

        # IMPORTANT: embedding must match ingestion vectors
        self.embed_provider = os.getenv("PEOPLE_EMBED_PROVIDER", "local").strip().lower()  # local|openai
        self.local_model_name = os.getenv("PEOPLE_LOCAL_EMBED_MODEL", "all-MiniLM-L6-v2")

        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_embed_model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

        self.min_score = float(os.getenv("PEOPLE_MIN_SCORE", "0.65"))

        if self.embed_provider == "openai" and not self.openai_api_key:
            self.logger.warning("PEOPLE_EMBED_PROVIDER=openai but OPENAI_API_KEY missing; fallback to local")
            self.embed_provider = "local"

        self.client = QdrantClient(url=self.qdrant_url)

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        # Reconstruct ChatRequest for Legacy Logic fallback
        req = ChatRequest(
            **ctx.request_payload
        )
        req.message = query # ensure query is sync
        
        return await self._process_legacy(req)

    async def _process_legacy(self, req: ChatRequest) -> ChatResponse:
        question = getattr(req, "message", None) or getattr(req, "query", "") or ""
        top_k = self.resolved_top_k(req)
        field = _guess_field(question)

        # ---- 1) EXACT match stage (code/name) ----
        code = _extract_code(question)
        name_ascii = _extract_name_ascii_hint(question)

        # build should filters
        must = [qmodels.FieldCondition(key="entity_type", match=qmodels.MatchValue(value="person"))]
        should = []
        if code:
            should.append(qmodels.FieldCondition(key="code", match=qmodels.MatchValue(value=code)))
            should.append(qmodels.FieldCondition(key="data_content.code", match=qmodels.MatchValue(value=code)))
        if name_ascii:
            should.append(qmodels.FieldCondition(key="name_ascii", match=qmodels.MatchValue(value=name_ascii)))

        if should:
            flt = qmodels.Filter(must=must, should=should)
            pts, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=flt,
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if pts:
                return self._render_answer(
                    question=question,
                    payload=pts[0].payload or {},
                    point_id=str(pts[0].id),
                    score=1.0,
                    field=field,
                )

        # ---- 2) Vector fallback ----
        if self.embed_provider == "openai":
            vec = _openai_embed_one(question, api_key=self.openai_api_key, model=self.openai_embed_model)
        else:
            vec = _local_embed_one(question, model_name=self.local_model_name)

        flt = qmodels.Filter(
            must=[qmodels.FieldCondition(key="entity_type", match=qmodels.MatchValue(value="person"))]
        )

        hits = self.client.query_points(
            collection_name=self.collection_name,
            query=vec,
            limit=top_k,
            query_filter=flt,
            with_payload=True,
        ).points

        if not hits:
            return self.build_response(answer="Không tìm thấy thông tin phù hợp trong dữ liệu demo.")

        best = hits[0]
        best_payload: Dict[str, Any] = best.payload or {}

        # ---- 3) Low confidence guard ----
        best_score = float(getattr(best, "score", 0.0) or 0.0)
        if best_score < self.min_score:
            # suggest top 3
            opts = []
            for h in hits[:3]:
                d = (h.payload or {}).get("data_content") or {}
                opts.append(f"- {d.get('full_name')} (mã {d.get('code')})")
            answer = (
                "Mình chưa chắc bạn đang hỏi người nào (kết quả mơ hồ).\n"
                "Bạn muốn tra cứu ai?\n"
                + "\n".join(opts)
                + "\n\nGợi ý: gõ rõ 'người A' / 'người B' / 'người C' hoặc họ tên đầy đủ."
            )
            # attach best citation for debug
            return self._render_answer(
                question=question,
                payload=best_payload,
                point_id=str(best.id),
                score=best_score,
                field=None,
                override_answer=answer,
            )

        return self._render_answer(
            question=question,
            payload=best_payload,
            point_id=str(best.id),
            score=best_score,
            field=field,
            hits=hits,
        )

    def _read_citation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Support both:
        - nested: payload["citation"]["source"]["sheet_name"]
        - flat: payload["sheet_name"], payload["row_start"]
        """
        # nested
        cit = payload.get("citation") or {}
        if isinstance(cit, dict):
            src = cit.get("source") or {}
            if isinstance(src, dict) and (src.get("source_uri") or src.get("sheet_name") or src.get("row_index")):
                return {
                    "source_uri": src.get("source_uri"),
                    "sheet_name": src.get("sheet_name"),
                    "row_index": src.get("row_index"),
                }

        # flat fallback
        return {
            "source_uri": payload.get("source_uri"),
            "sheet_name": payload.get("sheet_name"),
            "row_index": payload.get("row_start") or payload.get("row_end"),
        }

    def _render_answer(
        self,
        *,
        question: str,
        payload: Dict[str, Any],
        point_id: str,
        score: float,
        field: Optional[str],
        override_answer: Optional[str] = None,
        hits: Optional[List[Any]] = None,
    ) -> ChatResponse:
        data: Dict[str, Any] = payload.get("data_content") or {}

        cit = self._read_citation(payload)
        citations = []
        if cit.get("source_uri"):
            citations.append(
                self.make_citation(
                    chunk_id=point_id,
                    file_url=cit.get("source_uri"),
                    snippet=f"Sheet: {cit.get('sheet_name')}, Row: {cit.get('row_index')}",
                    score=score,
                )
            )

        if override_answer:
            return self.build_response(answer=override_answer, citations=citations)

        # Nếu hỏi kiểu “ai phụ trách …” -> liệt kê top hits
        q_lower = normalize_ascii(question)
        if "ai" in q_lower and ("phu trach" in q_lower or "phụ trách" in q_lower):
            lines = []
            if hits:
                for h in hits[: min(5, len(hits))]:
                    d = (h.payload or {}).get("data_content") or {}
                    lines.append(f"- {d.get('full_name')} — {d.get('occupation')} — {d.get('phone')}")
            else:
                lines.append(f"- {data.get('full_name')} — {data.get('occupation')} — {data.get('phone')}")
            answer = "Kết quả phù hợp:\n" + "\n".join(lines)
            return self.build_response(answer=answer, citations=citations)

        # Trả theo field nếu user hỏi rõ
        if field and field in data:
            answer = f"{data.get('full_name','(không rõ tên)')} — {field}: {data.get(field)}"
            return self.build_response(answer=answer, citations=citations)

        # Default card
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
