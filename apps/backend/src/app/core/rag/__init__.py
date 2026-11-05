# app/core/rag/__init__.py
from __future__ import annotations

"""
RAG Core Facade.

Mục tiêu:
- Agent import gọn: `from app.core import rag`
- Re-export các hàm/chủng loại dùng nhiều (pipeline + schemas)
- API ổn định: nếu chưa có rag_answer_stream thì vẫn import được,
  nhưng gọi sẽ báo lỗi hướng dẫn rõ ràng.
"""

from typing import Any, AsyncGenerator, List, Tuple, Optional

from app.schemas.chat import RetrievalFilters, Citation

# Main pipeline API
from .pipeline import rag_retrieve, RagPipelineResult

# Optional: streaming "magic function"
try:
    from .pipeline import rag_answer_stream as _rag_answer_stream  # type: ignore
except Exception:  # pragma: no cover
    _rag_answer_stream = None  # type: ignore


async def rag_answer_stream(*args: Any, **kwargs: Any):
    """
    Full RAG (stream) facade.

    Nếu bạn đã implement rag_answer_stream trong pipeline.py:
      - Hàm này sẽ được trỏ sang implementation thật.

    Nếu chưa:
      - Hàm này raise lỗi hướng dẫn cách dùng rag_retrieve + llm.generate_stream.
    """
    if _rag_answer_stream is None:
        raise RuntimeError(
            "rag_answer_stream() chua duoc implement trong app/core/rag/pipeline.py. "
            "Ban co the:\n"
            "  (1) Implement rag_answer_stream trong pipeline.py (goi rag_retrieve -> build messages -> generate_stream), hoac\n"
            "  (2) Dung rag_retrieve(...) de lay (context, citations, meta) roi Agent tu goi llm.generate_stream(...).\n"
        )
    return await _rag_answer_stream(*args, **kwargs)


__all__ = [
    # pipeline
    "rag_retrieve",
    "rag_answer_stream",
    "RagPipelineResult",
    # schemas (re-export)
    "RetrievalFilters",
    "Citation",
]
