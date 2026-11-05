# app/core/llm/rerank.py
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

_RERANKER_MODEL: Optional[CrossEncoder] = None
_RERANKER_LOCK = threading.Lock()

# Limit rerank concurrency to avoid CPU starvation
_RERANK_SEM: Optional[asyncio.Semaphore] = None


def _get_sem() -> asyncio.Semaphore:
    global _RERANK_SEM
    if _RERANK_SEM is None:
        max_c = int(getattr(settings, "RERANK_MAX_CONCURRENCY", 1) or 1)
        _RERANK_SEM = asyncio.Semaphore(max(1, max_c))
    return _RERANK_SEM


def get_reranker_model() -> CrossEncoder:
    """
    Lazy singleton loader (thread-safe).
    NOTE: predict() is sync, run it via asyncio.to_thread in async code.
    """
    global _RERANKER_MODEL
    if _RERANKER_MODEL is not None:
        return _RERANKER_MODEL

    with _RERANKER_LOCK:
        if _RERANKER_MODEL is not None:
            return _RERANKER_MODEL

        model_name = getattr(settings, "RERANK_MODEL_NAME", "BAAI/bge-reranker-v2-m3")
        device = getattr(settings, "RERANK_DEVICE", "cpu")  # "cpu" | "cuda"
        max_length = int(getattr(settings, "RERANK_MAX_LENGTH", 512) or 512)

        from sentence_transformers import CrossEncoder
        logger.info("Loading reranker model=%s device=%s max_length=%s", model_name, device, max_length)
        _RERANKER_MODEL = CrossEncoder(model_name, max_length=max_length, device=device)
        return _RERANKER_MODEL


def warmup_reranker() -> None:
    """Synchronous warmup: load model into memory."""
    _ = get_reranker_model()


def _pick_text(ch: Dict[str, Any]) -> str:
    if not ch:
        return ""
    for k in ("embed_text", "display_text", "content", "text", "chunk_text"):
        v = ch.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    payload = ch.get("payload")
    if isinstance(payload, dict):
        for k in ("embed_text", "display_text", "content", "text"):
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

    return ""


