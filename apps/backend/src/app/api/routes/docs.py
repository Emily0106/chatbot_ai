from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_sql import get_async_db
from app.core.sql_safety import validate_identifier, validate_table_identifier
from app.security.auth import AuthClaims, require_auth

router = APIRouter(prefix="/docs", tags=["docs"])


@router.get("/{doc_id}")
async def get_document_meta(
    doc_id: str,
    db: AsyncSession = Depends(get_async_db),
    claims: AuthClaims = Depends(require_auth),
):
    """
    Tenant-scoped metadata endpoint for citations.
    Never returns raw `source_uri`/filesystem paths.
    """
    docs_table = validate_table_identifier("documents")
    doc_id_col = validate_identifier("doc_id")
    tenant_col = validate_identifier("tenant_id")
    commune_col = validate_identifier("commune_id")
    scope_col = validate_identifier("scope")
    title_col = validate_identifier("title")
    doc_type_col = validate_identifier("doc_type")
    doc_category_col = validate_identifier("doc_category")
    deleted_col = validate_identifier("is_deleted")
    created_col = validate_identifier("created_at")
    updated_col = validate_identifier("updated_at")

    sql = text(
        f"""
        SELECT
          d.{doc_id_col}::text AS doc_id,
          d.{title_col} AS title,
          d.{scope_col} AS scope,
          COALESCE(d.{doc_type_col}, d.{doc_category_col}) AS doc_type,
          d.{created_col} AS created_at,
          d.{updated_col} AS updated_at
        FROM {docs_table} d
        WHERE d.{doc_id_col}::text = :doc_id
          AND COALESCE(d.{tenant_col}, d.{commune_col}) = :tenant_id
          AND COALESCE(d.{deleted_col}, FALSE) = FALSE
        LIMIT 1
        """
    )

    res = await db.execute(sql, {"doc_id": doc_id, "tenant_id": claims.tenant_id})
    row = res.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "doc_id": row.get("doc_id"),
        "title": row.get("title"),
        "scope": row.get("scope"),
        "doc_type": row.get("doc_type"),
        "created_at": str(row.get("created_at")) if row.get("created_at") is not None else None,
        "updated_at": str(row.get("updated_at")) if row.get("updated_at") is not None else None,
    }
