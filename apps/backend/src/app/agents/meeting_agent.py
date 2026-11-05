"""
AGENT TOOL NOTE
- agent_id: meeting_agent
- business: Tra cứu biên bản họp, trích xuất nhiệm vụ/kết luận
- data lane:
  - RAG: YES
  - allowed_doc_types: ["meeting_minutes"]
- tools (implemented now):
  - rag_retrieve(ctx, query, filters={"doc_type": ...})
- tools (TODO for dev):
  - extract_tasks(meeting_content)
  - summarize_decisions(meeting_content)
- policy:
  - scope: internal
- refusal:
  - if no evidence: return refusal NO_EVIDENCE (HTTP 200)
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

class MeetingAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="meeting_agent",
        name="Trợ lý Cuộc họp",
        description="Tra cứu biên bản họp và kết luận chỉ đạo.",
        doc_types=["meeting_minutes"]
    )
    
    policy = AgentPolicy(
        required_clearance=1 # Internal usually
    )

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        from app.core.db_sql import get_async_db
        from app.core.rag.pipeline import rag_retrieve
        from app.schemas.chat import RetrievalFilters
        from app.core.llm_client import achat
        from app.core.prompts.templates import build_generation_prompt

        # Filters
        filters = ctx.request_payload.get("filters", {})
        filters["doc_types"] = self.metadata.doc_types 
        
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
                top_k=15,
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
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "Không tìm thấy biên bản họp phù hợp.")

        # LLM
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
