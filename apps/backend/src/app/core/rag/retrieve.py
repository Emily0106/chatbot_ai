# app/core/rag/retrieve.py
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm import embed_query
from app.core.db_vector import search_hybrid_chunks  # Qdrant: dense + sparse + fusion
from app.core.db_sql import fetch_chunks_by_ids
from app.schemas.chat import RetrievalFilters
from app.core.policy.types import UserContext
from app.core.policy.manager import PolicyManager
from app.core.rag.qdrant_filter_builder import QdrantStrictFilterBuilder, PermissionError
from fastapi import HTTPException

STRICT_BUILDER = QdrantStrictFilterBuilder()
from app.core.rag.evidence import EvidenceGate, GateDecision
from app.core.rag.query_expansion.engine import QueryExpansionEngine
from app.core.rag.query_expansion.schemas import QueryExpansionConfig
from app.core.rag.query_expansion.lexicon_repo import LexiconRepo
from app.core.rag.query_expansion.llm_rewriter import LLMRewriter


# ... (inside retrieve function)



# Optional lexical module (Postgres FTS / trigram)
try:
    from app.core.db_lexical import search_lexical_chunks, is_code_query
    _HAS_LEXICAL = True
except Exception:
    search_lexical_chunks = None  # type: ignore
    is_code_query = None  # type: ignore
    _HAS_LEXICAL = False

logger = logging.getLogger(__name__)

HitA = Tuple[str, float, Dict[str, Any]]  # (chunk_id, score, payload)
HitB = Dict[str, Any]
RawHits = Union[List[HitA], List[HitB]]


@dataclass(frozen=True)
class RetrieveResult:
    chunks: List[Dict[str, Any]]
    doc_map: Dict[str, Dict[str, Any]]
    used_tools: List[str]
    debug: Dict[str, Any]
    gate_decision: Optional[GateDecision] = None


# -------------------------
# Helpers
# -------------------------
def _normalize_text_for_cache(s: str) -> str:
    return " ".join((s or "").strip().split())


def _coerce_hits(hits: Any) -> List[HitA]:
    """Normalize hits to [(chunk_id, score, payload), ...]."""
    if not hits:
        return []

    out: List[HitA] = []

    if isinstance(hits, list) and hits and isinstance(hits[0], tuple):
        for item in hits:
            if not isinstance(item, tuple) or len(item) < 2:
                continue
            cid, score = item[0], item[1]
            payload = item[2] if len(item) > 2 else {}
            out.append((str(cid), float(score), dict(payload or {})))
        return out

    if isinstance(hits, list) and hits and isinstance(hits[0], dict):
        for item in hits:
            if not isinstance(item, dict):
                continue
            cid = item.get("id") or item.get("chunk_id") or item.get("point_id")
            if cid is None:
                continue
            score = float(item.get("score", 0.0))
            payload = dict(item.get("payload") or {})
            out.append((str(cid), score, payload))
        return out

    return []


