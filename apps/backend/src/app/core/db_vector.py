# app/core/db_vector.py
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from functools import lru_cache
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = getattr(settings, "QDRANT_COLLECTION", "gov_knowledge")

def _sanitize_vector_name(value: Optional[str], *, default: str = "dense", allow_empty: bool = False) -> str:
    """
    Normalize vector names loaded from settings/env.
    Prevent empty-string names which trigger Qdrant "Not existing vector name" errors.
    """
    cleaned = (str(value).strip() if value is not None else "")
    if cleaned:
        return cleaned
    return "" if allow_empty else default


# Named vectors in Qdrant (must match ingestion)
DENSE_VECTOR_NAME = _sanitize_vector_name(
    getattr(settings, "QDRANT_DENSE_VECTOR_NAME", None) or os.getenv("QDRANT_DENSE_VECTOR_NAME"),
    default="dense",
)
SPARSE_VECTOR_NAME = _sanitize_vector_name(
    getattr(settings, "QDRANT_SPARSE_VECTOR_NAME", None) or os.getenv("QDRANT_SPARSE_VECTOR_NAME"),
    allow_empty=True,
)
SPARSE_ENABLED = bool(SPARSE_VECTOR_NAME)

# Timeouts / fusion params
DEFAULT_TIMEOUT_S = float(getattr(settings, "QDRANT_TIMEOUT", 30))
DEFAULT_PREFETCH_K = int(getattr(settings, "QDRANT_PREFETCH_K", 60) or 60)
DEFAULT_RRF_K = int(getattr(settings, "RRF_K", 60) or 60)

# Try server fusion if possible; otherwise fallback manual
TRY_SERVER_FUSION = str(getattr(settings, "QDRANT_TRY_SERVER_FUSION", "1")) != "0"

# SPLADE model for fastembed sparse embeddings
FASTEMBED_SPARSE_MODEL = getattr(settings, "FASTEMBED_SPARSE_MODEL", None) or os.getenv(
    "FASTEMBED_SPARSE_MODEL",
    # TODO: bạn nên chọn model phù hợp tiếng Việt/multilingual trong ingestion env thực tế
    "prithivida/Splade_PP_en_v1",
)

# If fastembed isn't thread-safe, optionally guard embed() with a lock.
FASTEMBED_LOCK = str(getattr(settings, "FASTEMBED_THREADSAFE_LOCK", "1")) != "0"
_fastembed_embed_lock = threading.Lock()

_qdrant_api_key = settings.QDRANT_READONLY_API_KEY
if not _qdrant_api_key:
    # Fail-Closed for Production (if not explicitly allowed to fallback)
    # For now, we allow fallback ONLY if QDRANT_API_KEY is set (Local Dev)
    # But strictly speaking, we should warn or fail if ENV is prod.
    # Let's use a simple heuristic: if QDRANT_API_KEY is also empty, we fail.
    # If QDRANT_API_KEY is set, we use it but warn.
    _fallback = getattr(settings, "QDRANT_API_KEY", "")
    if _fallback:
        import logging
        logging.getLogger(__name__).warning("Using QDRANT_API_KEY as fallback for ReadOnly. Ensure this is Local Dev only.")
        _qdrant_api_key = _fallback
    else:
        # Fallback to allow unit tests/docs to load this module without crashing
        import logging
        logging.getLogger(__name__).warning("⚠️ QDRANT_READONLY_API_KEY missing. Using 'mock-key' for import safety. Real requests will fail.")
        _qdrant_api_key = "mock-key-for-import"

import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)
    _qdrant = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        # Enforce Read-Only Key for Backend Core
        api_key=_qdrant_api_key,
        timeout=float(getattr(settings, "QDRANT_TIMEOUT", 30)),
    )


# -----------------------------
# Filters
# -----------------------------
# _build_filter removed (Legacy)



