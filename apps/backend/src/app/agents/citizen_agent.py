"""
AGENT TOOL NOTE
- agent_id: citizen_agent
- business: Hỏi đáp đa lĩnh vực + pháp luật + thủ tục
- data lane:
  - RAG: YES
  - allowed_doc_types: ["law", "admin_procedure", "citizen_guide"]
- tools (implemented now):
  - rag_retrieve(ctx, query, filters=...)
  - web_search(ctx, query) [Implemented]
- policy:
  - scope: public
  - requires_geo_match: true
- refusal:
  - if no evidence: return refusal NO_EVIDENCE
"""
from __future__ import annotations
import logging # [PROFESSIONAL] Dùng logging thay vì print
import uuid 

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

# [TIP] Logger nên khai báo ở cấp module
logger = logging.getLogger(__name__)

class CitizenAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="citizen_agent",
        name="Trợ lý Công dân",
        description="Hỗ trợ công dân tra cứu thủ tục, pháp luật, biểu mẫu và đời sống.",
        doc_types=["law", "admin_procedure", "citizen_guide"]
    )
    
    policy = AgentPolicy(
        required_clearance=0, # Public
        required_context_fields=["geo_code"]
    )

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        # Import bên trong để tránh circular dependency (Chuẩn Zero-Trust Framework)
        from app.core.db_sql import get_async_db # [FIX] Needed for DB session
        from app.core.rag.pipeline import rag_retrieve
        from app.schemas.chat import RetrievalFilters, Citation
        from app.core.llm_client import achat
        from app.core.prompts.templates import build_generation_prompt
        from app.core.web_search import WebSearchService

        # 1. SECURITY FILTER (Quan trọng)
        req_filters = ctx.request_payload.get("filters", {}).copy()
        if "doc_types" in req_filters:
            del req_filters["doc_types"]
        
        # 2. RAG RETRIEVE
        rag_res = None
        try:
            # [FIX] Use get_async_db to ensure db session is available
            async for db in get_async_db():
                rag_res = await rag_retrieve(
                    db=db, 
                    tenant_id=ctx.tenant_id,
                    agent_id=self.metadata.agent_id,
                    query=query,
                    filters=RetrievalFilters(doc_types=self.metadata.doc_types, **req_filters),
                    security_level=ctx.security_level,
                    top_k=10,
                    enable_rerank=True,
                    user_context={"geo_code": ctx.geo_code, "department_id": ctx.department_id}
                )
                break # Only need one session
        except Exception as e:
            logger.error(f"[CitizenAgent] RAG Retrieval failed: {e}")
            rag_res = None

        context = getattr(rag_res, "context", "") or ""
        citations = getattr(rag_res, "citations", []) or []
        meta = getattr(rag_res, "meta", {})
        
        # 3. WEB SEARCH FALLBACK
        if len(context) < 100:
            try:
                # Helper function to mimic function call from class method
                async def web_search_helper(q, num):
                    svc = WebSearchService()
                    return await svc.search(q)

                web_results = await web_search_helper(query, num=3)
                
                if web_results:
                    web_context_str = "\n".join([f"- [{getattr(r, 'title', 'Link')}]({getattr(r, 'link', '#')}): {getattr(r, 'snippet', '')}" for r in web_results])
                    context += f"\n\n=== THÔNG TIN TỪ INTERNET (Tham khảo) ===\n{web_context_str}"
                    
                    for r in web_results:
                        try:
                            cid = f"web_{uuid.uuid4().hex[:8]}"
                            cit = Citation(
                                chunk_id=cid,
                                title=getattr(r, 'title', 'Web Search'),
                                file_url=getattr(r, 'link', '#'),
                                snippet=getattr(r, 'snippet', ''),
                                score=0.5
                            )
                            citations.append(cit)
                        except Exception as e:
                            logger.warning(f"[CitizenAgent] Failed to create citation object: {e}")

            except Exception as e:
                logger.warning(f"[CitizenAgent] Web search failed for query '{query}': {e}")

        # 4. FAIL-CLOSED GATE
        if not context.strip():
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "Xin lỗi, tôi không tìm thấy thông tin phù hợp trong hệ thống văn bản và Internet.")

        # 5. TEMPLATE DETECTION & PROMPT ENGINEERING
        from app.core.prompts.prompts_citizen import build_citizen_prompt
        
        is_asking_form = any(kw in query.lower() for kw in ["mẫu", "đơn", "tờ khai", "hồ sơ", "form", "tải về", "bản khai"])
        
        system_instruction = ""
        if is_asking_form:
            system_instruction = (
                "\n\n[CHỈ DẪN QUAN TRỌNG]: Người dùng đang tìm mẫu văn bản/tờ khai. "
                "Hãy trích xuất TÊN MẪU (ví dụ: Mẫu 01/ĐK) và ĐƯỜNG DẪN TẢI (nếu có) lên đầu câu trả lời."
            )

        # 6. LLM GENERATION
        base_prompt = build_citizen_prompt(context, query)
        final_system_prompt = base_prompt + system_instruction

        messages = [{"role": "system", "content": final_system_prompt}, {"role": "user", "content": query}]
        
        try:
            answer = await achat(messages=messages, temperature=0.3)
        except Exception as e:
            logger.error(f"[CitizenAgent] LLM generation error: {e}")
            return self._make_refusal(RefusalCode.NO_EVIDENCE, "Đã xảy ra lỗi trong quá trình tổng hợp câu trả lời.")

        return AgentResponse(answer=answer, citations=citations, meta=meta)
