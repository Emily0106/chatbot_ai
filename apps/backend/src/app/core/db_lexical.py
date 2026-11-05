# app/core/db_lexical.py
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

# ---- Defaults aligned with current ingestion schema ----
CHUNKS_TABLE = getattr(settings, "CHUNKS_TABLE", "chunks")
CHUNK_ID_COL = getattr(settings, "CHUNK_ID_COL", "chunk_id")
DISPLAY_TEXT_COL = getattr(settings, "CHUNK_DISPLAY_TEXT_COL", "display_text")
EMBED_TEXT_COL = getattr(settings, "CHUNK_EMBED_TEXT_COL", "embed_text")
TENANT_COL = getattr(settings, "CHUNK_TENANT_COL", "commune_id")
DOC_TYPE_COL = getattr(settings, "CHUNK_DOC_TYPE_COL", "doc_category")
DOCUMENT_ID_COL = getattr(settings, "CHUNK_DOCUMENT_ID_COL", "doc_id")
SCOPE_COL = getattr(settings, "CHUNK_SCOPE_COL", "scope")

ENABLE_ILIKE_FALLBACK = str(getattr(settings, "LEXICAL_ENABLE_ILIKE_FALLBACK", "1")) != "0"
FTS_CONFIG = getattr(settings, "LEXICAL_FTS_CONFIG", "simple")
ALLOWED_FTS_CONFIGS = {"simple", "english"}

_CODELIKE_RE = re.compile(
    r"(?ix)"
    r"("
    r"\b\d{1,4}/\d{2,4}\b|"
    r"\b\d{1,4}/\d{2,4}/[A-ZĐ\-]+|"
    r"(nd|tt|qd|qđ|ubnd|hđnd)\b|"
    r"mẫu\s*số\s*\d+|"
    r"điều\s*\d+(\s*khoản\s*\d+)?|"
    r"[A-Z]{1,6}-\d{1,6}|"
    r"\d+[\/\-\._]\d+"
    r")"
)


def is_code_query(query: str) -> bool:
    q = (query or "").strip()
    return bool(q and _CODELIKE_RE.search(q))


def _safe_fts_config(value: str) -> str:
    cfg = (value or "simple").strip().lower()
    if cfg not in ALLOWED_FTS_CONFIGS:
        logger.warning("Unsupported lexical FTS config '%s'; falling back to 'simple'", value)
        return "simple"
    return cfg


