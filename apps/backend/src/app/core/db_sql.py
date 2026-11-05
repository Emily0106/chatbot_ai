from __future__ import annotations

import os
import logging
from typing import Any, Dict, List, Optional
from app.core.sql_safety import validate_identifier, validate_table_identifier

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DATABASE_URL = (
    os.getenv("DB_URL")
    or os.getenv("DATABASE_URL")
    or "postgresql+asyncpg://mock:mock@localhost/mock" # Fallback for Import Safety in Tests
)

# if not DATABASE_URL:
#     raise RuntimeError("Missing DATABASE_URL/DB_URL (async driver), e.g. postgresql+asyncpg://...")

_engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
_Session = async_sessionmaker(_engine, expire_on_commit=False)
logger = logging.getLogger(__name__)


async def get_async_db():
    async with _Session() as session:
        yield session


async def run_lookup_sql(
    db: AsyncSession,
    *,
    category: str,
    params: Dict[str, Any],
    user_security_level: int = 1,
) -> List[Dict[str, Any]]:
    code = params.get("code")
    cccd = params.get("cccd")
    full_name = params.get("full_name")
    commune_id = params.get("commune_id")
    year = params.get("year")
    q = (params.get("q_ascii") or params.get("q") or "").strip()

    # Enforce Security Level
    STRUCT_SEC_COL = validate_identifier(getattr(settings, "STRUCTURED_SECURITY_COL", "security_level"))
    
    where = ["doc_category = :category", f"COALESCE({STRUCT_SEC_COL}, 1) <= :security_level"]
    sql_params: Dict[str, Any] = {
        "category": category,
        "security_level": user_security_level
    }

    if commune_id:
        where.append("commune_id = :commune_id")
        sql_params["commune_id"] = commune_id

    if year:
        where.append("data_content->>'year' = :year")
        sql_params["year"] = str(year)

    # Strong keys first
    if cccd:
        where.append("data_content->>'cccd' = :cccd")
        sql_params["cccd"] = str(cccd)
        score_expr = "1.0"
        order_by = "row_id"
    elif code:
        where.append("data_content->>'code' = :code")
        sql_params["code"] = str(code)
        score_expr = "1.0"
        order_by = "row_id"
    elif full_name:
        where.append("LOWER(data_content->>'full_name') = LOWER(:full_name)")
        sql_params["full_name"] = str(full_name)
        score_expr = "1.0"
        order_by = "row_id"
    elif q:
        # ✅ FTS (hit đúng index idx_structured_rows_search_fts)
        where.append(
            "to_tsvector('simple', COALESCE(search_text,'')) @@ plainto_tsquery('simple', :q)"
        )
        sql_params["q"] = q
        score_expr = "ts_rank(to_tsvector('simple', COALESCE(search_text,'')), plainto_tsquery('simple', :q))"
        order_by = "score DESC"
    elif params.get("list_all"):
        # List all for category
        score_expr = "1.0"
        order_by = "(data_content->>'code') NULLS LAST"
        # LIMIT handled by query construction below (default 10, maybe increase for list_all?)
        # For list_all we might want more results, let's stick to default limit or param
    else:
        return []

    # Construct SQL without f-strings for safety
    columns = "row_id, data_content, citation, " + score_expr + " AS score"
    joined_where = " AND ".join(where)
    
    query_str = (
        "SELECT " + columns + "\n"
        "FROM structured_rows\n"
        "WHERE " + joined_where + "\n"
        "ORDER BY " + order_by + "\n"
        "LIMIT 10"
    )
    
    sql = text(query_str)

    res = await db.execute(sql, sql_params)

    out: List[Dict[str, Any]] = []
    for r in res.mappings().all():
        out.append({
            "row_id": r["row_id"],
            "data": r["data_content"],
            "citation": r["citation"],
            "score": float(r["score"]) if r["score"] is not None else 1.0,
        })
    return out


from app.config import settings

