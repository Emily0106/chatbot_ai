from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

class CitizenQAAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="citizen",
        name="Trợ lý Hỏi đáp Công dân",
        description="Giải đáp chung về thủ tục hành chính.",
        doc_types=["citizen_guide", "news"]
    )
    
    policy = AgentPolicy(
        required_clearance=1
    )

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        # Import internal deps
        from app.core.db_sql import get_async_db
        from app.core.rag.pipeline import rag_retrieve
        from app.schemas.chat import RetrievalFilters
        from app.core.llm_client import achat
        from app.core.prompts.templates import build_generation_prompt

        # 1. Prepare Filters
        # Citizen logic: search everything public usually
        filters = ctx.request_payload.get("filters") or {}
        
        # 2. RAG Retrieve
        rag_res = None
        async for db in get_async_db():
            rag_res = await rag_retrieve(
                db=db,
                tenant_id=ctx.tenant_id,
                agent_id=self.metadata.agent_id,
                query=query,
                filters=RetrievalFilters(**filters),
                security_level=ctx.security_level,
                # Tuning: General QA
                top_k=15,
                enable_rerank=True, # Better quality for citizens
                rerank_top_k=8,
                gate_top_n=5,
                user_context={"geo_code": ctx.geo_code, "department_id": ctx.department_id}
            )
            break
            
        if not rag_res:
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "System Error: DB Connection Failed")
             
        # 3. Unwrap
        context = getattr(rag_res, "context", "")
        citations = getattr(rag_res, "citations", [])
        meta = getattr(rag_res, "meta", {})
        
        # 4. Gate Check
        if not context:
             reason = meta.get("reason", "unknown")
             return self._make_refusal(RefusalCode.NO_EVIDENCE, 
                f"Xin lỗi, tôi không tìm thấy thông tin phù hợp quy định. ({reason})")

        # 5. LLM
        gen_prompt = build_generation_prompt(query, case=None, context=context)
        messages = [{"role": "system", "content": gen_prompt}, {"role": "user", "content": query}]
        
        try:
            answer = await achat(messages=messages, temperature=0.3) 
        except Exception as e:
            return self._make_refusal(RefusalCode.NO_EVIDENCE, f"Lỗi tạo câu trả lời: {str(e)}")

        return AgentResponse(
            answer=answer,
            citations=citations,
            meta={**meta, "note": "Citizen RAG Processed"}
        )
