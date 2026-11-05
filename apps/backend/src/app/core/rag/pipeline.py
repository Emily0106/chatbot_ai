# app/core/rag/pipeline.py
from __future__ import annotations

import hashlib
import json
import logging    
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cache import cache_get, cache_set, cache_get_tenant_epoch
from app.schemas.chat import Citation, RetrievalFilters
from app.core.router import decide_lane, LaneDecision

from .retrieve import retrieve, RetrieveResult
from .context import build_context, ContextBuildResult
from app.core.metrics import GATE_FAIL_TOTAL

logger = logging.getLogger(__name__)



# -----------------------------
# Helpers: text processing
# -----------------------------
import re

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ỹ]{2,}")
_VI_STOP = {
    "là","và","của","cho","các","những","một","theo","trong","khi","với","được","tại","đến","từ","về","này","đó"
}

def _tokens(s: str) -> List[str]:
    toks = [t.lower() for t in _TOKEN_RE.findall(s or "")]
    return [t for t in toks if t not in _VI_STOP]

def _overlap_count(q: str, t: str) -> int:
    qt = set(_tokens(q))
    if not qt:
        return 0
    tt = set(_tokens(t))
    return sum(1 for x in qt if x in tt)

@dataclass(frozen=True)
class RagPipelineResult:
    context: str
    citations: List[Citation]
    meta: Dict[str, Any]


# -----------------------------
# Helpers: telemetry toggles
# -----------------------------
def _bool_env(name: str, default: bool = True) -> bool:
    v = getattr(settings, name, None)
    if v is None:
        return default
    s = str(v).strip().lower()
    return s not in {"0", "false", "no", "off", ""}


RAG_TRACE_LOG = _bool_env("RAG_TRACE_LOG", default=True)
RAG_TRACE_INCLUDE_DEBUG = _bool_env("RAG_TRACE_INCLUDE_DEBUG", default=False)
RAG_TRACE_DEBUG_MAX_CHARS = int(getattr(settings, "RAG_TRACE_DEBUG_MAX_CHARS", 1500) or 1500)


