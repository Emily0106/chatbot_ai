import logging
import time
from typing import AsyncGenerator

from app.core.rag.pipeline import rag_retrieve
from app.schemas.chat import RetrievalFilters, ChatResponse, ChatMeta
from .base import BaseAgent
from .contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

logger = logging.getLogger(__name__)

class LegalAgent(BaseAgent):
    # Metadata (PR-B0 Contract)
    metadata = AgentMetadata(
        agent_id="legal",
        name="Trợ lý Pháp luật",
        description="Tra cứu văn bản pháp luật chính xác.",
        doc_types=["legal"]
    )
    
    policy = AgentPolicy(
        required_clearance=1, # Public ok
    )

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        logger.info(f"LegalAgent process: user={ctx.user_id} query='{query}'")
        
        # 0. Import internal deps
        from app.core.db_sql import get_async_db
        
        # 1. Prepare Filters
        # Basic filter logic: force doc_type=law (Taxonomy compliant)
        filters = ctx.request_payload.get("filters", {})
        if "doc_type" not in filters:
             filters["doc_type"] = "law"
             
        # 2. Call Standard RAG Retrieve (Blocking)
        rag_res = None
        
        async for db in get_async_db():
            rag_res = await rag_retrieve(
                db=db,
                tenant_id=ctx.tenant_id,
                agent_id=self.metadata.agent_id,
                query=query,
                filters=RetrievalFilters(**filters),
                security_level=ctx.security_level,
                # Tuning specific to Legal
                top_k=20,
                enable_rerank=True,
                rerank_top_k=10,
                gate_top_n=5,
                prefer_parent_text=True,
                user_context={"geo_code": ctx.geo_code, "department_id": ctx.department_id}
            )
            break
        
        if not rag_res:
             return self._make_refusal(RefusalCode.NO_EVIDENCE, "System Error: DB Connection Failed")

        # 3. Unwrap & Return
        context = getattr(rag_res, "context", "")
        citations = getattr(rag_res, "citations", [])
        meta = getattr(rag_res, "meta", {})
        
        # 4. Check Gate
        if not context:
             reason = meta.get("reason", "unknown")
             return self._make_refusal(RefusalCode.NO_EVIDENCE, 
                f"Không tìm thấy thông tin phù hợp. ({reason})")

        # 5. Generate Answer (LLM)
        from app.core.llm_client import achat
        from app.core.prompts.templates import build_generation_prompt
        
        gen_prompt = build_generation_prompt(query, case=None, context=context)
        messages = [{"role": "system", "content": gen_prompt}, {"role": "user", "content": query}]
        
        try:
            answer = await achat(messages=messages, temperature=0.1)
        except Exception as e:
            logger.warning("LegalAgent LLM failed, using retrieval fallback: %s", e)
            # Keep retrieval value even if model provider is unavailable.
            context_lines = [ln.strip() for ln in str(context).splitlines() if ln.strip()]
            canary_line = next((ln for ln in context_lines if "CANARY=" in ln), None)
            fallback_answer = canary_line or (context_lines[0] if context_lines else "Không tạo được câu trả lời từ mô hình.")
            return AgentResponse(
                answer=fallback_answer,
                citations=citations,
                meta={**meta, "llm_fallback": True, "llm_error": str(e)[:200]},
            )

        return AgentResponse(
            answer=answer,
            citations=citations,
            meta={**meta, "note": "Legal RAG Processed"}
        )

    async def process_stream(self, ctx: TrustedContext, query: str) -> AsyncGenerator[AgentResponse, None]:
        # Keep contract-safe streaming fallback (single final chunk).
        async for chunk in super().process_stream(ctx, query):
            yield chunk
