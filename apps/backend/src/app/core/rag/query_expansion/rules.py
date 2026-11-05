"""
Query Expansion Rules (PR-05).
Deterministic string rewrite rules using predefined templates and patterns.
"""

from __future__ import annotations
from typing import List

from app.core.rag.query_expansion.schemas import QueryVariant
from app.core.rag.query_expansion.preprocess import PreprocessResult

# To prevent importing heavy db logic, we lazily load or use a safe check.
# The `is_code_query` typically lives in `db_lexical`, but we are passed
# `is_code_query` either baked into Preprocess Result flags or we can safely 
# evaluate it if needed. However, per the prompt, relying on `pre.flags` or 
# `pre.must_keep_tokens` is preferred.

def build_rule_variants(pre: PreprocessResult, max_n: int = 1) -> List[QueryVariant]:
    """
    Apply Phase-1 deterministic rewriting rules.
    Priorities:
    R1. Code query phrasing (must_keep / is_code_query)
    R2. Penalty phrasing (xử phạt vi phạm hành chính)
    R3. Re-issue / re-register phrasing (cấp lại)
    """
    variants: List[QueryVariant] = []
    seen = {pre.normalized_query}

    def _add_variant(text: str, rule_id: str) -> None:
        if len(variants) >= max_n:
            return
        if text not in seen and len(text) <= 256:
            variants.append(QueryVariant(
                text=text,
                source="RULE",
                weight=0.90,
                meta={"rule_id": rule_id}
            ))
            seen.add(text)

    # Note: `is_code_query` flag might be injected into pre.flags by caller, 
    # but the rule states: "If pre.must_keep_tokens not empty OR pre.is_code_query is True"
    # We will check `must_keep_tokens` or a `is_code_query` flag.
    is_code = pre.flags.get("is_code_query", False)
    
    # R1 — Code query phrasing
    if pre.must_keep_tokens or is_code:
        # Use first token in must_keep_tokens if available, else fallback cleanly
        token = pre.must_keep_tokens[0] if pre.must_keep_tokens else ""
        if token:
            _add_variant(f"Tra cứu {token}", "CODE_QUERY_FORMAT")

    # R2 — Penalty phrasing
    lowered = pre.normalized_query.lower()
    penalty_keywords = ["mức phạt", "phạt bao nhiêu", "xử phạt", "vi phạm"]
    
    if any(k in lowered for k in penalty_keywords):
        if "xử phạt vi phạm hành chính" not in lowered:
            # Simple prepend rule for Phase 1
            _add_variant(f"xử phạt vi phạm hành chính {pre.normalized_query}", "PENALTY_VPHC")

    # R3 — Re-issue / re-register phrasing
    reissue_keywords = ["cấp lại", "làm lại", "đăng ký lại", "mất"]
    
    if any(k in lowered for k in reissue_keywords):
        if "cấp lại" not in lowered:
            _add_variant(f"cấp lại {pre.normalized_query}", "REISSUE_NORMALIZE")

    return variants