def _smart_truncate(text: str, max_chars: int) -> str:
    """
    Truncate softly to avoid cutting in the middle of sentences/words.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    cut = text[:max_chars]

    # Prefer cut at a sentence boundary near the end
    for sep in (". ", "。\n", "\n\n", "\n", "; ", ": ", ", "):
        idx = cut.rfind(sep)
        if idx >= int(max_chars * 0.7):
            return cut[: idx + len(sep)].strip()

    # Otherwise cut at last whitespace
    idx = cut.rfind(" ")
    if idx >= int(max_chars * 0.7):
        return cut[:idx].strip()

    return cut.strip()


# Circuit Breaker State
_BREAKER_FAILS = int(getattr(settings, "RERANK_BREAKER_FAILS", 5) or 5)
_BREAKER_COOLDOWN_S = float(getattr(settings, "RERANK_BREAKER_COOLDOWN_S", 60.0) or 60.0)
_fail_count = 0
_open_until = 0.0


def _breaker_open(now: float) -> bool:
    return now < _open_until


def _record_fail(now: float) -> None:
    global _fail_count, _open_until
    _fail_count += 1
    if _fail_count >= _BREAKER_FAILS:
        _open_until = now + _BREAKER_COOLDOWN_S
        _fail_count = 0
        logger.warning("Rerank circuit breaker OPEN until %.2f", _open_until)


def _record_success() -> None:
    global _fail_count, _open_until
    if _fail_count > 0:
        _fail_count = 0
    if _open_until > 0:
        _open_until = 0.0


async def rerank_chunks(
    *,
    query: str,
    chunks: List[Dict[str, Any]],
    top_n: int,
    # New params for Eco/Auto mode
    try_acquire: bool = False,
    deadline_ts: Optional[float] = None,
) -> Tuple[List[Dict[str, Any]], float, bool, str]:
    """
    Cross-encoder rerank over (query, chunk_text).

    Returns:
      (top_chunks, rerank_ms, is_fallback, reason)
    """
    if not chunks or not query.strip() or top_n <= 0:
        return (chunks[: max(0, top_n)], 0.0, True, "empty_input")

    # 1. Check Circuit Breaker
    now = time.perf_counter()
    if _breaker_open(now):
        return (chunks[: max(1, top_n)], 0.0, True, "breaker_open")

    # 2. Check Deadline (if provided)
    # We need at least ~20ms to even start
    if deadline_ts is not None:
        remaining = deadline_ts - now
        if remaining < 0.02:
            return (chunks[: max(1, top_n)], 0.0, True, "deadline_exceeded_pre_check")

    # Text truncation knobs
    # Default 6000 chars (safe-ish), still configurable
    text_max_chars = int(getattr(settings, "RERANK_TEXT_MAX_CHARS", 6000) or 6000)
    # Hard cap to avoid pathological OOM if chunk is gigantic
    hard_cap = int(getattr(settings, "RERANK_TEXT_HARD_CAP", 20000) or 20000)

    batch_size = int(getattr(settings, "RERANK_BATCH_SIZE", 16) or 16)

    # Prepare pairs
    pairs: List[List[str]] = []
    for ch in chunks:
        txt = _pick_text(ch)
        if hard_cap > 0 and len(txt) > hard_cap:
            txt = txt[:hard_cap]
        if text_max_chars > 0:
            txt = _smart_truncate(txt, text_max_chars)
        pairs.append([query, txt])

    t0 = time.perf_counter()
    sem = _get_sem()
    acquired = False

    try:
        # 3. Acquire Semaphore (Try or Wait)
        if try_acquire:
            try:
                # Instant check
                await asyncio.wait_for(sem.acquire(), timeout=0.001)
                acquired = True
            except asyncio.TimeoutError:
                return (chunks[: max(1, top_n)], 0.0, True, "sem_busy_skipped")
        else:
            # Wait with deadline awareness?
            # For now, standard wait, but we could wrap with wait_for if we wanted strict deadline.
            # But usually 'gov' mode (try_acquire=False) implies "wait as long as needed".
            await sem.acquire()
            acquired = True

        # 4. Predict
        model = get_reranker_model()

        # predict is sync → offload to a thread
        # If deadline is set, wrap in wait_for
        coro = asyncio.to_thread(
            model.predict,
            pairs,
            batch_size=batch_size,
            show_progress_bar=False,
        )

        if deadline_ts is not None:
            # Recalculate remaining time
            rem = deadline_ts - time.perf_counter()
            if rem < 0.05: # minimal time for inference
                 return (chunks[: max(1, top_n)], 0.0, True, "deadline_exceeded_pre_predict")
            scores = await asyncio.wait_for(coro, timeout=rem)
        else:
            scores = await coro

        _record_success()

        scored: List[Dict[str, Any]] = []
        for i, ch in enumerate(chunks):
            new_ch = dict(ch)
            old_score = ch.get("score")

            # overwrite score with rerank score
            new_ch["score"] = float(scores[i])

            payload = new_ch.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            payload = dict(payload)

            payload["_score_retrieval"] = old_score
            payload["_score_kind"] = "rerank"
            payload["_score_mode"] = "cross_encoder"

            new_ch["payload"] = payload
            scored.append(new_ch)

        scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

        dt_ms = (time.perf_counter() - t0) * 1000.0
        return (scored[:top_n], dt_ms, False, "ok")

    except asyncio.TimeoutError:
        _record_fail(time.perf_counter())
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return (chunks[: max(1, top_n)], dt_ms, True, "timeout_deadline")

    except Exception as e:
        _record_fail(time.perf_counter())
        dt_ms = (time.perf_counter() - t0) * 1000.0
        logger.exception("Rerank failed: %s", e)
        return (chunks[: max(1, top_n)], dt_ms, True, type(e).__name__)

    finally:
        if acquired:
            sem.release()