# -----------------------------
# Non-blocking helpers
# -----------------------------
async def _to_thread(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """
    Run CPU-bound sync function in a thread to avoid blocking event-loop.
    Compatible with Python <3.9 by falling back to run_in_executor.
    """
    try:
        to_thread = getattr(asyncio, "to_thread", None)
        if to_thread is not None:
            return await to_thread(func, *args, **kwargs)
    except Exception:
        pass

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


async def _maybe_await(x: Union[Any, Awaitable[Any]]) -> Any:
    return await x if asyncio.iscoroutine(x) else x


# -----------------------------
# Sparse embed (fastembed SPLADE)
# -----------------------------
@lru_cache(maxsize=1)
def _get_fastembed_sparse():
    # Lazy import để không làm crash server lúc boot nếu chưa cài fastembed
    from fastembed import SparseTextEmbedding  # type: ignore
    return SparseTextEmbedding(FASTEMBED_SPARSE_MODEL)


def _sparse_embed_fastembed_sync(query: str) -> qmodels.SparseVector:
    model = _get_fastembed_sparse()

    # Optional guard if library isn't thread-safe
    if FASTEMBED_LOCK:
        with _fastembed_embed_lock:
            emb = next(iter(model.embed([query])))
    else:
        emb = next(iter(model.embed([query])))

    indices = emb.get("indices") if isinstance(emb, dict) else getattr(emb, "indices", None)
    values = emb.get("values") if isinstance(emb, dict) else getattr(emb, "values", None)
    if indices is None or values is None:
        raise ValueError("fastembed returned invalid sparse embedding (missing indices/values)")

    return qmodels.SparseVector(indices=list(indices), values=list(values))


async def warmup_fastembed_sparse() -> None:
    """
    Optional: call this at app startup to avoid first-request cold start.
    """
    try:
        await _to_thread(_get_fastembed_sparse)
        logger.info("fastembed sparse model warmed up: %s", FASTEMBED_SPARSE_MODEL)
    except Exception as e:
        logger.warning("fastembed warmup failed (non-fatal): %s", e)


# -----------------------------
# RRF fusion (manual)
# -----------------------------
def _rrf_fuse(
    *,
    dense: List[Tuple[str, float, Dict[str, Any]]],
    sparse: List[Tuple[str, float, Dict[str, Any]]],
    top_k: int,
    rrf_k: int = DEFAULT_RRF_K,
) -> List[Tuple[str, float, Dict[str, Any]]]:
    """
    Reciprocal Rank Fusion on rankings, not raw scores.
    Returns: [(chunk_id, fused_score, payload), ...]
    """
    rank_dense: Dict[str, int] = {cid: i + 1 for i, (cid, _, _) in enumerate(dense)}
    rank_sparse: Dict[str, int] = {cid: i + 1 for i, (cid, _, _) in enumerate(sparse)}

    dense_score_map: Dict[str, float] = {cid: s for cid, s, _ in dense}
    sparse_score_map: Dict[str, float] = {cid: s for cid, s, _ in sparse}

    payload_map: Dict[str, Dict[str, Any]] = {}
    for cid, _, p in dense:
        payload_map[cid] = p or {}
    for cid, _, p in sparse:
        payload_map.setdefault(cid, p or {})

    all_ids = set(rank_dense.keys()) | set(rank_sparse.keys())

    fused: List[Tuple[str, float, Dict[str, Any]]] = []
    for cid in all_ids:
        s = 0.0
        rd = rank_dense.get(cid)
        rs = rank_sparse.get(cid)
        if rd is not None:
            s += 1.0 / (rrf_k + rd)
        if rs is not None:
            s += 1.0 / (rrf_k + rs)

        payload = dict(payload_map.get(cid, {}) or {})
        # Debug + score drift protection:
        payload["_score_kind"] = "rrf"
        payload["_score_mode"] = "hybrid_manual_rrf"
        payload["_dense_score"] = dense_score_map.get(cid)
        payload["_sparse_score"] = sparse_score_map.get(cid)

        fused.append((cid, float(s), payload))

    fused.sort(key=lambda x: x[1], reverse=True)
    return fused[: max(1, int(top_k))]


# -----------------------------
# Qdrant query wrapper
# -----------------------------
async def _qdrant_query_points_safe(**kwargs):
    """
    Wrap qdrant call with asyncio timeout for extra safety.
    """
    timeout_s = float(kwargs.pop("timeout_s", DEFAULT_TIMEOUT_S))
    return await asyncio.wait_for(_qdrant.query_points(**kwargs), timeout=timeout_s)


async def _dense_query(
    *,
    query_vector: List[float],
    q_filter: qmodels.Filter,
    limit: int,
    timeout_s: float,
) -> List[Tuple[str, float, Dict[str, Any]]]:
    """
    Dense search using named vector `dense`.
    """
    if not query_vector:
        return []

    resp = await _qdrant_query_points_safe(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        using=DENSE_VECTOR_NAME,
        query_filter=q_filter,
        limit=int(limit),
        with_payload=True,
        with_vectors=False,
        timeout_s=timeout_s,
    )

    points = resp.points if hasattr(resp, "points") else resp
    out: List[Tuple[str, float, Dict[str, Any]]] = []
    for p in points:
        payload = p.payload or {}
        # Score drift protection:
        payload["_score_kind"] = "cosine"
        payload["_score_mode"] = "dense"
        out.append((str(p.id), float(p.score or 0.0), payload))
    return out


async def _sparse_query(
    *,
    sparse_vector: qmodels.SparseVector,
    q_filter: qmodels.Filter,
    limit: int,
    timeout_s: float,
) -> List[Tuple[str, float, Dict[str, Any]]]:
    """
    Sparse search using named sparse vector `sparse`.
    """
    if not SPARSE_ENABLED:
        return []

    resp = await _qdrant_query_points_safe(
        collection_name=COLLECTION_NAME,
        query=sparse_vector,
        using=SPARSE_VECTOR_NAME,
        query_filter=q_filter,
        limit=int(limit),
        with_payload=True,
        with_vectors=False,
        timeout_s=timeout_s,
    )
    points = resp.points if hasattr(resp, "points") else resp
    out: List[Tuple[str, float, Dict[str, Any]]] = []
    for p in points:
        payload = p.payload or {}
        payload["_score_kind"] = "sparse"
        payload["_score_mode"] = "sparse"
        out.append((str(p.id), float(p.score or 0.0), payload))
    return out


# -----------------------------
# Public API (backward compatible + hybrid)
# -----------------------------
async def search_chunks(
    *,
    query_vector: List[float],
    tenant_id: str,
    top_k: int = 8,
    q_filter: Optional[qmodels.Filter] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> List[Tuple[str, float, Dict[str, Any]]]:
    """
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")

    if not query_vector:
        return []

    return await _dense_query(
        query_vector=query_vector,
        q_filter=q_filter,
        limit=int(top_k),
        timeout_s=timeout_s,
    )


DenseEmbedFn = Union[
    Callable[[str], List[float]],
    Callable[[str], Awaitable[List[float]]],
]


async def _dense_embed_nonblocking(dense_embed_fn: DenseEmbedFn, query: str) -> List[float]:
    """
    dense_embed_fn can be async (API call) or sync (local CPU/GPU).
    If sync -> run in thread to avoid blocking event-loop.
    """
    try:
        res = dense_embed_fn(query)
        if asyncio.iscoroutine(res):
            vec = await res  # type: ignore[misc]
        else:
            vec = await _to_thread(lambda: res)  # type: ignore[arg-type]
        return list(vec or [])
    except Exception:
        raise


async def _sparse_embed_nonblocking(query: str) -> qmodels.SparseVector:
    """
    fastembed SPLADE is sync + CPU-bound -> run in thread.
    """
    return await _to_thread(_sparse_embed_fastembed_sync, query)


async def search_hybrid_chunks(
    *,
    query: str,
    dense_embed_fn: DenseEmbedFn,
    tenant_id: str,
    top_k: int = 8,
    prefetch_k: int = DEFAULT_PREFETCH_K,
    q_filter: Optional[qmodels.Filter] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    rrf_k: int = DEFAULT_RRF_K,
    mode: str = "hybrid",  # "hybrid" | "dense_only"
) -> List[Tuple[str, float, Dict[str, Any]]]:
    """
    Hybrid Search (Dense + Sparse SPLADE) + RRF

    - mode="hybrid" (default): dense + sparse + RRF
    - mode="dense_only": fallback (dense only)

    Returns: [(chunk_id, score, payload), ...]
      - score is either cosine (dense/server fusion) or RRF (manual fusion)
      - payload contains `_score_kind` & `_score_mode` to prevent score-drift bugs downstream
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")

    query = (query or "").strip()
    if not query:
        return []

    # Collection configured without sparse vectors -> deterministic dense-only behavior.
    if mode == "hybrid" and not SPARSE_ENABLED:
        mode = "dense_only"

    t0 = time.time()

    # Dense-only fast path
    if mode == "dense_only":
        try:
            t_embed = time.time()
            dense_vector = await _dense_embed_nonblocking(dense_embed_fn, query)
            logger.debug("dense_embed dt=%.3fs", time.time() - t_embed)
        except Exception as e:
            logger.exception("Dense embedding failed. err=%s", e)
            return []

        if not dense_vector:
            return []

        out = await _dense_query(
            query_vector=dense_vector,
            q_filter=q_filter,
            limit=int(top_k),
            timeout_s=timeout_s,
        )
        logger.debug("search_hybrid(mode=dense_only) hits=%s dt=%.3fs", len(out), time.time() - t0)
        return out

    # HYBRID: run dense embedding + sparse embedding concurrently (reduces latency)
    try:
        t_embed = time.time()
        dense_task = asyncio.create_task(_dense_embed_nonblocking(dense_embed_fn, query))
        sparse_task = asyncio.create_task(_sparse_embed_nonblocking(query))
        dense_vector, sparse_vector = await asyncio.gather(dense_task, sparse_task)
        logger.debug("embed_parallel dt=%.3fs (dense+sparse)", time.time() - t_embed)
    except Exception as e:
        # If sparse fails OR fastembed missing -> fallback to dense only (fail-safe)
        logger.warning("Hybrid embedding failed -> fallback dense_only. err=%s", e)
        try:
            dense_vector = await _dense_embed_nonblocking(dense_embed_fn, query)
        except Exception as e2:
            logger.exception("Dense embedding failed even in fallback. err=%s", e2)
            return []

        if not dense_vector:
            return []

        out = await _dense_query(
            query_vector=dense_vector,
            q_filter=q_filter,
            limit=int(top_k),
            timeout_s=timeout_s,
        )
        logger.debug("search_hybrid(fallback=dense_only) hits=%s dt=%.3fs", len(out), time.time() - t0)
        return out

    if not dense_vector:
        return []

    # 3) Try server-side prefetch + fusion RRF (if supported)
    if TRY_SERVER_FUSION:
        try:
            fusion_query = qmodels.FusionQuery(fusion=qmodels.Fusion.RRF)
            prefetch = [
                qmodels.Prefetch(
                    query=list(dense_vector),
                    using=DENSE_VECTOR_NAME,
                    limit=int(prefetch_k),
                    filter=q_filter,
                ),
                qmodels.Prefetch(
                    query=sparse_vector,
                    using=SPARSE_VECTOR_NAME,
                    limit=int(prefetch_k),
                    filter=q_filter,
                ),
            ]

            t_q = time.time()
            resp = await _qdrant_query_points_safe(
                collection_name=COLLECTION_NAME,
                query=fusion_query,
                prefetch=prefetch,
                limit=int(top_k),
                with_payload=True,
                with_vectors=False,
                timeout_s=timeout_s,
            )
            logger.debug("qdrant_server_fusion dt=%.3fs", time.time() - t_q)

            points = resp.points if hasattr(resp, "points") else resp
            out: List[Tuple[str, float, Dict[str, Any]]] = []
            for p in points:
                payload = p.payload or {}
                payload["_score_kind"] = "rrf_or_fused"  # Qdrant already fused rankings; do NOT threshold absolutely
                payload["_score_mode"] = "hybrid_server_fusion"
                out.append((str(p.id), float(p.score or 0.0), payload))

            logger.debug("search_hybrid(mode=hybrid_server_fusion) hits=%s dt=%.3fs", len(out), time.time() - t0)
            return out

        except Exception as e:
            logger.info("Server fusion not available -> fallback manual RRF. err=%s", e)

    # 4) Manual fallback: prefetch dense + sparse -> RRF fuse
    try:
        t_q = time.time()
        dense_hits, sparse_hits = await asyncio.gather(
            _dense_query(
                query_vector=list(dense_vector),
                q_filter=q_filter,
                limit=int(prefetch_k),
                timeout_s=timeout_s,
            ),
            _sparse_query(
                sparse_vector=sparse_vector,
                q_filter=q_filter,
                limit=int(prefetch_k),
                timeout_s=timeout_s,
            ),
        )
        logger.debug("qdrant_manual_prefetch dt=%.3fs", time.time() - t_q)

        out = _rrf_fuse(dense=dense_hits, sparse=sparse_hits, top_k=int(top_k), rrf_k=int(rrf_k))
        logger.debug("search_hybrid(mode=hybrid_manual_rrf) hits=%s dt=%.3fs", len(out), time.time() - t0)
        return out

    except Exception as e:
        # Final defense: fallback dense-only
        logger.warning("Hybrid manual RRF failed -> fallback dense_only. err=%s", e)
        out = await _dense_query(
            query_vector=list(dense_vector),
            q_filter=q_filter,
            limit=int(top_k),
            timeout_s=timeout_s,
        )
        logger.debug("search_hybrid(final_fallback=dense_only) hits=%s dt=%.3fs", len(out), time.time() - t0)
        return out

# Export for main.py readiness check
qdrant_client = _qdrant