async def _execute_sql(db: AsyncSession, sql_query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = await db.execute(text(sql_query), params)
    return [dict(r._mapping) for r in result.mappings().all()]


def _normalize_scope(scope: Any) -> str:
    if scope is None:
        return "public"
    raw = scope.value if hasattr(scope, "value") else scope
    return str(raw).strip().lower() or "public"


async def search_lexical_chunks(
    db: AsyncSession,
    *,
    query: str,
    tenant_id: str,
    top_k: int = 8,
    filters: Optional[Dict[str, Any]] = None,
    # legacy-compatible args
    doc_type: Optional[str] = None,
    domain: Optional[str] = None,  # kept for signature compatibility
    security_level: int = 1,  # kept for signature compatibility
    document_id: Optional[str] = None,  # kept for signature compatibility
    parent_id: Optional[str] = None,  # kept for signature compatibility
    variants: Optional[List[Dict[str, Any]]] = None,
) -> List[Tuple[str, float, Dict[str, Any]]]:
    """
    Lexical retrieval (Postgres FTS) aligned with current `chunks` schema.
    Fail-soft by design: any SQL/runtime error returns [] without breaking hybrid lane.
    """
    del domain, security_level, document_id, parent_id  # explicit legacy args

    q = (query or "").strip()
    if not q and not variants:
        return []

    f = filters or {}

    # queries list
    queries = [v.get("query", "").strip() for v in (variants or []) if (v.get("query") or "").strip()]
    if not queries:
        queries = [q]

    # strict scope handling: this SQL lane currently supports public docs only.
    # internal/restricted continue to rely on vector lane (hybrid).
    scope = _normalize_scope(f.get("scope"))
    if scope != "public":
        logger.warning("Lexical lane disabled for non-public scope='%s' (fail-soft)", scope)
        return []

    params: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "scope": scope,
        "k": int(top_k),
        "cfg": _safe_fts_config(str(FTS_CONFIG)),
    }

    where_clauses = [
        f"{TENANT_COL} = :tenant_id",
        f"LOWER(COALESCE({SCOPE_COL}, '')) = :scope",
    ]

    # doc type filter maps to doc_category in chunks table
    dt = f.get("doc_type") or f.get("doc_types") or doc_type
    if dt:
        if isinstance(dt, list):
            normalized = [str(x).strip().lower() for x in dt if str(x).strip()]
            if normalized:
                where_clauses.append(f"LOWER(COALESCE({DOC_TYPE_COL}, '')) = ANY(:doc_types)")
                params["doc_types"] = normalized
        else:
            where_clauses.append(f"LOWER(COALESCE({DOC_TYPE_COL}, '')) = :doc_type")
            params["doc_type"] = str(dt).strip().lower()

    text_expr = f"COALESCE({DISPLAY_TEXT_COL}, '') || ' ' || COALESCE({EMBED_TEXT_COL}, '')"

    # FTS setup
    fts_tsquery_parts: List[str] = []
    for i, variant_q in enumerate(queries):
        params[f"q{i}"] = variant_q
        fts_tsquery_parts.append(f"websearch_to_tsquery(CAST(:cfg AS regconfig), :q{i})")

    if not fts_tsquery_parts:
        params["q0"] = q
        fts_tsquery_parts.append("websearch_to_tsquery(CAST(:cfg AS regconfig), :q0)")

    fts_tsquery = " || ".join(fts_tsquery_parts)
    fts_vector = f"to_tsvector(CAST(:cfg AS regconfig), {text_expr})"
    fts_rank = f"ts_rank_cd({fts_vector}, ({fts_tsquery}))"
    fts_match = f"{fts_vector} @@ ({fts_tsquery})"

    codelike = ENABLE_ILIKE_FALLBACK and is_code_query(q)
    if codelike:
        ilike_parts = [f"{text_expr} ILIKE '%' || :q{i} || '%'" for i in range(len(queries))]
        ilike_match = " OR ".join(ilike_parts) if ilike_parts else "FALSE"
        score_expr = f"({fts_rank} + CASE WHEN ({ilike_match}) THEN 0.15 ELSE 0 END)"
        match_expr = f"(({fts_match}) OR ({ilike_match}))"
        mode = "pg_fts_ilike"
    else:
        score_expr = fts_rank
        match_expr = fts_match
        mode = "pg_fts"

    where_sql = " AND ".join(where_clauses)

    sql = f"""
    SELECT
      {CHUNK_ID_COL}::text AS chunk_id,
      {score_expr} AS score,
      {TENANT_COL} AS tenant_id,
      {DOC_TYPE_COL} AS doc_type,
      NULL::text AS domain,
      1::int AS security_level,
      {DOCUMENT_ID_COL}::text AS document_id,
      NULL::text AS parent_id
    FROM {CHUNKS_TABLE}
    WHERE {where_sql} AND {match_expr}
    ORDER BY score DESC
    LIMIT :k
    """

    try:
        rows = await _execute_sql(db, sql, params)
    except Exception as e:
        logger.error("Lexical SQL Failed: %s", e)
        return []

    out: List[Tuple[str, float, Dict[str, Any]]] = []
    for r in rows:
        payload = {
            "tenant_id": r.get("tenant_id"),
            "doc_type": r.get("doc_type"),
            "domain": r.get("domain"),
            "security_level": r.get("security_level"),
            "document_id": r.get("document_id"),
            "parent_id": r.get("parent_id"),
            "_score_kind": "lexical",
            "_score_mode": mode,
        }
        out.append((str(r.get("chunk_id")), float(r.get("score") or 0.0), payload))

    return out
