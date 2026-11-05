"""
AGENT TOOL NOTE
- agent_id: agri_agent
- business: Trợ lý Nông nghiệp – Mùa vụ (mùa vụ, thời tiết nông nghiệp, giống/vật tư, sâu bệnh/kỹ thuật, chăn nuôi, thủy sản, báo cáo & thị trường)
- data lanes:
  - RAG: YES (primary, evidence-first)
  - Weather: OPTIONAL (realtime via weather_api wrapper)
  - Web Search: OPTIONAL (market/news via web_search wrapper)
- allowed_doc_types (whitelist):
  ["agri_tech", "agri_season", "agri_pest", "agri_seed", "agri_inputs",
   "agri_livestock", "agri_aquaculture", "agri_market", "agri_stats"]
- tools:
  - rag_retrieve(db, tenant_id, agent_id, query, filters, security_level, ...)
  - weather_api(...)   # optional wrapper, MUST be mocked in Tier-0
  - web_search(...)    # optional wrapper, MUST be mocked in Tier-0
  - achat(messages=...)
- policy:
  - required_clearance: 1
- refusal (fail-closed):
  - if no evidence from all lanes: RefusalCode.NO_EVIDENCE (HTTP 200)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode


class AgriAgent(BaseAgent):
    ALLOWED_DOC_TYPES: List[str] = [
        "agri_tech",
        "agri_season",
        "agri_pest",
        "agri_seed",
        "agri_inputs",
        "agri_livestock",
        "agri_aquaculture",
        "agri_market",
        "agri_stats",
    ]

    metadata = AgentMetadata(
        agent_id="agri_agent",
        name="Trợ lý Nông nghiệp – Mùa vụ",
        description="Hỗ trợ mùa vụ, kỹ thuật, giống/vật tư, sâu bệnh, chăn nuôi, thủy sản, và thị trường dựa trên evidence.",
        doc_types=ALLOWED_DOC_TYPES,
    )

    policy = AgentPolicy(required_clearance=1)

    # -----------------------------
    # Zero-trust filters
    # -----------------------------
    def _sanitize_user_filters(self, raw_filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        User có thể gửi filters nhưng doc_types phải bị giới hạn theo allowlist của agent.
        Không cho override tenant/scope/security/agent_id.
        """
        safe = dict(raw_filters or {})

        user_doc_types = safe.get("doc_types") or safe.get("doc_type")
        if user_doc_types:
            if isinstance(user_doc_types, str):
                user_doc_types = [user_doc_types]
            if isinstance(user_doc_types, list):
                filtered = [dt for dt in user_doc_types if dt in self.ALLOWED_DOC_TYPES]
                safe["doc_types"] = filtered if filtered else self.ALLOWED_DOC_TYPES
            else:
                safe["doc_types"] = self.ALLOWED_DOC_TYPES
        else:
            safe["doc_types"] = self.ALLOWED_DOC_TYPES

        for k in ["tenant_id", "scope", "security_level", "agent_id"]:
            safe.pop(k, None)

        return safe

    # -----------------------------
    # In-agent capability routing
    # -----------------------------
    def _detect_capabilities(self, query: str) -> Dict[str, bool]:
        """
        Không chọn agent nào; chỉ chọn LANE nào trong agent: RAG / WEATHER / WEB.
        """
        q = (query or "").lower()

        need_weather = any(k in q for k in [
            "thời tiết", "dự báo", "mưa", "nắng", "rét", "bão", "áp thấp", "lũ", "hạn",
            "nhiệt độ", "độ ẩm", "gió", "sương", "xâm nhập mặn"
        ])

        need_market = any(k in q for k in [
            "giá", "thị trường", "đầu ra", "xu hướng", "tăng", "giảm", "bản tin",
            "giá lúa", "giá heo", "giá gà", "giá cá", "giá tôm", "giá phân", "giá giống"
        ])

        # RAG là lane chính; nhưng có thể giảm tải trong trường hợp hỏi "thuần thời tiết"
        # vẫn để True mặc định để đảm bảo evidence từ tài liệu hướng dẫn tác động/khuyến cáo.
        need_rag = True

        return {"rag": need_rag, "weather": need_weather, "web": need_market}

    def _load_optional_tools(self):
        """
        Offline-first: nếu tool chưa tồn tại, agent vẫn chạy được (fail-closed nếu thiếu evidence).
        """
        weather_api = None
        web_search = None

        try:
            from app.core.tools.weather import weather_api as _weather_api  # type: ignore
            weather_api = _weather_api
        except Exception:
            weather_api = None

        try:
            from app.core.tools.web import web_search as _web_search  # type: ignore
            web_search = _web_search
        except Exception:
            web_search = None

        return weather_api, web_search

    def _format_weather_context(self, payload: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
        """
        payload kỳ vọng có thể chứa: location, updated_at/timestamp, summary/forecast_summary, source_url
        """
        location = payload.get("location") or "khu vực yêu cầu"
        updated_at = payload.get("updated_at") or payload.get("timestamp") or ""
        summary = payload.get("summary") or payload.get("forecast_summary") or ""

        text = (
            "[WEATHER_API]\n"
            f"Khu vực: {location}\n"
            f"Thời điểm: {updated_at}\n"
            f"Tóm tắt: {summary}\n"
        ).strip()

        citations = [{
            "chunk_id": "weather-api",
            "title": "Weather API",
            "source_url": payload.get("source_url") or "weather_api://local",
            "page_number": None,
            "snippet": (summary or str(payload))[:500],
        }]
        return text, citations

    def _format_web_context(self, results: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        lines = []
        citations: List[Dict[str, Any]] = []
        for r in (results or [])[:5]:
            title = r.get("title") or "Kết quả web"
            url = r.get("url") or r.get("source_url") or ""
            snippet = r.get("snippet") or ""
            lines.append(f"- {title}: {snippet}")
            citations.append({
                "chunk_id": "web-search",
                "title": r.get("title"),
                "source_url": url,
                "page_number": None,
                "snippet": (r.get("snippet") or "")[:500],
            })
        text = "[WEB_SEARCH]\n" + "\n".join(lines)
        return text.strip(), citations

    # -----------------------------
    # Main
    # -----------------------------
    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        # Enforce policy (nếu BaseAgent có _enforce_policy)
        try:
            if hasattr(self, "_enforce_policy"):
                self._enforce_policy(ctx)  # type: ignore
        except Exception:
            return self._make_refusal(
                RefusalCode.INSUFFICIENT_CLEARANCE,
                "Bạn không đủ quyền để sử dụng trợ lý này.",
            )

        capabilities = self._detect_capabilities(query)
        weather_api, web_search = self._load_optional_tools()

        # Core wrappers
        from app.core.db_sql import get_async_db
        from app.core.rag.pipeline import rag_retrieve
        from app.schemas.chat import RetrievalFilters
        from app.core.llm_client import achat
        from app.core.prompts.agri_templates import build_agri_generation_prompt

        # User filters (zero-trust sanitize)
        raw_filters = {}
        if hasattr(ctx, "request_payload") and isinstance(getattr(ctx, "request_payload"), dict):
            raw_filters = ctx.request_payload.get("filters", {}) or {}
        safe_filters = self._sanitize_user_filters(raw_filters)

        # -----------------
        # Lane: RAG (primary)
        # -----------------
        rag_context = ""
        rag_citations: List[Dict[str, Any]] = []
        rag_meta: Dict[str, Any] = {}
        rag_ok = False

        if capabilities["rag"]:
            rag_res = None
            try:
                async for db in get_async_db():
                    rag_res = await rag_retrieve(
                        db=db,
                        tenant_id=ctx.tenant_id,
                        agent_id=self.metadata.agent_id,
                        query=query,
                        filters=RetrievalFilters(**safe_filters),
                        security_level=ctx.security_level,
                        top_k=20,
                        enable_rerank=True,
                        user_context={
                            "geo_code": getattr(ctx, "geo_code", None),
                            "department_id": getattr(ctx, "department_id", None),
                        },
                    )
                    break
            except Exception:
                rag_res = None

            if rag_res:
                rag_context = (getattr(rag_res, "context", "") or "").strip()
                rag_citations = getattr(rag_res, "citations", []) or []
                rag_meta = getattr(rag_res, "meta", {}) or {}
                rag_ok = bool(rag_context)

        # -----------------
        # Lane: Weather (optional)
        # -----------------
        weather_context = ""
        weather_citations: List[Dict[str, Any]] = []
        weather_ok = False
        if capabilities["weather"]:
            geo_code = getattr(ctx, "geo_code", None)
            if weather_api and geo_code:
                try:
                    payload = await weather_api(geo_code=geo_code, days=7)  # signature gợi ý, test sẽ mock
                    if isinstance(payload, dict) and payload:
                        weather_context, weather_citations = self._format_weather_context(payload)
                        weather_ok = bool(weather_context)
                except Exception:
                    weather_ok = False

        # -----------------
        # Lane: Web Search (optional)
        # -----------------
        web_context = ""
        web_citations: List[Dict[str, Any]] = []
        web_ok = False
        if capabilities["web"]:
            if web_search:
                try:
                    area = getattr(ctx, "geo_code", None) or getattr(ctx, "department_id", None) or ""
                    q_web = f"{query} {area}".strip()
                    results = await web_search(q_web, num_results=5)  # test sẽ mock list[dict]
                    if isinstance(results, list) and results:
                        web_context, web_citations = self._format_web_context(results)
                        web_ok = bool(web_context)
                except Exception:
                    web_ok = False

        # -----------------
        # Evidence aggregation (fail-closed)
        # -----------------
        context_parts: List[str] = []
        if rag_ok:
            context_parts.append(rag_context)
        if weather_ok:
            context_parts.append(weather_context)
        if web_ok:
            context_parts.append(web_context)

        combined_context = "\n\n".join([p for p in context_parts if p]).strip()

        if not combined_context:
            return self._make_refusal(
                RefusalCode.NO_EVIDENCE,
                "Không tìm thấy dữ liệu/chứng cứ phù hợp để trả lời (tài liệu hoặc nguồn thời tiết/giá chưa sẵn sàng).",
            )

        # -----------------
        # LLM generation (evidence-only)
        # -----------------
        gen_prompt = build_agri_generation_prompt(query, case=None, context=combined_context)
        messages = [
            {"role": "system", "content": gen_prompt},
            {"role": "user", "content": query},
        ]

        try:
            answer = await achat(messages=messages, temperature=0.3)
        except Exception as e:
            return self._make_refusal(RefusalCode.NO_EVIDENCE, f"Error: {str(e)}")

        citations = (rag_citations or []) + (weather_citations or []) + (web_citations or [])
        meta = {
            **(rag_meta or {}),
            "filters_used": safe_filters,
            "capabilities": capabilities,
            "tools_used": [k for k, v in [("rag", rag_ok), ("weather_api", weather_ok), ("web_search", web_ok)] if v],
        }

        return AgentResponse(
            answer=answer,
            citations=citations,
            meta=meta,
        )
