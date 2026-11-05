from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.routes.docs import get_document_meta


@pytest.mark.asyncio
async def test_docs_meta_returns_tenant_scoped_safe_fields():
    row = {
        "doc_id": "doc-1",
        "title": "Sample",
        "scope": "public",
        "doc_type": "law",
        "created_at": None,
        "updated_at": None,
    }
    result = MagicMock()
    result.mappings.return_value.first.return_value = row
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    claims = MagicMock()
    claims.tenant_id = "tenant-a"

    out = await get_document_meta("doc-1", db=db, claims=claims)
    assert out["doc_id"] == "doc-1"
    assert out["title"] == "Sample"
    assert "source_uri" not in out


@pytest.mark.asyncio
async def test_docs_meta_returns_404_when_missing():
    result = MagicMock()
    result.mappings.return_value.first.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    claims = MagicMock()
    claims.tenant_id = "tenant-a"

    with pytest.raises(HTTPException) as exc:
        await get_document_meta("doc-missing", db=db, claims=claims)
    assert exc.value.status_code == 404
