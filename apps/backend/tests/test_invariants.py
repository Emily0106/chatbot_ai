# apps/backend/tests/test_invariants.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from app.core.db_vector import search_chunks, search_hybrid_chunks
from app.core.db_sql import fetch_chunks_by_ids

@pytest.mark.asyncio
async def test_vector_search_requires_tenant_id():
    # Test search_chunks
    with pytest.raises(ValueError, match="tenant_id is required"):
        await search_chunks(query_vector=[0.1]*768, tenant_id=None)
    
    with pytest.raises(ValueError, match="tenant_id is required"):
        await search_chunks(query_vector=[0.1]*768, tenant_id="")

    # Test search_hybrid_chunks
    with pytest.raises(ValueError, match="tenant_id is required"):
        await search_hybrid_chunks(query="test", dense_embed_fn=AsyncMock(), tenant_id=None)

@pytest.mark.asyncio
async def test_sql_fetch_requires_tenant_id():
    mock_db = AsyncMock()
    with pytest.raises(ValueError, match="tenant_id is required"):
        await fetch_chunks_by_ids(mock_db, tenant_id=None, chunk_ids=["1"])
