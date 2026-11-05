import pytest
from unittest.mock import MagicMock, AsyncMock, call
from sqlalchemy import text
from app.core.db_sql import run_lookup_sql, fetch_chunks_by_ids

@pytest.mark.asyncio
async def test_fetch_chunks_tenant_injection_guard():
    """
    Test A: Ensure tenant_id is bound as a parameter, not injected into string.
    """
    mock_session = AsyncMock()
    # execute returns a result that has .mappings().all()
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result
    
    malicious_tenant = "t1' OR 1=1 --"
    chunk_ids = ["c1"]
    
    await fetch_chunks_by_ids(
        mock_session, 
        tenant_id=malicious_tenant, 
        chunk_ids=chunk_ids
    )
    
    # Check the call to execute
    assert mock_session.execute.called
    call_args = mock_session.execute.call_args
    # call_args[0][0] is the SQL text object
    sql_obj = call_args[0][0]
    sql_str = str(sql_obj)
    
    # 1. Verify malicious payload is NOT in SQL text
    assert "OR 1=1" not in sql_str
    
    # 2. Verify placeholder IS in SQL text
    assert ":tenant_id" in sql_str
    
    # 3. Verify params contain the payload
    # params are usually the second arg
    params = call_args[0][1]
    assert params["tenant_id"] == malicious_tenant

@pytest.mark.asyncio
async def test_run_lookup_sql_injection_guard():
    """
    Test B: Ensure search query inputs are bound.
    """
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result
    
    malicious_q = "admin' -- DROP TABLE users"
    
    await run_lookup_sql(
        mock_session,
        category="doc",
        params={"q": malicious_q}
    )
    
    assert mock_session.execute.called
    call_args = mock_session.execute.call_args
    sql_obj = call_args[0][0]
    sql_str = str(sql_obj)
    
    # Verify malicious payload NOT in SQL
    assert "DROP TABLE" not in sql_str
    
    # Verify placeholder IS in SQL (q uses :q)
    assert ":q" in sql_str
    
    # Verify params
    params = call_args[0][1]
    assert params["q"] == malicious_q