def _sha1(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8", errors="ignore")).hexdigest()


def _safe_debug(debug: Any) -> Any:
    """
    Avoid logging huge / sensitive fields. Keep only compact debug when enabled.
    """
    if not RAG_TRACE_INCLUDE_DEBUG:
        return None
    try:
        txt = json.dumps(debug, ensure_ascii=False)
        if len(txt) > RAG_TRACE_DEBUG_MAX_CHARS:
            txt = txt[:RAG_TRACE_DEBUG_MAX_CHARS] + "...(truncated)"
        return json.loads(txt)
    except Exception:
        # fallback: string truncation
        t = str(debug)
        if len(t) > RAG_TRACE_DEBUG_MAX_CHARS:
            t = t[:RAG_TRACE_DEBUG_MAX_CHARS] + "...(truncated)"
        return t


# -----------------------------
# Helpers: cache key
# -----------------------------
def _stable_filters(filters: Optional[RetrievalFilters]) -> Dict[str, Any]:
    if not filters:
        return {}
    d = filters.model_dump(exclude_none=True)
    return dict(sorted(d.items(), key=lambda x: x[0]))


def _normalize_query(q: str) -> str:
    return " ".join((q or "").strip().split())


def _make_cache_key(
    *,
    tenant_id: str,
    agent_id: str,
    query: str,
    filters: Optional[RetrievalFilters],
    # retrieval
    top_k: int,
    # rerank
    enable_rerank: bool,
    rerank_top_k: int,
    # gate
    gate_top_n: int,
    # context
    max_total_chars: int,
    max_chunk_chars: int,
    dedup: bool,
    max_chunks: int,
    max_per_document: int,
    include_scores: bool,
    include_scores_in_prompt: bool,
    prefer_parent_text: bool,
    tenant_epoch: int,
) -> str:
    payload = {
        "v": 5,  # bump because tenant epoch cache invalidation is enabled
        "tenant": tenant_id,
        "tenant_epoch": int(tenant_epoch),
        "agent": agent_id,
        "q": _normalize_query(query).lower(),
        "filters": _stable_filters(filters),
        "retrieval": {"top_k": int(top_k)},
        "rerank": {"enable": bool(enable_rerank), "top_k": int(rerank_top_k)},
        "gate": {"top_n": int(gate_top_n)},
        "context": {
            "max_total_chars": int(max_total_chars),
            "max_chunk_chars": int(max_chunk_chars),
            "dedup": bool(dedup),
            "max_chunks": int(max_chunks),
            "max_per_document": int(max_per_document),
            "include_scores": bool(include_scores),
            "include_scores_in_prompt": bool(include_scores_in_prompt),
            "prefer_parent_text": bool(prefer_parent_text),
        },
    }
    return "rag:" + json.dumps(payload, ensure_ascii=False, sort_keys=True)


# -----------------------------
# Helpers: citations
# -----------------------------
def _make_snippet(text: str, max_len: int = 180) -> str:
    t = " ".join((text or "").strip().split())
    if len(t) <= max_len:
        return t
    cut = t[:max_len]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "..."


def _pick_citation_text(ch: Dict[str, Any], *, prefer_parent_text: bool) -> str:
    if prefer_parent_text:
        return str(ch.get("parent_text") or ch.get("chunk_text") or "")
    return str(ch.get("chunk_text") or ch.get("parent_text") or "")


def _build_citations_safe(
    chunks: List[Dict[str, Any]],
    doc_map: Dict[str, Dict[str, Any]],
    *,
    max_citations: int = 10,
    prefer_parent_text: bool = True,
) -> List[Citation]:
    """
    Build citations from *used chunks* (sync with context).
    Enriched: title/url/page/score + snippet.
    """
    out: List[Citation] = []
    for ch in chunks[:max_citations]:
        did = str(ch.get("document_id") or "")
        doc = doc_map.get(did, {}) if did else {}

        # Prefer rerank_score for display, else score
        score = ch.get("rerank_score")
        if score is None:
            score = ch.get("score")

        snippet_src = _pick_citation_text(ch, prefer_parent_text=prefer_parent_text)

        out.append(
            Citation(
                chunk_id=str(ch.get("chunk_id") or "unknown"),
                document_id=(did or None),
                title=(doc.get("title") or "Tài liệu hệ thống"),
                source_url=doc.get("file_url"),
                page_number=(int(ch["page_start"]) if ch.get("page_start") is not None else None),
                score=(float(score) if score is not None else None),
                snippet=_make_snippet(snippet_src),
            )
        )
    return out


def _meta(ch: Dict[str, Any], key: str) -> Any:
    if key in ch:
        return ch.get(key)
    p = ch.get("payload") or {}
    if isinstance(p, dict) and key in p:
        return p.get(key)
    return None


# -----------------------------
# Hooks: rerank / evaluator (soft dependencies)
# -----------------------------
async def _maybe_rerank(
    *,
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: int,
    prefer_parent_text: bool,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Returns: (reranked_chunks, success_bool)
    Contract expected from .rerank:
      async def rerank(query: str, chunks: List[dict], top_k: int, prefer_parent_text: bool = ...) -> List[dict]
    """
    if not chunks:
        return [], False
    try:
        from .rerank import rerank  # type: ignore

        reranked = await rerank(
            query=query,
            chunks=chunks,
            top_k=int(top_k),
            prefer_parent_text=bool(prefer_parent_text),
        )
        # Check if fallback occurred (rerank returned chunks but no rerank_score)
        ok = bool(reranked) and ("rerank_score" in (reranked[0] or {}))
        return list(reranked or []), ok
    except ImportError:
        return chunks[: int(top_k)], False
    except Exception as e:
        logger.warning("Rerank failed; fallback to vector order. err=%s", e)
        return chunks[: int(top_k)], False


def _evaluate_evidence(
    *,
    query: str,
    chunks: List[Dict[str, Any]],
) -> Tuple[bool, Dict[str, Any]]:
    """
    Prefer evaluator.evaluate(). If missing, do conservative fallback gate that is
    hybrid-safe and LOGIT-safe.
    """
    if not chunks:
        return False, {"reason": "no_chunks"}

    try:
        from .evaluator import evaluate  # type: ignore

        ok, info = evaluate(query=query, chunks=chunks)
        return bool(ok), dict(info or {})
    except Exception as e:
        best = chunks[0]
        score_kind = str(_meta(best, "_score_kind") or "unknown").lower()

        # Text for overlap (prefer parent if available)
        text = str(best.get("parent_text") or best.get("chunk_text") or "")
        ov = _overlap_count(query, text)
        q_tok_n = len(_tokens(query))
        need_ov = 1 if q_tok_n <= 2 else 2

        # 1) If rerank_score exists -> LOGIT gate (Gov lane)
        s = best.get("rerank_score")
        if s is not None:
            try:
                val = float(s)
                thresh = float(getattr(settings, "RERANK_GATE_MIN_LOGIT", -1.0) or -1.0)
                ok = (val >= thresh) and (ov >= 1)
                return ok, {
                    "reason": "fallback_rerank_logit_gate",
                    "score": val,
                    "thresh": thresh,
                    "overlap": ov,
                    "need_overlap": 1,
                    "score_kind": score_kind,
                    "err": type(e).__name__,
                }
            except Exception:
                return False, {"reason": "fallback_rerank_parse_fail", "err": type(e).__name__}

        # 2) RRF gate (Eco-safe)
        if score_kind == "rrf":
            try:
                rrf_score = float(best.get("score") or 0.0)
            except Exception:
                rrf_score = 0.0

            sources = _meta(best, "_sources")
            src_n = len(sources) if isinstance(sources, list) else 0

            thr_multi = float(getattr(settings, "RRF_GATE_MIN_MULTI", 0.018) or 0.018)
            thr_single = float(getattr(settings, "RRF_GATE_MIN_SINGLE", 0.013) or 0.013)

            if src_n >= 2:
                ok = (rrf_score >= thr_multi) and (ov >= 1)
                return ok, {
                    "reason": "fallback_rrf_gate_multi",
                    "rrf_score": rrf_score,
                    "thresh": thr_multi,
                    "sources": sources,
                    "overlap": ov,
                    "need_overlap": 1,
                    "err": type(e).__name__,
                }
            else:
                ok = (rrf_score >= thr_single) and (ov >= need_ov)
                return ok, {
                    "reason": "fallback_rrf_gate_single",
                    "rrf_score": rrf_score,
                    "thresh": thr_single,
                    "sources": sources,
                    "overlap": ov,
                    "need_overlap": need_ov,
                    "err": type(e).__name__,
                }

        # 3) Lexical gate (if any) -> rely on overlap (lexical score scale varies)
        if score_kind == "lexical":
            ok = (ov >= need_ov)
            return ok, {
                "reason": "fallback_lexical_overlap_gate",
                "overlap": ov,
                "need_overlap": need_ov,
                "err": type(e).__name__,
            }

        # 4) Vector/hybrid gate
        try:
            val = float(best.get("score")) if best.get("score") is not None else None
        except Exception:
            val = None

        if val is None:
            return False, {"reason": "fallback_no_score_fail_closed", "overlap": ov, "err": type(e).__name__}

        thr_vec = float(getattr(settings, "VECTOR_GATE_MIN", 0.45) or 0.45)
        ok = (val >= thr_vec) and (ov >= 1)
        return ok, {
            "reason": "fallback_vector_gate",
            "score": val,
            "thresh": thr_vec,
            "overlap": ov,
            "need_overlap": 1,
            "score_kind": score_kind,
            "err": type(e).__name__,
        }


def _is_code_like(debug: Any) -> bool:
    if not isinstance(debug, dict):
        return False
    v = debug.get("code_like")
    return bool(v)


def _log_trace(trace: Dict[str, Any]) -> None:
    if not RAG_TRACE_LOG:
        return
    try:
        logger.info("rag_trace=%s", json.dumps(trace, ensure_ascii=False))
    except Exception:
        logger.info("rag_trace=%s", str(trace))


# -----------------------------
# Main API
# -----------------------------
async def rag_retrieve(
    db: AsyncSession,
    *,
    tenant_id: str,
    agent_id: str,
    query: str,
    filters: Optional[RetrievalFilters] = None,
    # retrieval
    top_k: int = 30,
    # rerank
    enable_rerank: bool = False,
    rerank_top_k: int = 10,
    # gate
    gate_top_n: int = 10,
    # context
    max_total_chars: int = 9000,
    max_chunk_chars: int = 1400,
    dedup: bool = True,
    max_chunks: int = 12,
    max_per_document: int = 6,
    include_scores: bool = True,
    include_scores_in_prompt: bool = False,
    prefer_parent_text: bool = True,
    # cache
    enable_cache: bool = True,
    cache_ttl_seconds: int = 300,
    # fallback / retry
    enable_retry: bool = True,
    broaden_top_k: int = 60,
    force_rerank_on_retry: bool = True,
    relax_filters_on_retry: bool = False,
    # telemetry
    trace_id: Optional[str] = None,
    # routing
    security_level: int = 1,
    user_context: Optional[Dict[str, Any]] = None,
) -> RagPipelineResult:
    """
    Orchestrator:
      Cache -> Retrieve -> (Rerank) -> Gate -> Build Context -> Build Citations -> Cache set

    Telemetry additions:
      - trace_id
      - safe query hash (avoid logging raw query)
      - attempt_total_ms + cache_set_ms
      - structured trace log: "rag_trace=..."
    """
    t0 = time.perf_counter()
    trace_id = trace_id or uuid.uuid4().hex

    q = _normalize_query(query)
    if not q:
        meta = {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "trace_id": trace_id,
            "reason": "empty_query",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }
        _log_trace(
            {
                "trace_id": trace_id,
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "ok": False,
                "reason": "empty_query",
                "latency_ms": meta["latency_ms"],
            }
        )
        return RagPipelineResult(context="", citations=[], meta=meta)

    meta: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "trace_id": trace_id,
        "top_k": int(top_k),
        "gate_top_n": int(gate_top_n),
        # safe query fingerprints
        "query_len": len(q),
        "query_sha1": _sha1(q.lower()),
    }

    # ---- MODE SELECTION (Eco/Auto/Gov) ----
    mode = str(getattr(settings, "RETRIEVAL_MODE", "auto") or "auto").lower()
    deadline_ms = int(getattr(settings, "RETRIEVAL_DEADLINE_MS", 1500) or 1500)
    deadline_ts = t0 + (deadline_ms / 1000.0)
    
    meta["retrieval_mode"] = mode
    meta["deadline_ms"] = deadline_ms

    # ---- ROUTING (PR4) ----
    # Default parameters based on strict
    eff_top_k = int(top_k)
    eff_rerank = bool(enable_rerank)
    
    # Decide lane
    lane_decision = decide_lane(
        query=q, 
        agent_id=agent_id, 
        security_level=security_level
    )
    
    # Override if FAST lane enabled and router said fast
    lane = "strict"
    enable_fast_lane_flag = bool(getattr(settings, "ENABLE_FAST_LANE", False))
    
    if enable_fast_lane_flag and lane_decision.lane == "fast":
        lane = "fast"
        # FAST knobs
        fast_top_k = int(getattr(settings, "FAST_TOP_K", 20))
        fast_skip_rerank = bool(getattr(settings, "FAST_SKIP_RERANK", True))
        
        eff_top_k = fast_top_k
        if fast_skip_rerank:
            eff_rerank = False  # heuristic: fast lane usually skips rerank for speed
    
    meta["lane"] = lane
    meta["lane_reason"] = lane_decision.reason
    meta["lane_candidate"] = lane_decision.lane

    # Determine effective rerank status
    # We treat the passed 'enable_rerank' as a request, but mode can override.
    # Actually, usually the caller just calls rag_retrieve without args, so defaults apply.
    # We'll let mode dictate the default behavior.
    
    # Determine effective rerank status
    # routing decision `eff_rerank` might be overridden by budget/mode
    
    # We treat the passed 'enable_rerank' as a request, but mode can override.
    # Actually, usually the caller just calls rag_retrieve without args, so defaults apply.
    # We'll let mode dictate the default behavior.
    
    # eff_rerank = enable_rerank # start with argument logic -> No, router decided `eff_rerank` above based on lane
    
    # Logic: Lane > Mode? Or Mode > Lane? 
    # Usually: Lane sets the base ambition. Mode sets the infrastructure constraint.
    # If Lane=Fast (skip rerank), Mode=Gov (force rerank) -> What to do?
    # Correctness-first: If Gov mode (strict requirements), it likely shouldn't have been routed to Fast?
    # Actually, decide_lane checks strict conditions. If it became Fast, it means it's safe.
    # But let's respect Mode as "hard constraint".
    
    if mode == "eco":
        eff_rerank = False
        meta["rerank_skipped"] = True
        meta["rerank_skip_reason"] = "mode_eco"
    elif mode == "gov":
        eff_rerank = True
    elif mode == "auto":
        # Check deadline (budget)
        now = time.perf_counter()
        if now > deadline_ts:
            eff_rerank = False
            meta["rerank_skipped"] = True
            meta["rerank_skip_reason"] = "deadline_exceeded"
        else:
            # In auto, we default to True if budget allows, unless explicitly disabled?
            # Let's assume Auto means "Rerank if possible".
            eff_rerank = True

    # Update meta with final decision
    meta["enable_rerank"] = bool(eff_rerank)
    meta["rerank_top_k"] = int(rerank_top_k)

    tenant_epoch = 0
    epoch_healthy = False
    if enable_cache:
        tenant_epoch, epoch_healthy = await cache_get_tenant_epoch(tenant_id)
    meta["tenant_epoch"] = int(tenant_epoch)

    cache_key = _make_cache_key(
        tenant_id=tenant_id,
        agent_id=agent_id,
        query=q,
        filters=filters,
        top_k=top_k,
        enable_rerank=eff_rerank, # Use effective rerank for cache key
        rerank_top_k=rerank_top_k,
        gate_top_n=gate_top_n,
        max_total_chars=max_total_chars,
        max_chunk_chars=max_chunk_chars,
        dedup=dedup,
        max_chunks=max_chunks,
        max_per_document=max_per_document,
        include_scores=include_scores,
        include_scores_in_prompt=include_scores_in_prompt,
        prefer_parent_text=prefer_parent_text,
        tenant_epoch=int(tenant_epoch),
    )
    meta["cache_key_sha1"] = _sha1(cache_key)
    cache_allowed = bool(enable_cache and epoch_healthy)
    meta["cache_enabled"] = bool(cache_allowed)
    if enable_cache and not epoch_healthy:
        meta["cache_skip_reason"] = "tenant_epoch_unavailable"

    # 1) Cache get
    if cache_allowed:
        t_cache = time.perf_counter()
        cached = await cache_get(cache_key)
        meta["cache_get_ms"] = int((time.perf_counter() - t_cache) * 1000)
        if cached:
            try:
                payload = json.loads(cached)
                citations = [Citation(**c) for c in payload.get("citations", [])]
                out = RagPipelineResult(
                    context=str(payload.get("context", "")),
                    citations=citations,
                    meta={
                        **meta,
                        **(payload.get("meta") or {}),
                        "cache_hit": True,
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                    },
                )
                _log_trace(
                    {
                        "trace_id": trace_id,
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "ok": bool(out.context),
                        "cache_hit": True,
                        "latency_ms": out.meta.get("latency_ms"),
                        "citations_count": len(out.citations),
                    }
                )
                return out
            except Exception as e:
                logger.warning("Cache parse failed, ignore cache. err=%s", e)

    async def _attempt(
        *,
        attempt_idx: int,
        eff_top_k: int,
        eff_filters: Optional[RetrievalFilters],
        eff_enable_rerank: bool,
    ) -> Tuple[Optional[RagPipelineResult], Dict[str, Any]]:
        t_attempt0 = time.perf_counter()

        attempt_meta: Dict[str, Any] = {
            "attempt": attempt_idx,
            "eff_top_k": int(eff_top_k),
            "eff_rerank": bool(eff_enable_rerank),
        }

        # 2) Retrieve
        t_ret = time.perf_counter()
        rr: RetrieveResult = await retrieve(
            db,
            tenant_id=tenant_id,
            agent_id=agent_id,
            query=q,
            top_k=int(eff_top_k),
            filters=eff_filters,
            user_context=user_context,
        )
        attempt_meta["retrieve_ms"] = int((time.perf_counter() - t_ret) * 1000)
        attempt_meta["hits"] = len(rr.chunks)
        attempt_meta["retrieve_debug"] = rr.debug  # keep full in meta (debugging)
        attempt_meta["used_tools"] = rr.used_tools

        if not rr.chunks:
            attempt_meta["attempt_total_ms"] = int((time.perf_counter() - t_attempt0) * 1000)
            GATE_FAIL_TOTAL.labels(agent_id=agent_id, reason="no_hits").inc()
            return None, {**attempt_meta, "reason": "no_hits"}

        code_like = _is_code_like(rr.debug)
        attempt_meta["code_like"] = code_like

        chunks = rr.chunks

        # 3) Rerank BEFORE gate
        if eff_enable_rerank:
            # Auto mode: check deadline again after retrieval
            if mode == "auto" and time.perf_counter() > deadline_ts:
                attempt_meta["rerank_skipped"] = True
                attempt_meta["rerank_skip_reason"] = "deadline_exceeded"
            else:
                t_re = time.perf_counter()
                # Auto prefer parent evidence for code-like queries
                rerank_prefer_parent = bool(prefer_parent_text) or bool(code_like)
                chunks, ok_rerank = await _maybe_rerank(
                    query=q,
                    chunks=chunks,
                    top_k=int(rerank_top_k),
                    prefer_parent_text=rerank_prefer_parent,
                )
                attempt_meta["rerank_ms"] = int((time.perf_counter() - t_re) * 1000)
                attempt_meta["rerank_ok"] = bool(ok_rerank)
                attempt_meta["rerank_prefer_parent_text"] = rerank_prefer_parent
        else:
            chunks = chunks[: int(rerank_top_k)]
            attempt_meta["rerank_ok"] = False

        # 4) Gate on top gate_top_n
        gate_chunks = chunks[: max(1, int(gate_top_n))]
        ok, gate_info = _evaluate_evidence(query=q, chunks=gate_chunks)
        attempt_meta["evidence_ok"] = bool(ok)
        attempt_meta["evidence_info"] = gate_info

        if not ok:
            attempt_meta["attempt_total_ms"] = int((time.perf_counter() - t_attempt0) * 1000)
            GATE_FAIL_TOTAL.labels(agent_id=agent_id, reason="low_evidence").inc()
            return None, {**attempt_meta, "reason": "low_evidence"}

        # 5) Build context (only after gate)
        t_ctx = time.perf_counter()
        ctx_res: ContextBuildResult = build_context(
            chunks,
            rr.doc_map,
            max_total_chars=max_total_chars,
            max_chunk_chars=max_chunk_chars,
            dedup=dedup,
            max_chunks=max_chunks,
            max_per_document=max_per_document,
            include_scores=include_scores,
            include_scores_in_prompt=include_scores_in_prompt,
            prefer_parent_text=prefer_parent_text,
        )
        attempt_meta["context_ms"] = int((time.perf_counter() - t_ctx) * 1000)
        attempt_meta["context_stats"] = ctx_res.stats

        if not ctx_res.context:
            attempt_meta["attempt_total_ms"] = int((time.perf_counter() - t_attempt0) * 1000)
            GATE_FAIL_TOTAL.labels(agent_id=agent_id, reason="missing_context").inc()
            return None, {**attempt_meta, "reason": "context_empty"}

        # 6) Citations sync with used_chunks
        t_cit = time.perf_counter()
        citations = _build_citations_safe(
            ctx_res.used_chunks,
            rr.doc_map,
            prefer_parent_text=bool(prefer_parent_text),
        )
        attempt_meta["citations_ms"] = int((time.perf_counter() - t_cit) * 1000)
        attempt_meta["citations_count"] = len(citations)

        attempt_meta["used_doc_ids"] = list(
            {str(ch.get("document_id") or "") for ch in ctx_res.used_chunks if ch.get("document_id")}
        )

        attempt_meta["attempt_total_ms"] = int((time.perf_counter() - t_attempt0) * 1000)

        result = RagPipelineResult(context=ctx_res.context, citations=citations, meta=attempt_meta)
        return result, attempt_meta

        result = RagPipelineResult(context=ctx_res.context, citations=citations, meta=attempt_meta)
        return result, attempt_meta

    # ----------------------------------------------------------------------
    # Execution Strategy (Fast Lane with Fallback)
    # ----------------------------------------------------------------------
    
    attempt_results: List[Dict[str, Any]] = []
    
    # Attempt 0: Primary Lane
    res, m0 = await _attempt(
        attempt_idx=0,
        eff_top_k=int(eff_top_k) if lane == "fast" else int(top_k), # Lane knob vs passed default
        eff_filters=filters,
        eff_enable_rerank=bool(eff_rerank),
    )
    attempt_results.append(m0)

    # Fallback Logic: FAST -> STRICT
    # Condition: FAST lane used AND Gate Failed (reason=low_evidence)
    # Note: res is None if failed
    
    do_fallback = False
    if lane == "fast" and res is None:
        reason = m0.get("reason")
        if reason in ("low_evidence", "no_hits", "context_empty"):
            do_fallback = True
            m0["fallback_triggered"] = True
            
    if do_fallback:
        # Fallback to STRICT knobs
        fallback_top_k = int(top_k) # Original request
        fallback_rerank = bool(enable_rerank) or True # Usually Strict implies Rerank enabled if available
        # But verify with auto mode budget? 
        # For correctness, we favor rerank in strict fallback even if slightly over budget? 
        # Or respect auto mode? Let's respect basic auto mode constraints (done inside _attempt logic if we simply reset flags?)
        # Actually _attempt doesn't verify mode/budget again inside it (except rerank step check).
        
        # Let's just use the strict parameters (enable_rerank from args)
        if mode == "eco": 
            fallback_rerank = False

        res, m1 = await _attempt(
            attempt_idx=1,
            eff_top_k=fallback_top_k,
            eff_filters=filters,
            eff_enable_rerank=fallback_rerank,
        )
        m1["fallback_from"] = "fast"
        attempt_results.append(m1)

    # Auto Retry (Broaden) logic for STRICT failures (or failed fallback)
    # Only if we haven't succeeded yet and retry is enabled
    if res is None and enable_retry and not (lane == "fast" and not do_fallback): 
        #If it was FAST and we didn't fallback (e.g. error?) -> maybe retry? 
        # Simplify: If res is None, try broaden.
        
        # Avoid double-retry if we just did fallback (which effectively is a retry)
        # If we did fallback (attempt 1) and it failed -> try broaden (attempt 2)? allowable.
        
        # Let's keep existing logic but adapted
        
        should_retry = True
        # If we just did fallback, we might want to stop or continue. 
        # Standard: Broaden search is a valid next step.
        
        if should_retry:
            idx = len(attempt_results)
            eff_filters = filters
            if relax_filters_on_retry and filters is not None:
                try:
                    eff_filters = filters.model_copy(update={"doc_type": None, "domain": None})
                except Exception:
                    eff_filters = filters

            eff_enable_rerank_retry = bool(eff_rerank) or bool(force_rerank_on_retry)
            if mode == "eco":
                eff_enable_rerank_retry = False
            
            # Use strict/broad parameters
            retry_top_k = max(int(broaden_top_k), int(top_k))
            
            res, m_retry = await _attempt(
                attempt_idx=idx,
                eff_top_k=retry_top_k,
                eff_filters=eff_filters,
                eff_enable_rerank=eff_enable_rerank_retry,
            )
            attempt_results.append(m_retry)

    if res is None:
        meta["attempts"] = attempt_results
        meta["cache_hit"] = False
        meta["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        meta["reason"] = attempt_results[-1].get("reason") if attempt_results else "failed"

        # structured log (failed)
        _log_trace(
            {
                "trace_id": trace_id,
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "ok": False,
                "cache_hit": False,
                "reason": meta.get("reason"),
                "latency_ms": meta.get("latency_ms"),
                "query_sha1": meta.get("query_sha1"),
                "attempts": [
                    {
                        "attempt": a.get("attempt"),
                        "reason": a.get("reason"),
                        "hits": a.get("hits"),
                        "retrieve_ms": a.get("retrieve_ms"),
                        "rerank_ms": a.get("rerank_ms"),
                        "context_ms": a.get("context_ms"),
                        "attempt_total_ms": a.get("attempt_total_ms"),
                        "code_like": a.get("code_like"),
                        "evidence_ok": a.get("evidence_ok"),
                        "evidence_info": a.get("evidence_info"),
                        "used_tools": a.get("used_tools"),
                        "retrieve_debug": _safe_debug(a.get("retrieve_debug")),
                    }
                    for a in attempt_results
                ],
            }
        )

        return RagPipelineResult(context="", citations=[], meta=meta)

    merged_meta = {
        **meta,
        "attempts": attempt_results,
        **(res.meta or {}),
        "cache_hit": False,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
    out = RagPipelineResult(context=res.context, citations=res.citations, meta=merged_meta)

    # 7) Cache set (best-effort)
    if cache_allowed and out.context:
        t_cs = time.perf_counter()
        ok_set = False
        try:
            payload = {
                "context": out.context,
                "citations": [c.model_dump(exclude_none=True) for c in out.citations],
                "meta": {k: v for k, v in out.meta.items() if k not in {"tenant_id"}},
            }
            await cache_set(
                cache_key,
                json.dumps(payload, ensure_ascii=False),
                ttl_seconds=int(cache_ttl_seconds),
            )
            ok_set = True
        except Exception as e:
            logger.warning("Cache set failed, ignore. err=%s", e)
        finally:
            out.meta["cache_set_ms"] = int((time.perf_counter() - t_cs) * 1000)
            out.meta["cache_set_ok"] = ok_set

    # structured log (success)
    _log_trace(
        {
            "trace_id": trace_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "ok": True,
            "cache_hit": False,
            "latency_ms": out.meta.get("latency_ms"),
            "citations_count": len(out.citations),
            "query_sha1": out.meta.get("query_sha1"),
            "cache_set_ms": out.meta.get("cache_set_ms"),
            "cache_set_ok": out.meta.get("cache_set_ok"),
            "attempts": [
                {
                    "attempt": a.get("attempt"),
                    "reason": a.get("reason"),
                    "hits": a.get("hits"),
                    "retrieve_ms": a.get("retrieve_ms"),
                    "rerank_ms": a.get("rerank_ms"),
                    "context_ms": a.get("context_ms"),
                    "citations_ms": a.get("citations_ms"),
                    "citations_count": a.get("citations_count"),
                    "attempt_total_ms": a.get("attempt_total_ms"),
                    "code_like": a.get("code_like"),
                    "evidence_ok": a.get("evidence_ok"),
                    "evidence_info": a.get("evidence_info"),
                    "used_tools": a.get("used_tools"),
                    "retrieve_debug": _safe_debug(a.get("retrieve_debug")),
                    "used_doc_ids_count": len(a.get("used_doc_ids") or []),
                }
                for a in (out.meta.get("attempts") or [])
            ],
        }
    )

    return out