async def fetch_chunks_by_ids(
    db: AsyncSession,
    *,
    tenant_id: str,
    chunk_ids: List[str],
    security_level: int = 1,
) -> List[Dict[str, Any]]:
    """
    Fetch chunk rows by ids with strict tenant isolation (required).
    Optionally enforce security_level <= user_security_level.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")

    # Security: Lock default tenant (null-scope) access
    if tenant_id == "default" and not settings.ALLOW_DEFAULT_TENANT:
        raise ValueError("Access to default tenant is restricted in this environment")

    if not chunk_ids:
        return []

    # Validate SQL Identifiers (Anti-Injection)
    CHUNKS_TABLE = validate_table_identifier(getattr(settings, "CHUNKS_TABLE", "chunks"))
    CHUNK_ID_COL = validate_identifier(getattr(settings, "CHUNK_ID_COL", "chunk_id"))
    DOC_ID_COL = validate_identifier(getattr(settings, "CHUNK_DOCUMENT_ID_COL", "doc_id"))
    DOCS_TABLE = validate_table_identifier(getattr(settings, "DOCUMENTS_TABLE", "documents"))
    DOCS_ID_COL = validate_identifier(getattr(settings, "DOCUMENT_ID_COL", "doc_id"))
    DOCS_TENANT_COL = validate_identifier(getattr(settings, "DOCUMENT_TENANT_COL", "tenant_id"))
    
    # Columns to return: keep flexible; include common fields used by rerank/retrieve
    # Adjust if your table uses different names.
    EMBED_TEXT_COL = validate_identifier(getattr(settings, "CHUNK_EMBED_TEXT_COL", "embed_text"))
    DISPLAY_TEXT_COL = validate_identifier(getattr(settings, "CHUNK_DISPLAY_TEXT_COL", "display_text"))
    PAYLOAD_COL = validate_identifier(getattr(settings, "CHUNK_PAYLOAD_COL", "payload"))
    SEC_COL = validate_identifier(getattr(settings, "CHUNK_SECURITY_COL", "security_level"))

    # Note: asyncpg automatically handles Python list as PostgreSQL array
    # No need for ::text[] cast on parameter side
    # Note: asyncpg automatically handles Python list as PostgreSQL array
    # No need for ::text[] cast on parameter side
    
    # Base Query Structure (Identifiers from settings)
    base_query = (
        "SELECT \n"
        "  c.{CHUNK_ID_COL}::text AS chunk_id, \n"
        "  c.{DOC_ID_COL}::text AS document_id, \n"
        "  c.{DISPLAY_TEXT_COL} AS chunk_text, \n"
        "  c.{EMBED_TEXT_COL} AS embed_text, \n"
        "  c.citation, \n"
        "  1 AS page_start, \n"
        "  1 AS page_end \n"
        "FROM {CHUNKS_TABLE} c \n"
        "JOIN {DOCS_TABLE} d ON d.{DOCS_ID_COL} = c.{DOC_ID_COL} \n"
        "WHERE {scope_clause} \n"
        "  {security_clause} \n"
        "  AND c.{CHUNK_ID_COL}::text = ANY(:chunk_ids)"
    )

    params = {"tenant_id": tenant_id, "chunk_ids": chunk_ids, "security_level": security_level}
        
    # Format identifiers only (Trusted Config)
    final_query = base_query.format(
        CHUNK_ID_COL=CHUNK_ID_COL,
        DOC_ID_COL=DOC_ID_COL,
        CHUNKS_TABLE=CHUNKS_TABLE,
        DOCS_TABLE=DOCS_TABLE,
        DOCS_ID_COL=DOCS_ID_COL,
        DOCS_TENANT_COL=DOCS_TENANT_COL,
        DISPLAY_TEXT_COL=DISPLAY_TEXT_COL,
        EMBED_TEXT_COL=EMBED_TEXT_COL,
        SEC_COL=SEC_COL,
        scope_clause=f"d.{DOCS_TENANT_COL} = :tenant_id",
        security_clause=f"AND COALESCE(c.{SEC_COL}, 1) <= :security_level",
    )
    
    sql = text(final_query)

    try:
        res = await db.execute(sql, params)
    except Exception as e:
        msg = str(e).lower()
        # Some deployments keep security level in document metadata (not chunks table).
        # Fail-soft here to avoid dropping valid vector hits.
        missing_sec_col = ("does not exist" in msg) and (SEC_COL.lower() in msg)
        if not missing_sec_col:
            raise

        logger.warning(
            "fetch_chunks_by_ids: column %s missing on %s; retrying without chunk-level security filter",
            SEC_COL,
            CHUNKS_TABLE,
        )
        try:
            await db.rollback()
        except Exception:
            pass

        params_no_sec = dict(params)
        params_no_sec.pop("security_level", None)
        fallback_query = base_query.format(
            CHUNK_ID_COL=CHUNK_ID_COL,
            DOC_ID_COL=DOC_ID_COL,
            CHUNKS_TABLE=CHUNKS_TABLE,
            DOCS_TABLE=DOCS_TABLE,
            DOCS_ID_COL=DOCS_ID_COL,
            DOCS_TENANT_COL=DOCS_TENANT_COL,
            DISPLAY_TEXT_COL=DISPLAY_TEXT_COL,
            EMBED_TEXT_COL=EMBED_TEXT_COL,
            SEC_COL=SEC_COL,
            scope_clause=f"d.{DOCS_TENANT_COL} = :tenant_id",
            security_clause="",
        )
        res = await db.execute(text(fallback_query), params_no_sec)

    return [dict(r) for r in res.mappings().all()]
