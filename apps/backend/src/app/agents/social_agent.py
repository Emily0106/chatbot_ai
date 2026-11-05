"""
AGENT TOOL NOTE
- agent_id: social_agent
- business: Chính sách xã hội, người có công, bảo trợ
- data lane:
  - RAG: YES
  - SQL: TODO (Beneficiary lookup)
  - allowed_doc_types: ["social_policy"]
- tools (implemented now):
  - rag_retrieve(ctx, query, filters=...)
- tools (TODO for dev):
  - sql_beneficiary_check(id_card)
- policy:
  - scope: restricted
  - requires_clearance: 2
  - requires_department_match: true
- refusal:
  - if no evidence: return refusal NO_EVIDENCE
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

class SocialAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="social_agent",
        name="Trợ lý Xã hội",
        description="Chính sách bảo trợ và người có công.",
        doc_types=["social_policy"]
    )
    
    policy = AgentPolicy(
        required_clearance=2,
        requires_department_match=True,
        required_context_fields=["department_id"]
    )

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        from app.core.db_sql import get_async_db
        from app.core.rag.pipeline import rag_retrieve
        from app.schemas.chat import RetrievalFilters
        from app.core.llm_client import achat
        from app.core.prompts.templates import build_generation_prompt

        filters = ctx.request_payload.get("filters", {})
        filters["doc_types"] = self.metadata.doc_types
        
        user_context = {}
        if self.policy.requires_department_match and ctx.department_id:
            user_context["department_id"] = ctx.department_id

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
                user_context=user_context
            )
            break
            
        if not rag_res:
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "System info unavailable.")

        context = getattr(rag_res, "context", "")
        citations = getattr(rag_res, "citations", [])
        meta = getattr(rag_res, "meta", {})
        
        if not context:
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "Không tìm thấy chính sách xã hội liên quan.")

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
