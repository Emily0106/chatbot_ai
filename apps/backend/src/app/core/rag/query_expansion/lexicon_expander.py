"""
Lexicon Expander (PR-04).
Transforms a PreprocessResult into QueryVariants using LexiconMatch items.
"""

from __future__ import annotations

import re
from typing import List

from .preprocess import PreprocessResult
from .schemas import QueryVariant
from .schemas_lexicon import LexiconMatch


def build_lexicon_variants(
    pre: PreprocessResult,
    matches: List[LexiconMatch],
    max_n: int = 2
) -> List[QueryVariant]:
    """
    Builds up to max_n deterministic lexicon variants.
    Replaces exact matches of alias using word-boundaries.
    """
    if not matches:
        return []

    # Strategy: 
    # 1. Sort matches by length of alias DESC, then weight DESC.
    #    (Matches passed from DB might already be sorted, but we ensure here to avoid subword matching bugs)
    sorted_matches = sorted(matches, key=lambda m: (len(m.alias), m.weight), reverse=True)
    
    variants = []
    seen_texts = set()
    
    # Original query to dedupe against
    seen_texts.add(pre.normalized_query)

    for m in sorted_matches:
        if len(variants) >= max_n:
            break

        alias = m.alias
        canonical = m.canonical

        # Escape alias to safely use in regex
        # Word boundary \b works well for Vietnamese words separated by spaces.
        # Note: If alias contains punctuation, \b might behave unexpectedly, 
        # but for phase 1 deterministic replacement, it's the safest bet.
        pattern = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)

        # Substitute alias with canonical
        new_text = pattern.sub(canonical, pre.normalized_query)

        # Optimization Phase 1 Limitation Note:
        # If the original query had diacritics missing, a strict \b on the raw alias may fail to match.
        # Implementing a perfect robust mapping between normalized_no_diacritic back to 
        # the original text bounds is complex. For PR-04, we accept this exact-match constraint.

        if new_text not in seen_texts:
            # Enforce max length rule (from schema spec max_query_chars = 256)
            if len(new_text) <= 256:
                variants.append(
                    QueryVariant(
                        text=new_text,
                        source="LEXICON",
                        weight=0.95,
                        meta={"lexicon_term": alias, "canonical": canonical}
                    )
                )
                seen_texts.add(new_text)

    return variants
