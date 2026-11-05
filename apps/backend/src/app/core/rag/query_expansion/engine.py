"""
Query Expansion Engine Orchestration (PR-07).
Orchestrates preprocess -> lexicon -> rules -> LLM rewrite.
"""
from __future__ import annotations
import logging
from typing import Any, Optional, Dict, List

from app.core.rag.query_expansion.schemas import QueryExpansionConfig, QueryPack, QueryVariant
from app.core.rag.query_expansion.lexicon_repo import LexiconRepo
from app.core.rag.query_expansion.llm_rewriter import LLMRewriter
from app.core.rag.query_expansion.preprocess import preprocess_query, PreprocessResult
from app.core.rag.query_expansion.lexicon_expander import build_lexicon_variants
from app.core.rag.query_expansion.rules import build_rule_variants

logger = logging.getLogger(__name__)


class QueryExpansionEngine:
    def __init__(
        self,
        cfg: QueryExpansionConfig,
        lexicon_repo: LexiconRepo,
        llm_rewriter: LLMRewriter,
        logger_instance: Optional[logging.Logger] = None
    ) -> None:
        self.cfg = cfg
        self.lexicon_repo = lexicon_repo
        self.llm_rewriter = llm_rewriter
        self.logger = logger_instance or logger

    async def expand(
        self,
        raw_query: str,
        *,
        user_ctx: Optional[Any] = None,
        agent_policy: Optional[Any] = None
    ) -> QueryPack:
        """
        Orchestrate the deterministic and fail-closed query expansion pipeline.
        """
        # 1. Preprocess (validates empty/length, extracts must_keep, redact PII, flags injection)
        pre = preprocess_query(raw_query)
        
        # Populate is_code_query flag if missing (from pre.must_keep_tokens presence)
        if "is_code_query" not in pre.flags:
            pre.flags["is_code_query"] = len(pre.must_keep_tokens) > 0
            
        variants: List[QueryVariant] = []
        debug_info: Dict[str, Any] = {
            "lexicon_version": "0",
            "llm_used": False,
            "llm_timeout": False
        }
        
        # 2. LEXICON Phase (Fail-soft)
        if self.cfg.max_lexicon_variants > 0:
            try:
                debug_info["lexicon_version"] = await self.lexicon_repo.version()
                # Phase 1 limits to global lexicon (tenant_id=None)
                matches = await self.lexicon_repo.match(
                    normalized=pre.normalized_query,
                    normalized_no_diacritic=pre.normalized_no_diacritic,
                    limit=self.cfg.max_lexicon_variants * 2  # slight fetch buffer
                )
                lex_variants = build_lexicon_variants(pre, matches, max_n=self.cfg.max_lexicon_variants)
                variants.extend(lex_variants)
            except Exception as e:
                self.logger.warning("Lexicon matched failed (fail-soft): %s", e)
                
        # 3. RULE Phase
        if self.cfg.max_rule_variants > 0:
            rule_variants = build_rule_variants(pre, max_n=self.cfg.max_rule_variants)
            variants.extend(rule_variants)

        # 4. LLM Phase
        llm_disabled = False
        if not self.cfg.enable_llm_rewrite or self.cfg.max_llm_variants <= 0:
            llm_disabled = True
        elif self.cfg.disable_llm_if_injection_suspected and pre.flags.get("injection_suspected"):
            llm_disabled = True
        elif pre.flags.get("is_code_query") or pre.must_keep_tokens:
            llm_disabled = True
            
        if not llm_disabled:
            try:
                # LLM rewrite
                llm_out = await self.llm_rewriter.rewrite(
                    redacted_query=pre.redacted_query,
                    allowed_terms=[], # Phase 1: allowed_terms empty
                    must_keep_tokens=pre.must_keep_tokens,
                    max_variants=self.cfg.max_llm_variants
                )
                debug_info["llm_used"] = True
                if llm_out is None:
                    # In our tests, llm returning None denotes timeout or fail-closed.
                    debug_info["llm_timeout"] = True
                else:
                    for v in llm_out.variants:
                        variants.append(QueryVariant(
                            text=v.text,
                            source="LLM",
                            weight=0.85,
                            meta={"type": v.type, "used_terms": v.used_terms}
                        ))
            except Exception as e:
                self.logger.warning("LLM rewrite failed (fail-soft): %s", e)
                debug_info["llm_timeout"] = True
                debug_info["llm_used"] = True
                
        # 5. Deduplicate and Clamp
        # 5a. Drop variant if identical to pre.normalized_query
        # 5b. Dedupe by normalized text (case/space normalized)
        # 5c. Keep highest weight if collision
        # 5d. Stable ordering: weight desc, then source order (LEXICON -> RULE -> LLM)
        
        source_order = {"LEXICON": 0, "RULE": 1, "LLM": 2}
        
        unique_variants: Dict[str, QueryVariant] = {}
        for v in variants:
            # Case/space normalized
            norm_v = " ".join(v.text.lower().split())
            if norm_v == pre.normalized_query.lower():
                continue
                
            if norm_v not in unique_variants:
                unique_variants[norm_v] = v
            else:
                existing = unique_variants[norm_v]
                # If collision, keep highest weight. If equal weight, keep lowest source_order
                if v.weight > existing.weight:
                    unique_variants[norm_v] = v
                elif v.weight == existing.weight:
                    if source_order.get(v.source, 99) < source_order.get(existing.source, 99):
                        unique_variants[norm_v] = v

        final_variants = list(unique_variants.values())
        final_variants.sort(key=lambda x: (-x.weight, source_order.get(x.source, 99)))
        
        # Cap max_variants_total
        final_variants = final_variants[:self.cfg.max_variants_total]
        
        audit_info = {
            "expansion_applied": len(final_variants) > 0,
            "variants_count": len(final_variants)
        }
        
        return QueryPack(
            original_query=raw_query,
            normalized_query=pre.normalized_query,
            redacted_query=pre.redacted_query,
            flags=pre.flags,
            must_keep_tokens=pre.must_keep_tokens,
            variants=final_variants,
            debug=debug_info,
            audit=audit_info
        )
