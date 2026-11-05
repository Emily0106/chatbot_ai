"""
LLM Rewriter Module (PR-06).
Constrained wrapper invoking structured LLM outputs with hard 300ms timeout.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from app.core.llm.structured_outputs import aextract_pydantic
from app.core.rag.query_expansion.llm_schema import GovGradeQueryRewriteOutput

logger = logging.getLogger(__name__)


class LLMRewriter:
    def __init__(self, model_name: str = "gpt-4o-mini", timeout: float = 0.3) -> None:
        self.model_name = model_name
        self.timeout = timeout

    async def rewrite(
        self,
        *,
        redacted_query: str,
        allowed_terms: List[str],
        must_keep_tokens: List[str],
        max_variants: int = 2,
        intent_hint: Optional[str] = None,
    ) -> Optional[GovGradeQueryRewriteOutput]:
        """
        Rewrite query using exactly the allowed schema, respecting must-keep tokens.
        Fail-closed securely if any constraint is breached or if 300ms timeout occurs.
        """
        system = (
            "You are a Gov-Grade Query Expansion assistant. "
            "You MUST output raw JSON exactly matching the provided JSON schema."
        )
        user = f"Query: {redacted_query}\nAllowed terms: {allowed_terms}\nMust keep: {must_keep_tokens}"
        
        try:
            # Enforce Hard Timeout using existing codebase wrapper `aextract_pydantic`
            output: GovGradeQueryRewriteOutput = await asyncio.wait_for(
                aextract_pydantic(
                    response_model=GovGradeQueryRewriteOutput,
                    llm_model=self.model_name,
                    system=system,
                    user=user,
                    schema_name="gov_grade_rewrite",
                ),
                timeout=self.timeout
            )
        except (asyncio.TimeoutError, Exception) as e:
            # Log generically without exposing redacted query directly just to be safe (hash or len)
            logger.warning(f"LLMRewriter fail-closed: {e.__class__.__name__} len={len(redacted_query)}")
            return None
        
        # 1. Verification Runtime Check: Clamp max variants
        if len(output.variants) > max_variants:
            output.variants = output.variants[:max_variants]

        # 2. Verification Runtime Check: used_terms MUST be subset of allowed_terms
        allowed_set = set(allowed_terms)
        for v in output.variants:
            if not set(v.used_terms).issubset(allowed_set):
                logger.warning(f"LLMRewriter fail-closed: Term not in allowlist. used={v.used_terms}")
                return None

        # 3. Verification Runtime Check: all must_keep_tokens MUST appear in canonical AND variants
        for token in must_keep_tokens:
            if token not in output.canonical_query:
                logger.warning(f"LLMRewriter fail-closed: Missing must_keep token '{token}' in canonical_query")
                return None
            for v in output.variants:
                if token not in v.text:
                    logger.warning(f"LLMRewriter fail-closed: Missing must_keep token '{token}' in variant")
                    return None

        return output
