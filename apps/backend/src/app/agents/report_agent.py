"""
AGENT TOOL NOTE
- agent_id: report_agent
- business: Hỗ trợ lập báo cáo nội bộ, thống kê
- data lane:
  - RAG: YES
  - allowed_doc_types: ["internal_report", "stats"]
- tools (implemented now):
  - rag_retrieve(ctx, query, filters={"doc_type": ...})
- tools (TODO for dev):
  - formatting output (tables/charts)
  - export_to_pdf/excel
- policy:
  - scope: internal
  - requires_clearance: >= 2
- refusal:
  - if no evidence: return refusal NO_EVIDENCE (HTTP 200)
  - if out_of_scope doc_type: OUT_OF_SCOPE
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

class ReportAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="report_agent",
        name="Trợ lý Báo cáo",
        description="Hỗ trợ tổng hợp báo cáo và số liệu thống kê.",
        doc_types=["internal_report", "stats"]
    )
    
    policy = AgentPolicy(
        required_clearance=2 # Internal only
    )

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        from app.core.db_sql import get_async_db
        from app.core.rag.pipeline import rag_retrieve
        from app.schemas.chat import RetrievalFilters
        from app.core.llm_client import achat
        from app.core.prompts.templates import build_generation_prompt

        filters = ctx.request_payload.get("filters", {})
        
        # RAG
        rag_res = None
        async for db in get_async_db():
            rag_res = await rag_retrieve(
                db=db,
                tenant_id=ctx.tenant_id,
                agent_id=self.metadata.agent_id,
                query=query,
                filters=RetrievalFilters(**filters),
                security_level=ctx.security_level, 
                top_k=30, # Reports need more context
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
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "Không tìm thấy dữ liệu báo cáo phù hợp.")

        # LLM
        gen_prompt = build_generation_prompt(query, case=None, context=context)
        messages = [{"role": "system", "content": gen_prompt}, {"role": "user", "content": query}]
        
        try:
            answer = await achat(messages=messages, temperature=0.1) # Strict for reports
        except Exception as e:
            return self._make_refusal(RefusalCode.NO_EVIDENCE, f"Error: {str(e)}")

        return AgentResponse(
            answer=answer,
            citations=citations,
            meta=meta
        )
