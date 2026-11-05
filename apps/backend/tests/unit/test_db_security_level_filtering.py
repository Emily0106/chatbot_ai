import pytest
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.core import db_sql

@pytest.mark.asyncio
async def test_fetch_chunks_enforces_security_level():
    """
    Test 1: fetch_chunks_by_ids includes security clause + bound param
    """
    mock_db = AsyncMock(spec=AsyncSession)
    # Mock result
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result
    
    await db_sql.fetch_chunks_by_ids(
        mock_db, 
        tenant_id="t1", 
        chunk_ids=["c1"], 
        security_level=2
    )
    
    assert mock_db.execute.called
    args, _ = mock_db.execute.call_args
    sql_obj = args[0]
    params = args[1]
    
    sql_str = str(sql_obj)
    
    # Assertions
    assert ":security_level" in sql_str
    # Check default identifier 'security_level' is used in COALESCE
    assert "COALESCE(c.security_level, 1) <= :security_level" in sql_str
    assert params["security_level"] == 2
    assert params["tenant_id"] == "t1"
    assert params["chunk_ids"] == ["c1"]

@pytest.mark.asyncio
async def test_run_lookup_sql_enforces_security_level():
    """
    Test 2: run_lookup_sql includes security clause + bound param
    """
    mock_db = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result
    
    await db_sql.run_lookup_sql(
        mock_db, 
        category="doc", 
        params={"q": "hello"}, 
        user_security_level=3
    )
    
    assert mock_db.execute.called
    args, _ = mock_db.execute.call_args
    sql_obj = args[0]
    params = args[1]
    
    sql_str = str(sql_obj)
    
    # Assertions
    assert ":security_level" in sql_str
    assert "COALESCE(security_level, 1) <= :security_level" in sql_str
    assert params["security_level"] == 3
    assert params["category"] == "doc"
    assert params["q"] == "hello"

@pytest.mark.asyncio
async def test_fetch_chunks_default_tenant_param():
    """
    Test 1b: fetch_chunks_by_ids handling for default tenant also binds security_level
    """
    mock_db = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result
    
    # Needs ALLOW_DEFAULT_TENANT=True if we want to avoid error
    # We can patch settings, or just catch error if allow check fails?
    # db_sql.settings.ALLOW_DEFAULT_TENANT is checked.
    # It defaults to False in config.py, so this might raise ValueError.
    
    from unittest.mock import patch
    with patch("app.core.db_sql.settings.ALLOW_DEFAULT_TENANT", True):
        await db_sql.fetch_chunks_by_ids(
            mock_db, 
            tenant_id="default", 
            chunk_ids=["c1"], 
            security_level=1
        )
        
    args, _ = mock_db.execute.call_args
    params = args[1]
    
    # Assert security_level is bound even for default tenant
    assert params["security_level"] == 1
    assert params["tenant_id"] == "default"


@pytest.mark.asyncio
async def test_fetch_chunks_fallback_when_security_column_missing():
    """
    If chunks table does not have security_level, query should retry without security clause.
    """
    mock_db = AsyncMock(spec=AsyncSession)

    # 1st execute -> missing column, 2nd execute -> success
    first_err = Exception('column "security_level" does not exist')
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_db.execute.side_effect = [first_err, mock_result]

    await db_sql.fetch_chunks_by_ids(
        mock_db,
        tenant_id="tenant_a",
        chunk_ids=["c1"],
        security_level=1,
    )

    assert mock_db.execute.call_count == 2
    # rollback called between attempts
    assert mock_db.rollback.called

    first_sql = str(mock_db.execute.call_args_list[0].args[0])
    first_params = mock_db.execute.call_args_list[0].args[1]
    assert "COALESCE(c.security_level, 1) <= :security_level" in first_sql
    assert "security_level" in first_params

    second_sql = str(mock_db.execute.call_args_list[1].args[0])
    second_params = mock_db.execute.call_args_list[1].args[1]
    assert "COALESCE(security_level, 1) <= :security_level" not in second_sql
    assert "security_level" not in second_params
