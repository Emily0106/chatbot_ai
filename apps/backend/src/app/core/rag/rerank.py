# app/core/rag/rerank.py
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

# ---- Defaults
DEFAULT_MODEL_NAME = "BAAI/bge-reranker-v2-m3"
DEFAULT_MAX_LENGTH = 512
DEFAULT_TIMEOUT_S = 2.5
DEFAULT_BATCH_SIZE = 16

# ---- Concurrency control (avoid thread storm)
_MAX_CONCURRENT_RERANK = 4
_rerank_sem = asyncio.Semaphore(_MAX_CONCURRENT_RERANK)

# ---- Model cache keyed by (model_name, max_length)
_model_cache: Dict[Tuple[str, int], Any] = {}
_model_locks: Dict[Tuple[str, int], asyncio.Lock] = {}


def _get_lock(key: Tuple[str, int]) -> asyncio.Lock:
    if key not in _model_locks:
        _model_locks[key] = asyncio.Lock()
    return _model_locks[key]


def _sigmoid(x: float) -> float:
    # Only for telemetry/debug. DO NOT use for gating unless you also change evaluator thresholding.
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _clean_space(text: str) -> str:
    return " ".join((text or "").strip().split())


def _truncate_chars(text: str, max_chars: int) -> str:
    if not text:
        return ""
    t = _clean_space(text)
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "…"


def _pick_text_for_rerank(chunk: Dict[str, Any], *, prefer_parent_text: bool = False) -> str:
    """
    Prefer child text for specificity; fallback to parent text.
    If prefer_parent_text=True, score on parent evidence to reduce fragmentation.
    """
    if prefer_parent_text:
        return str(chunk.get("parent_text") or chunk.get("chunk_text") or "")
    return str(chunk.get("chunk_text") or chunk.get("parent_text") or "")


def _fingerprint_for_dedup(ch: Dict[str, Any]) -> str:
    """
    Dedup compute key:
      - parent_id (highest priority): many children share same parent evidence
      - chunk_id
      - text prefix fallback
    """
    pid = ch.get("parent_id")
    if pid:
        return f"pid:{pid}"
    cid = ch.get("chunk_id")
    if cid:
        return f"cid:{cid}"
    txt = _clean_space(str(ch.get("chunk_text") or ch.get("parent_text") or ""))
    return "txt:" + (txt[:200].lower() if txt else "empty")


def _ensure_payload_meta(ch: Dict[str, Any]) -> Dict[str, Any]:
    p = ch.get("payload")
    if not isinstance(p, dict):
        p = {}
    # Do not overwrite if already exists
    p.setdefault("_score_kind", "rerank")
    p.setdefault("_score_mode", "cross_encoder_logit")
    return p


def _load_model_sync(model_name: str, max_length: int):
    """
    Load CrossEncoder model (sync). Called inside a thread.

    NOTE/TODO (GPU/CPU resource policy):
      - Chưa xử lý chọn device (cuda/mps/cpu) ở phiên bản hiện tại.
      - Sẽ bổ sung sau (ví dụ: settings.RERANK_DEVICE hoặc auto-detect + pin).
      - Hiện tại để CrossEncoder tự quyết định device mặc định.
    """
    from sentence_transformers import CrossEncoder  # optional dependency

    # TODO: add `device=...` here later (e.g. device="cuda" if allowed/available)
    return CrossEncoder(model_name, max_length=max_length)


async def _get_model(model_name: str, max_length: int):
    key = (model_name, int(max_length))
    if key in _model_cache and _model_cache[key] is not None:
        return _model_cache[key]

    lock = _get_lock(key)
    async with lock:
        if key in _model_cache and _model_cache[key] is not None:
            return _model_cache[key]

        try:
            logger.info("Loading rerank model '%s' (max_length=%s)...", model_name, max_length)
            model = await asyncio.to_thread(_load_model_sync, model_name, max_length)
            _model_cache[key] = model
            logger.info("Rerank model loaded OK. key=%s", key)
            return model
        except ImportError:
            logger.warning("sentence-transformers not installed -> rerank disabled. pip install sentence-transformers")
            _model_cache[key] = None
            return None
        except Exception as e:
            logger.exception("Failed to load rerank model: %s", str(e))
            _model_cache[key] = None
            return None


