"""
[DEPRECATED] Compatibility alias for historical imports.
Please import directly from 'app.core.llm'.
This module will be removed in a future release.
"""
from __future__ import annotations
from typing import List
from app.core.llm import embed_query as _embed_query

async def embed_query(text: str) -> List[float]:
    return await _embed_query(text)

__all__ = ["embed_query"]
