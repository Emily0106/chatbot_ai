import pytest
from unittest.mock import MagicMock, AsyncMock
from app.core.db_lexical import search_lexical_chunks

@pytest.mark.asyncio
async def test_lexical_public_safety():
    """Verify PUBLIC scope uses case-normalized scope filter."""
    db = AsyncMock()
    # Mock result to avoid iteration error
    db.execute.return_value.mappings.return_value.all.return_value = []
    
    await search_lexical_chunks(
        db, 
        query="test", 
        tenant_id="t1", 
        filters={"scope": "PUBLIC"}
    )
    
    # Check SQL arguments
    call_args = db.execute.call_args
    sql = str(call_args[0][0]) # getting the SQL text object
    
    assert "LOWER(COALESCE(scope, '')) = :scope" in sql
    assert "contains_pii" not in sql
    assert "department_id" not in sql

@pytest.mark.asyncio
async def test_lexical_internal_enforcement():
    """INTERNAL scope is fail-soft in SQL lane and should return empty."""
    db = AsyncMock()
    db.execute.return_value.mappings.return_value.all.return_value = []

    # Internal is handled by vector strict filter; lexical lane skips.
    res = await search_lexical_chunks(
        db, 
        query="decree", 
        tenant_id="t1",
        filters={"scope": "INTERNAL", "department_id": "DEPT_01"}
    )
    assert res == []
    assert not db.execute.called

@pytest.mark.asyncio
async def test_lexical_restricted_logic():
    """RESTRICTED scope is fail-soft in SQL lane and should return empty."""
    db = AsyncMock()
    db.execute.return_value.mappings.return_value.all.return_value = []
    
    res = await search_lexical_chunks(
        db,
        query="secrets",
        tenant_id="t1",
        filters={"scope": "RESTRICTED", "security_level": 3, "geo_code": "VN-HN"}
    )
    assert res == []
    assert not db.execute.called

@pytest.mark.asyncio
async def test_lexical_legacy_unknown_meta_deny():
    """Default scope should still constrain to public rows."""
    db = AsyncMock()
    db.execute.return_value.mappings.return_value.all.return_value = []

    # Implicit PUBLIC check
    await search_lexical_chunks(db, query="foo", tenant_id="t1", filters={})
    sql = str(db.execute.call_args[0][0])
    assert "LOWER(COALESCE(scope, '')) = :scope" in sql
