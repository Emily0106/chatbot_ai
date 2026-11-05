# apps/backend/src/app/core/temp_docs/search.py
from __future__ import annotations

from typing import List, Dict, Any
import re

def normalize_text(text: str) -> str:
    """Simple normalization: lower, strip, remove punctuation."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    return text

def lexical_rank(chunks: List[Dict[str, Any]], query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Rank chunks by simple token overlap.
    chunks: list of dict, expected to have 'text' field.
    """
    if not query or not chunks:
        return []

    norm_query = normalize_text(query)
    query_tokens = set(norm_query.split())
    
    if not query_tokens:
        return []

    scored_chunks = []
    for chunk in chunks:
        text = chunk.get("text", "")
        norm_text = normalize_text(text)
        text_tokens = set(norm_text.split())
        
        # Score = intersection / union (Jaccard-ish) or just intersection count
        # Let's use intersection count for simplicity + length penalty?
        # Just intersection count is fine for MVP.
        intersection = len(query_tokens.intersection(text_tokens))
        
        if intersection > 0:
            scored_chunks.append((intersection, chunk))

    # Sort desc by score
    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    
    return [c for _, c in scored_chunks[:top_k]]
