"""
AGENT TOOL NOTE
- agent_id: health_agent
- business: Tư vấn y tế công cộng, dịch bệnh
- data lane:
  - RAG: YES
  - allowed_doc_types: ["health_guidelines", "disease_info"]
- tools (implemented now):
  - rag_retrieve(ctx, query, filters={"doc_type": ...})
- tools (TODO for dev):
  - warning_alert_system()
  - sql_epidemic_report()
- policy:
  - scope: public
- refusal:
  - if no evidence: return refusal NO_EVIDENCE (HTTP 200)
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

class HealthAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="health_agent",
        name="Trợ lý Y tế",
        description="Thông tin y tế công cộng và phòng chống dịch bệnh.",
        doc_types=["health_guidelines", "disease_info"]
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
                top_k=15,
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
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "Không tìm thấy hướng dẫn y tế liên quan.")

        gen_prompt = build_generation_prompt(query, case=None, context=context)
        messages = [{"role": "system", "content": gen_prompt}, {"role": "user", "content": query}]
        
        try:
            answer = await achat(messages=messages, temperature=0.2)
        except Exception as e:
            return self._make_refusal(RefusalCode.NO_EVIDENCE, f"Error: {str(e)}")

        return AgentResponse(
            answer=answer,
            citations=citations,
            meta=meta
        )