def _unique_preserve_order(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for v in values:
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _reorder_rows_by_ids(rows: List[Dict[str, Any]], ids: List[str]) -> List[Dict[str, Any]]:
    """SQL IN (...) does not preserve order. Reorder by ids."""
    mp = {str(r.get("chunk_id") or ""): r for r in rows}
    out: List[Dict[str, Any]] = []
    for cid in ids:
        r = mp.get(cid)
        if r is not None:
            out.append(r)
    return out


def _ensure_payload_kind(payload: Dict[str, Any], *, default_kind: str, default_mode: str) -> Dict[str, Any]:
    """Guarantee payload contains _score_kind/_score_mode for downstream context/evaluator."""
    p = dict(payload or {})
    p.setdefault("_score_kind", default_kind)
    p.setdefault("_score_mode", default_mode)
    return p


def _rrf_fuse(
    a: List[HitA],
    b: List[HitA],
    *,
    top_k: int,
    rrf_k: int = 60,
    w_a: float = 1.0,
    w_b: float = 1.0,
    mode: str = "rrf",
) -> List[HitA]:
    """
    Reciprocal Rank Fusion: scale-invariant, rank-based.
    score(cid) = Σ weight * 1/(k + rank)
    """
    scores: Dict[str, float] = {}
    payloads: Dict[str, Dict[str, Any]] = {}

    def add(lst: List[HitA], weight: float, source_tag: str) -> None:
        for rank, (cid, _s, p) in enumerate(lst, start=1):
            scores[cid] = scores.get(cid, 0.0) + weight * (1.0 / (rrf_k + rank))
            if cid not in payloads:
                payloads[cid] = dict(p or {})
            else:
                payloads[cid].update(dict(p or {}))

            payloads[cid].setdefault("_sources", [])
            if isinstance(payloads[cid]["_sources"], list) and source_tag not in payloads[cid]["_sources"]:
                payloads[cid]["_sources"].append(source_tag)

    add(a, w_a, "lexical")
    add(b, w_b, "hybrid")

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    out: List[HitA] = []
    for cid, sc in ranked:
        p = payloads.get(cid, {})
        p["_score_kind"] = "rrf"
        p["_score_mode"] = mode
        out.append((cid, float(sc), p))
    return out


async def _fetch_documents_meta_bulk(
    db: AsyncSession,
    *,
    tenant_id: str,
    document_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """
    Keep it configurable because schemas differ a lot.
    Defaults assume:
      - table: documents
      - id column: id (uuid/int) or document_id (text)
      - title, file_url columns exist
    You can override via settings:
      DOCUMENTS_TABLE, DOCUMENT_ID_COL, DOCUMENT_TITLE_COL, DOCUMENT_FILE_URL_COL, DOCUMENT_TENANT_COL
    """
    if not document_ids:
        return {}

    DOCS_TABLE = getattr(settings, "DOCUMENTS_TABLE", "documents")
    DOC_ID_COL = getattr(settings, "DOCUMENT_ID_COL", "id")
    DOC_TITLE_COL = getattr(settings, "DOCUMENT_TITLE_COL", "title")
    DOC_URL_COL = getattr(settings, "DOCUMENT_FILE_URL_COL", "file_url")
    DOC_TENANT_COL = getattr(settings, "DOCUMENT_TENANT_COL", "tenant_id")

    sql = text(
        f"""
        SELECT
          doc_id::text AS document_id,
          title AS title,
          source_uri AS file_url
        FROM {DOCS_TABLE}
        WHERE doc_id::text = ANY(:doc_ids)
          AND {DOC_TENANT_COL} = :tenant_id
        """
    )
    res = await db.execute(sql, {"doc_ids": document_ids, "tenant_id": tenant_id})
    rows = [dict(r) for r in res.mappings().all()]
    return {str(r["document_id"]): r for r in rows}


# -------------------------
# Main retrieve
# -------------------------
async def retrieve(
    db: AsyncSession,
    *,
    tenant_id: str,
    agent_id: str,
    query: str,
    top_k: int = 30,
    filters: Optional[RetrievalFilters] = None,
    user_security_level: int = 1,
    user_context: Optional[Dict[str, Any]] = None,
) -> RetrieveResult:
    """
    Production retrieval:
      1) Hybrid in Qdrant (dense+sparse+fusion)
      2) Optional lexical in Postgres (FTS/trgm) for code-like queries
      3) Parallel execution (asyncio.gather)
      4) Fuse via RRF (rank-based, avoids score-scale drift)
      5) SQL fetch chunks by ids + reorder to fused order
      6) SQL fetch doc meta bulk
    """
    t0 = time.perf_counter()
    used_tools: List[str] = []
    debug: Dict[str, Any] = {"agent_id": agent_id, "top_k": int(top_k)}

    q_raw = (query or "").strip()
    if not q_raw:
        return RetrieveResult(chunks=[], doc_map={}, used_tools=used_tools, debug={**debug, "reason": "empty_query"})

    q = q_raw
    filters = filters or RetrievalFilters()

    # ---------------------------------------------------------
    # PR-BE-2.1: Strict Policy Enforcement
    # ---------------------------------------------------------
    # 1. Construct UserContext
    # We default security_level to 1 if not provided
    u_ctx = UserContext(
        tenant_id=tenant_id,
        department_id=(user_context or {}).get("department_id"),
        geo_code=(user_context or {}).get("geo_code"),
        security_level=int(user_security_level or 1),
    )

    # 2. Policy Enforce (Gatekeeper)
    # Allows generic_agent for now; chat.py passes proper agent_id in retrieval
    # Policy manager uses agent_id to load specific policies
    policy_res = PolicyManager.enforce_filters(agent_id, u_ctx, filters)
    
    if policy_res["policy_meta"].get("conflict"):
        # Fail Closed on Conflict
        raise HTTPException(
            status_code=403, 
            detail={"code": "ERR_POLICY_CONFLICT", "message": "Policy Conflict Detected"}
        )

    # 2.5 Query Expansion Integration
    import os
    enable_qe = os.getenv("ENABLE_QUERY_EXPANSION", "0") == "1"
    pack = None
    if enable_qe:
        try:
            t_qe = time.perf_counter()
            engine = QueryExpansionEngine(
                cfg=QueryExpansionConfig(),
                lexicon_repo=LexiconRepo(db),
                llm_rewriter=LLMRewriter()
            )
            pack = await engine.expand(q, user_ctx=u_ctx, agent_policy=policy_res)
            # Override current query string with normalized expansion for single-search fallback test
            q = pack.normalized_query
            debug["query_expanded"] = True
            debug["query_expansion_ms"] = int((time.perf_counter() - t_qe) * 1000)
            
            # Pack all query expansion observability metrics into a single audit dictionary
            # Schema merges standard audit dictionary + strict debug values (LLM / Flags / Counts)
            variant_counts_map = {"ORIGINAL": 1}
            for v in pack.variants:
                src = str(v.source).replace("VariantSource.", "")
                variant_counts_map[src] = variant_counts_map.get(src, 0) + 1
                  
            debug["query_expansion_audit"] = {
                "expansion_applied": pack.audit.get("expansion_applied", False),
                "variants_count": pack.audit.get("variants_count", 0) + 1, # +1 for Original
                "variant_sources": variant_counts_map,
                "llm_used": pack.debug.get("llm_used", False),
                "llm_timeout": pack.debug.get("llm_timeout", False),
                "lexicon_version": pack.debug.get("lexicon_version", "0"),
                "contains_pii": pack.flags.get("contains_pii", False), # Raw strings not logged
                "injection_suspected": pack.flags.get("injection_suspected", False),
                "is_code_query": pack.flags.get("is_code_query", False),
                "must_keep_tokens_count": len(pack.must_keep_tokens)
            }
            used_tools.append("query_expansion")
        except Exception as e:
            logger.warning("Query expansion failed (fail-soft): %s", e)
            debug["query_expanded"] = False
            debug["qe_error"] = str(e)

    # Variants to process
    search_variants = []
    if pack and pack.variants:
        for v in pack.variants:
            search_variants.append({"query": v.text, "weight": v.weight})
    else:
        # Fallback to single q
        search_variants.append({"query": q, "weight": 1.0})

    # 3. Build Safe Qdrant Filter
    try:
        q_filter = STRICT_BUILDER.build(u_ctx, policy_res["filters"])
    except PermissionError as e:
        raise HTTPException(
            status_code=403, 
            detail={"code": "ERR_POLICY_DENIED", "message": str(e)}
        )
    except Exception as e:
         raise HTTPException(
            status_code=403, 
            detail={"code": "ERR_CONTEXT_MISSING", "message": str(e)}
        )

    # Context extracted vars for Lexical (Legacy vars)
    # We keep them for lexical search compatibility IF lexical supports q_filter?
    # lexical search usually uses simple filters.
    # Current lexical search: doc_type, domain, security_level.
    # We should extract them from policy_res["filters"] just for lexical?
    # Or update lexical to ignore them if strict?
    # For now, we reuse the loose variables for lexical, OR we pass q_filter if supported.
    # search_lexical_chunks signature: calls db_lexical.py.
    # Likely db_lexical doesn't support q_filter.
    # Let's extract SAFE values from policy_res["filters"] for lexical.
    
    final_filters = policy_res["filters"]
    lexical_scope = str(final_filters.get("scope") or "public").strip().lower()
    debug["lexical_scope"] = lexical_scope
    eff_doc_type = final_filters.get("doc_type") # List or Str
    # Lexical might expect str.
    if isinstance(eff_doc_type, list): 
        eff_doc_type = eff_doc_type[0] if eff_doc_type else None
    
    eff_domain = final_filters.get("domain")
    # Security level is handled by checking u_ctx against doc level? 
    # db_lexical usually takes security_level argument.
    
    security_level = int(user_security_level)

    # Decide lexical
    code_like = False
    if _HAS_LEXICAL and is_code_query is not None:
        try:
            code_like = bool(is_code_query(q))
        except Exception:
            code_like = False
    debug["code_like"] = code_like
    debug["lexical_available"] = bool(_HAS_LEXICAL)

    # Tuning knobs
    prefetch_base = int(getattr(settings, "QDRANT_PREFETCH_K", 60) or 60)
    prefetch_k = prefetch_base * (2 if code_like else 1)

    lexical_pool_default = max(60, int(top_k) * 2)
    lexical_top_k = int(getattr(settings, "LEXICAL_TOP_K", lexical_pool_default) or lexical_pool_default)

    rrf_k = int(getattr(settings, "RRF_K", 60) or 60)
    w_lex = float(getattr(settings, "RRF_WEIGHT_LEXICAL", 1.0))
    w_hyb = float(getattr(settings, "RRF_WEIGHT_HYBRID", 1.0))

    hybrid_timeout_s = float(getattr(settings, "HYBRID_TIMEOUT_S", 8.0) or 8.0)
    lexical_timeout_s = float(getattr(settings, "LEXICAL_TIMEOUT_S", 4.0) or 4.0)

    debug.update(
        {
            "prefetch_k": int(prefetch_k),
            "lexical_top_k": int(lexical_top_k),
            "rrf_k": int(rrf_k),
            "w_lex": float(w_lex),
            "w_hyb": float(w_hyb),
        }
    )

    # Dense embed function (per-request cache)
    _dense_cache: Dict[str, List[float]] = {}
    _embed_logged = False

    async def dense_embed_fn(text_in: str) -> List[float]:
        nonlocal _embed_logged
        key = _normalize_text_for_cache(text_in)
        if key in _dense_cache:
            return _dense_cache[key]

        t_embed = time.perf_counter()
        try:
            vecs = await embed_query(text_in)
        except Exception as e:
            logger.warning("embed_query failed: %s", e)
            vecs = []
        ms = int((time.perf_counter() - t_embed) * 1000)

        if not _embed_logged:
             used_tools.append("embedding")
             debug["embed_ms"] = ms
             _embed_logged = True

        _dense_cache[key] = vecs
        return _dense_cache[key]

    # ---- parallel search ----
    t_search = time.perf_counter()

    hybrid_sem = asyncio.Semaphore(6)
    
    async def run_hybrid_single(variant_query: str, weight: float) -> List[HitA]:
        async with hybrid_sem:
            raw: RawHits = await search_hybrid_chunks(
                query=variant_query,
                dense_embed_fn=dense_embed_fn,
                tenant_id=tenant_id,
                top_k=int(top_k),
                prefetch_k=int(prefetch_k),
                q_filter=q_filter,
                mode="hybrid",
            )
            hits = _coerce_hits(raw)
            # Scale score by variant weight
            return [(cid, float(s) * weight, _ensure_payload_kind(p, default_kind="unknown", default_mode="hybrid")) for cid, s, p in hits]

    async def run_hybrid() -> List[HitA]:
        coros = [run_hybrid_single(v["query"], v["weight"]) for v in search_variants]
        results = await asyncio.gather(*coros, return_exceptions=True)
        
        all_hits = []
        for res in results:
            if isinstance(res, Exception):
                logger.warning("Hybrid variant failed: %s", res)
            else:
                all_hits.extend(res)
                
        # Dedupe by chunk_id, keep highest score
        unique_hits = {}
        for cid, s, p in all_hits:
            if cid not in unique_hits or s > unique_hits[cid][1]:
                unique_hits[cid] = (cid, s, p)
                
        sorted_hits = sorted(unique_hits.values(), key=lambda x: x[1], reverse=True)
        return sorted_hits[:int(top_k)]

    async def run_lexical() -> List[HitA]:
        if not code_like:
            debug["lexical_skip_reason"] = "not_code_like"
            return []
        if not (_HAS_LEXICAL and search_lexical_chunks is not None):
            debug["lexical_skip_reason"] = "lexical_unavailable"
            return []
        if lexical_scope != "public":
            # Keep lane fail-safe while surfacing explicit reason to router/meta.
            debug["lexical_skip_reason"] = "scope_not_public"
            return []

        # Secure Lexical Lane (Unified Policy)
        raw: RawHits = await search_lexical_chunks(
            db,
            query=q,
            tenant_id=tenant_id,
            top_k=int(lexical_top_k),
            filters=final_filters, # Enforce PolicyManager filters
            security_level=security_level,
            variants=search_variants  # Execute OR tsquery
        )
        hits = _coerce_hits(raw)
        return [(cid, s, _ensure_payload_kind(p, default_kind="lexical", default_mode="lexical")) for cid, s, p in hits]

    tasks: List[asyncio.Task] = []
    tasks.append(asyncio.create_task(asyncio.wait_for(run_hybrid(), timeout=hybrid_timeout_s)))
    if code_like and _HAS_LEXICAL and search_lexical_chunks is not None:
        tasks.append(asyncio.create_task(asyncio.wait_for(run_lexical(), timeout=lexical_timeout_s)))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    hybrid_hits: List[HitA] = []
    lexical_hits: List[HitA] = []

    # hybrid result is always index 0
    if isinstance(results[0], Exception):
        logger.exception("Hybrid search failed tenant=%s agent=%s: %s", tenant_id, agent_id, results[0])
        used_tools.append("hybrid_search_failed")
        debug["hybrid_error"] = type(results[0]).__name__
        debug["search_ms"] = int((time.perf_counter() - t_search) * 1000)
        debug["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        return RetrieveResult(chunks=[], doc_map={}, used_tools=used_tools, debug=debug)

    hybrid_hits = results[0]
    used_tools.append("hybrid_search")

    if len(results) > 1:
        if isinstance(results[1], Exception):
            logger.warning("Lexical search failed (non-fatal): %s", results[1])
            used_tools.append("lexical_search_failed")
            debug["lexical_error"] = type(results[1]).__name__
            if "lexical_skip_reason" not in debug:
                debug["lexical_skip_reason"] = "lexical_runtime_error"
            lexical_hits = []
        else:
            lexical_hits = results[1]
            used_tools.append("lexical_search")
            debug.pop("lexical_skip_reason", None)

    debug["search_ms"] = int((time.perf_counter() - t_search) * 1000)
    debug["hybrid_hits"] = len(hybrid_hits)
    debug["lexical_hits"] = len(lexical_hits)

    # ---- fuse ----
    fusion_mode = "hybrid_only"
    fused_hits: List[HitA] = hybrid_hits

    if code_like and lexical_hits:
        # Boost Lexical for Code Queries: 0.7 vs 0.3 effective weight?
        # Standard RRF doesn't normalize weights easily, but we can bump w_lex.
        # If user explicitly asked for "Lexical score (0.7)", we assume they mean
        # relative importance.
        eff_w_lex = w_lex * 2.0  # Double importance of lexical matches
        eff_w_hyb = w_hyb * 1.0

        fused_hits = _rrf_fuse(
            lexical_hits,
            hybrid_hits,
            top_k=int(top_k),
            rrf_k=int(rrf_k),
            w_a=float(eff_w_lex),
            w_b=float(eff_w_hyb),
            mode="rrf_lexical_hybrid",
        )
        fusion_mode = "rrf_lexical_hybrid"

    debug["fusion_mode"] = fusion_mode
    debug["hits"] = len(fused_hits)

    if not fused_hits:
        debug["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        return RetrieveResult(chunks=[], doc_map={}, used_tools=used_tools, debug={**debug, "reason": "no_hits"})

    # ---- fetch chunks from SQL + reorder ----
    chunk_ids = _unique_preserve_order([cid for cid, _s, _p in fused_hits])
    score_map = {cid: float(score) for cid, score, _p in fused_hits}
    payload_map = {cid: dict(payload or {}) for cid, _s, payload in fused_hits}

    t_sql_chunks = time.perf_counter()
    try:
        # IMPORTANT FIX: match db_sql.fetch_chunks_by_ids signature
        rows = await fetch_chunks_by_ids(
            db, 
            tenant_id=tenant_id, 
            chunk_ids=chunk_ids,
            security_level=security_level
        )
        used_tools.append("sql_hydrate_chunks")
    except Exception as e:
        logger.exception("fetch_chunks_by_ids failed: %s", e)
        # Rollback transaction to prevent cascade errors
        try:
            await db.rollback()
        except Exception:
            pass
        used_tools.append("sql_hydrate_chunks_failed")
        debug["sql_chunks_error"] = type(e).__name__
        debug["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        return RetrieveResult(chunks=[], doc_map={}, used_tools=used_tools, debug=debug)

    debug["sql_chunks_ms"] = int((time.perf_counter() - t_sql_chunks) * 1000)
    debug["chunks_fetched"] = len(rows)

    if not rows:
        debug["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        return RetrieveResult(chunks=[], doc_map={}, used_tools=used_tools, debug={**debug, "reason": "chunks_not_found"})

    chunks = _reorder_rows_by_ids(rows, chunk_ids)

    # attach score + payload to each chunk (for evaluator/context builder)
    for ch in chunks:
        cid = str(ch.get("chunk_id") or "")
        ch["score"] = score_map.get(cid)

        p = payload_map.get(cid, {})
        if p:
            base = ch.get("payload") or {}
            if not isinstance(base, dict):
                base = {}
            ch["payload"] = {**base, **p}

    # ---- RERANKING REMOVED (Moved to pipeline.py) ----
    # retrieve.py only handles retrieval + fusion + fetch.
    # Reranking is now strictly controlled by pipeline.py to avoid double-work.
    
    # Just pass through chunks
    pass

    # ---- fetch docs meta ----
    t_sql_docs = time.perf_counter()
    doc_map: Dict[str, Dict[str, Any]] = {}
    try:
        doc_ids = _unique_preserve_order([str(ch.get("document_id") or "") for ch in chunks if ch.get("document_id")])
        doc_map = await _fetch_documents_meta_bulk(db, tenant_id=tenant_id, document_ids=doc_ids)
        used_tools.append("sql_hydrate_docs")
    except Exception as e:
        logger.warning("fetch docs meta failed (non-fatal): %s", e)
        used_tools.append("sql_hydrate_docs_failed")
        debug["sql_docs_error"] = type(e).__name__

    debug["sql_docs_ms"] = int((time.perf_counter() - t_sql_docs) * 1000)
    debug["docs_fetched"] = len(doc_map)

    debug["docs_fetched"] = len(doc_map)
    
    # ---- PR-BE-3.2: Upstream Evidence Gating (Gate Blindness Fix) ----
    # Evaluate with full metadata context (including _score_kind)
    gate = EvidenceGate()
    gate_decision = gate.evaluate(chunks)
    debug["gate_status"] = gate_decision.status
    debug["gate_reason"] = gate_decision.reason

    debug["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    return RetrieveResult(
        chunks=chunks, 
        doc_map=doc_map, 
        used_tools=used_tools, 
        debug=debug,
        gate_decision=gate_decision
    )