def _sync_rerank(
    model,
    query: str,
    candidates: List[Dict[str, Any]],
    *,
    top_k: int,
    batch_size: int,
    prefer_parent_text: bool,
    max_input_chars: int,
) -> List[Dict[str, Any]]:
    """
    CrossEncoder.predict is CPU/GPU-bound -> sync, called in a thread.

    Output:
      - rerank_score: RAW LOGIT (compatible with current evaluator thresholds)
      - rerank_prob: sigmoid(logit) ONLY for telemetry/debug
      - payload meta: _score_kind="rerank"
      - preserve original score as vector_score (if absent)
    """
    if not candidates:
        return []

    q = _clean_space(query)
    if not q:
        return candidates[: max(1, int(top_k))]

    # 1) Dedup compute to avoid repeated scoring on same parent/text
    uniq_order: List[str] = []
    uniq_text: Dict[str, str] = {}

    for ch in candidates:
        fp = _fingerprint_for_dedup(ch)
        if fp in uniq_text:
            continue
        txt = _pick_text_for_rerank(ch, prefer_parent_text=prefer_parent_text)
        uniq_text[fp] = _truncate_chars(txt, max_input_chars)
        uniq_order.append(fp)

    pairs: List[List[str]] = [[q, uniq_text[fp]] for fp in uniq_order]

    # 2) Predict (logits)
    logits = model.predict(pairs, batch_size=int(batch_size))
    fp_logit: Dict[str, float] = {fp: float(logits[i]) for i, fp in enumerate(uniq_order)}

    # 3) Materialize results (copy chunks + attach rerank scores)
    ranked: List[Dict[str, Any]] = []
    for ch in candidates:
        fp = _fingerprint_for_dedup(ch)
        logit = fp_logit.get(fp, float("-inf"))

        new_ch = dict(ch)
        if "vector_score" not in new_ch:
            new_ch["vector_score"] = new_ch.get("score")

        new_ch["rerank_score"] = float(logit)         # <-- keep RAW LOGIT
        new_ch["rerank_prob"] = float(_sigmoid(logit))  # <-- telemetry only

        new_ch["payload"] = _ensure_payload_meta(new_ch)
        ranked.append(new_ch)

    ranked.sort(key=lambda x: float(x.get("rerank_score") or -1e9), reverse=True)
    return ranked[: max(1, int(top_k))]


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


async def rerank(
    *,
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: int = 8,
    model_name: Optional[str] = None,
    max_length: Optional[int] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_S,
    batch_size: int = DEFAULT_BATCH_SIZE,
    prefer_parent_text: bool = False,
    max_input_chars: int = 2400,
    # New params for Eco/Auto mode
    try_acquire: bool = False,
    deadline_ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Async entrypoint.

    NOTE:
      - GPU/CPU resource policy chưa xử lý ở bản này (sẽ xử lý sau).
      - rerank_score giữ dạng LOGIT để tương thích evaluator hiện tại.
      - rerank_prob chỉ dùng debug/telemetry (không dùng để gate trừ khi đổi threshold).
    """
    if not chunks:
        return []

    q = _clean_space(query)
    if not q:
        return chunks[: max(1, int(top_k))]

    # 1. Check Circuit Breaker
    now = time.perf_counter()
    if _breaker_open(now):
        # Return top_k without reranking (fallback)
        return chunks[: max(1, int(top_k))]

    # 2. Check Deadline (if provided)
    if deadline_ts is not None:
        remaining = deadline_ts - now
        if remaining < 0.02:
            return chunks[: max(1, int(top_k))]

    model_name = model_name or DEFAULT_MODEL_NAME
    max_length = int(max_length or DEFAULT_MAX_LENGTH)

    model = await _get_model(model_name, max_length)
    if model is None:
        return chunks[: max(1, int(top_k))]

    t0 = time.perf_counter()
    acquired = False

    try:
        # 3. Acquire Semaphore (Try or Wait)
        if try_acquire:
            try:
                await asyncio.wait_for(_rerank_sem.acquire(), timeout=0.001)
                acquired = True
            except asyncio.TimeoutError:
                return chunks[: max(1, int(top_k))]
        else:
            await _rerank_sem.acquire()
            acquired = True

        task = asyncio.to_thread(
            _sync_rerank,
            model,
            q,
            chunks,
            top_k=int(top_k),
            batch_size=int(batch_size),
            prefer_parent_text=bool(prefer_parent_text),
            max_input_chars=int(max_input_chars),
        )

        # 4. Wait with deadline awareness
        if deadline_ts is not None:
            rem = deadline_ts - time.perf_counter()
            if rem < 0.05:
                return chunks[: max(1, int(top_k))]
            # Use the smaller of timeout_seconds or remaining deadline
            eff_timeout = min(float(timeout_seconds), rem)
        else:
            eff_timeout = float(timeout_seconds)

        results = await asyncio.wait_for(task, timeout=eff_timeout)
        _record_success()

        ms = int((time.perf_counter() - t0) * 1000)
        try:
            uniq = len({_fingerprint_for_dedup(c) for c in chunks})
        except Exception:
            uniq = None

        logger.info(
            "Rerank OK: %d -> %d in %dms (uniq=%s, batch=%d, model=%s)",
            len(chunks),
            len(results),
            ms,
            str(uniq),
            int(batch_size),
            model_name,
        )
        return results

    except asyncio.TimeoutError:
        _record_fail(time.perf_counter())
        logger.warning("Rerank timeout (%.2fs) -> fallback to original top_k", float(timeout_seconds))
        return chunks[: max(1, int(top_k))]

    except Exception as e:
        _record_fail(time.perf_counter())
        logger.exception("Rerank error -> fallback. err=%s", str(e))
        return chunks[: max(1, int(top_k))]

    finally:
        if acquired:
            _rerank_sem.release()
