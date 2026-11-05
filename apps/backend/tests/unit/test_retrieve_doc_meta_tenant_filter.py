from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.rag.retrieve import _fetch_documents_meta_bulk


@pytest.mark.asyncio
async def test_fetch_documents_meta_bulk_enforces_tenant_filter() -> None:
    db = AsyncMock()

    class _Result:
        def mappings(self):
            return self

        def all(self):
            return []

    db.execute = AsyncMock(return_value=_Result())

    await _fetch_documents_meta_bulk(
        db,
        tenant_id="tenant_a",
        document_ids=["doc-1", "doc-2"],
    )

    sql = str(db.execute.call_args[0][0])
    params = db.execute.call_args[0][1]

    assert "tenant_id = :tenant_id" in sql
    assert params["tenant_id"] == "tenant_a"
    assert params["doc_ids"] == ["doc-1", "doc-2"]
