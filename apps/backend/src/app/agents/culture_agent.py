"""
AGENT TOOL NOTE
- agent_id: culture_agent
- business: Văn hoá - Du lịch - Sự kiện
- data lane:
  - RAG: YES
  - allowed_doc_types: ["culture_guide", "tourism_spots"]
- tools (implemented now):
  - rag_retrieve(ctx, query, filters={"doc_type": ...})
- tools (TODO for dev):
  - web_search(ctx, query)
  - weather_api()
- policy:
  - scope: public
- refusal:
  - if no evidence: return refusal NO_EVIDENCE (HTTP 200)
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

class CultureAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="culture_agent",
        name="Trợ lý Văn hoá & Du lịch",
        description="Hướng dẫn du lịch, địa điểm văn hoá và sự kiện.",
        doc_types=["culture_guide", "tourism_spots"]
    )
    
    policy = AgentPolicy(
        required_clearance=1
    )

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        from app.core.db_sql import get_async_db
        from app.core.rag.pipeline import rag_retrieve
        from app.schemas.chat import RetrievalFilters
        from app.core.llm_client import achat
        from app.core.prompts.templates import build_generation_prompt

        filters = ctx.request_payload.get("filters", {})
        
        rag_res = None
        async for db in get_async_db():
            rag_res = await rag_retrieve(
                db=db,
                tenant_id=ctx.tenant_id,
                agent_id=self.metadata.agent_id,
                query=query,
                filters=RetrievalFilters(**filters),
                security_level=ctx.security_level, 
                top_k=20,
                enable_rerank=True,
                user_context={"geo_code": ctx.geo_code, "department_id": ctx.department_id}
            )
            break
            
        if not rag_res:
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "System info unavailable.")

        context = getattr(rag_res, "context", "")
        citations = getattr(rag_res, "citations", [])
        meta = getattr(rag_res, "meta", {})
        
        if not context:
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "Không tìm thấy thông tin văn hoá/du lịch phù hợp.")

        gen_prompt = build_generation_prompt(query, case=None, context=context)
        messages = [{"role": "system", "content": gen_prompt}, {"role": "user", "content": query}]
        
        try:
            answer = await achat(messages=messages, temperature=0.7) # Higher temp for creative/tourism
        except Exception as e:
            return self._make_refusal(RefusalCode.NO_EVIDENCE, f"Error: {str(e)}")

        return AgentResponse(
            answer=answer,
            citations=citations,
            meta=meta
        )
