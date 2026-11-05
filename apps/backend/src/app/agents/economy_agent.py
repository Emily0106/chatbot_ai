"""
AGENT TOOL NOTE
- agent_id: economy_agent
- business: Báo cáo chỉ tiêu kinh tế - xã hội
- data lane:
  - RAG: YES (Narrative reports)
  - SQL: TODO (Structured Stats)
  - allowed_doc_types: ["stats", "internal_report"]
- tools (implemented now):
  - rag_retrieve(ctx, query, filters=...)
- tools (TODO for dev):
  - sql_execute_safe(template_id="econ_kpi_query", params={...})
- policy:
  - scope: internal
  - requires_clearance: 2
- refusal:
  - if no evidence: return refusal NO_EVIDENCE
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

class EconomyAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="economy_agent",
        name="Trợ lý Kinh tế",
        description="Tra cứu chỉ tiêu và báo cáo kinh tế.",
        doc_types=["stats", "internal_report"]
    )
    
    policy = AgentPolicy(
        required_clearance=2
    )

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        from app.core.db_sql import get_async_db
        from app.core.rag.pipeline import rag_retrieve
        from app.schemas.chat import RetrievalFilters
        from app.core.llm_client import achat
        from app.core.prompts.templates import build_generation_prompt

        # TODO(dev): Detect if SQL is needed for specific stats
        # if is_statistic_query(query):
        #      return await self.handle_sql(ctx, query)
        
        # Default: RAG loop
        filters = ctx.request_payload.get("filters", {})
        filters["doc_types"] = self.metadata.doc_types
        
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
                user_context={"department_id": ctx.department_id}
            )
            break
            
        if not rag_res:
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "System info unavailable.")

        context = getattr(rag_res, "context", "")
        citations = getattr(rag_res, "citations", [])
        meta = getattr(rag_res, "meta", {})
        
        if not context:
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "Không tìm thấy báo cáo kinh tế phù hợp.")

        gen_prompt = build_generation_prompt(query, case=None, context=context)
        messages = [{"role": "system", "content": gen_prompt}, {"role": "user", "content": query}]
        
        try:
            answer = await achat(messages=messages, temperature=0.1)
        except Exception as e:
            return self._make_refusal(RefusalCode.NO_EVIDENCE, f"Error: {str(e)}")

        return AgentResponse(
            answer=answer,
            citations=citations,
            meta=meta
        )
