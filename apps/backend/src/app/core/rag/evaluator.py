# app/core/rag/evaluator.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

# Defaults (can be overridden by settings/.env)
DEFAULT_RERANK_THRESHOLD = float(getattr(settings, "RERANK_THRESHOLD", -1.5))
DEFAULT_VECTOR_THRESHOLD = float(getattr(settings, "VECTOR_THRESHOLD", 0.45))
DEFAULT_TOP_N = int(getattr(settings, "EVIDENCE_TOP_N", 3))

# Heuristics for non-cosine scoring (RRF / lexical)
DEFAULT_MIN_DOCS_IN_TOPN = int(getattr(settings, "EVIDENCE_MIN_DOCS_IN_TOPN", 1))
DEFAULT_MIN_SCORED_CHUNKS = int(getattr(settings, "EVIDENCE_MIN_SCORED_CHUNKS", 1))
DEFAULT_MIN_SPREAD = float(getattr(settings, "EVIDENCE_MIN_SPREAD", 0.0))  # keep 0 for rrf/lexical


def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _meta(chunk: Dict[str, Any], key: str) -> Any:
    if key in chunk:
        return chunk.get(key)
    payload = chunk.get("payload") or {}
    if isinstance(payload, dict) and key in payload:
        return payload.get(key)
    return None


def _score_kind(chunk: Dict[str, Any]) -> str:
    v = _meta(chunk, "_score_kind")
    return str(v).lower() if v is not None else "unknown"


def _score_mode(chunk: Dict[str, Any]) -> str:
    v = _meta(chunk, "_score_mode")
    return str(v) if v is not None else "unknown"


def _doc_id(chunk: Dict[str, Any]) -> str:
    did = chunk.get("document_id")
    if did is None:
        did = _meta(chunk, "document_id")
    return str(did or "")


def evaluate(
    *,
    query: str,
    chunks: List[Dict[str, Any]],
    rerank_threshold: float = DEFAULT_RERANK_THRESHOLD,
    vector_threshold: float = DEFAULT_VECTOR_THRESHOLD,
    top_n: int = DEFAULT_TOP_N,
    min_docs_in_topn: int = DEFAULT_MIN_DOCS_IN_TOPN,
    min_scored_chunks: int = DEFAULT_MIN_SCORED_CHUNKS,
    min_spread: float = DEFAULT_MIN_SPREAD,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Evidence gate for:
      - rerank_score (CrossEncoder logits, comparable scale)
      - dense cosine score
      - hybrid manual RRF score
      - lexical (FTS/trigram) score

    Returns:
      ok, info(dict)
    """
    if not chunks:
        return False, {"reason": "no_chunks", "mode": "none", "passed": False}

    n = max(1, int(top_n))
    sample = chunks[:n]

    # 1) Prefer rerank_score if present in top_n
    best_rerank = None
    best_rerank_idx = None
    for i, ch in enumerate(sample):
        s = _to_float(ch.get("rerank_score"))
        if s is None:
            continue
        if best_rerank is None or s > best_rerank:
            best_rerank = s
            best_rerank_idx = i

    if best_rerank is not None:
        passed = best_rerank >= float(rerank_threshold)
        return passed, {
            "reason": "rerank_score",
            "mode": "rerank",
            "best_score": float(best_rerank),
            "best_rank": int(best_rerank_idx),
            "threshold": float(rerank_threshold),
            "top_n": n,
            "passed": passed,
        }

    # 2) No rerank_score -> gate based on score_kind
    top_kind = _score_kind(sample[0])
    top_mode = _score_mode(sample[0])

    scores: List[Tuple[int, float]] = []
    for i, ch in enumerate(sample):
        s = _to_float(ch.get("score"))
        if s is not None:
            scores.append((i, s))

    uniq_docs = len({d for d in (_doc_id(ch) for ch in sample) if d})

    # 2a) cosine/vector -> allow absolute threshold
    if top_kind in ("cosine", "vector"):
        if not scores:
            return False, {
                "reason": "no_vector_scores",
                "mode": "vector",
                "top_kind": top_kind,
                "top_mode": top_mode,
                "top_n": n,
                "passed": False,
            }

        best_idx, best_score = max(scores, key=lambda x: x[1])
        passed = float(best_score) >= float(vector_threshold)

        spread = None
        if len(scores) >= 2:
            s_sorted = sorted((s for _, s in scores), reverse=True)
            spread = float(s_sorted[0] - s_sorted[1])
            if spread < float(min_spread):
                passed = False

        return passed, {
            "reason": "vector_score",
            "mode": "vector",
            "top_kind": top_kind,
            "top_mode": top_mode,
            "best_score": float(best_score),
            "best_rank": int(best_idx),
            "threshold": float(vector_threshold),
            "spread_top1_top2": spread,
            "uniq_docs_topn": uniq_docs,
            "top_n": n,
            "passed": passed,
        }

    # 2b) rrf/lexical/unknown -> do NOT absolute-threshold
    scored_cnt = len(scores)

    passed = (scored_cnt >= int(min_scored_chunks)) and (uniq_docs >= int(min_docs_in_topn))

    spread = None
    if len(scores) >= 2:
        s_sorted = sorted((s for _, s in scores), reverse=True)
        spread = float(s_sorted[0] - s_sorted[1])
        if spread < float(min_spread):
            passed = False

    if scored_cnt == 0:
        passed = False  # conservative

    return passed, {
        "reason": "noncosine_rank_gate",
        "mode": "rank_gate",
        "top_kind": top_kind,
        "top_mode": top_mode,
        "scored_cnt_topn": scored_cnt,
        "uniq_docs_topn": uniq_docs,
        "spread_top1_top2": spread,
        "top_n": n,
        "passed": passed,
    }
