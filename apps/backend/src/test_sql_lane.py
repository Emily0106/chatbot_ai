import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from app.core.sql.validator import SQLValidator
from app.core.sql.executor import SQLExecutor
from app.core.sql.types import SQLPolicy, SecurityError, ValidationError
from sqlalchemy import text

# Default Policy
DEFAULT_POLICY = SQLPolicy(
    tenant_column="commune_id",
    allowed_relations=["view_people", "view_budget", "structured_rows"],
    max_limit=50,
    statement_timeout_ms=2000,
    forbid_set_ops=True
)

# Mock DB Session
class MockSession:
    def __init__(self):
        self.execute = AsyncMock()

@pytest.mark.asyncio
async def test_validator_injection():
    v = SQLValidator()
    # Attempt injection
    bad_sql = "SELECT * FROM view_people; DROP TABLE view_people;"
    
    with pytest.raises(SecurityError) as excinfo:
        v.validate_and_transform(
            raw_sql=bad_sql, 
            params={}, 
            tenant_id="tenant_1", 
            policy=DEFAULT_POLICY, 
            lane="manual"
        )
    assert "multi_statement_forbidden" in str(excinfo.value)

@pytest.mark.asyncio
async def test_validator_tenant_isolation():
    v = SQLValidator()
    sql = "SELECT * FROM view_people"
    safe_sql = v.validate_and_transform(
        raw_sql=sql, 
        params={}, 
        tenant_id="tenant_1", 
        policy=DEFAULT_POLICY, 
        lane="manual"
    )
    
    # Check canonical SQL
    # sqlglot canonical output might quote identifiers or not depending on dialect.
    # We check for presence of condition.
    print(f"Generated SQL: {safe_sql.sql}")
    assert 'commune_id = :tenant_id_val' in safe_sql.sql
    assert safe_sql.params['tenant_id_val'] == 'tenant_1'
    assert safe_sql.injected['tenant_injected'] > 0

@pytest.mark.asyncio
async def test_executor_flow():
    # Mock get_async_db
    mock_session = MockSession()
    mock_result = MagicMock()
    mock_result.keys.return_value = ["full_name", "code"]
    mock_result.all.return_value = [("Nguyen Van A", "A")]
    mock_session.execute.return_value = mock_result

    with patch("app.core.sql.executor.get_async_db", return_value=iter([mock_session])):
        # The mock needs to be an async generator
        async def mock_get_db():
            yield mock_session

        with patch("app.core.sql.executor.get_async_db", side_effect=mock_get_db):
            executor = SQLExecutor()
            # executor uses its own internal policy which matches DEFAULT_POLICY structure
            res = await executor.execute_safe("SELECT * FROM view_people", "tenant_1")
            
            assert len(res["data"]) == 1
            assert res["data"][0]["full_name"] == "Nguyen Van A"
            
            # Verify session.execute called with modified SQL
            args, kwargs = mock_session.execute.call_args
            executed_sql = str(args[0])
            executed_params = args[1] if len(args) > 1 else kwargs.get('params', {})
            
            assert 'commune_id = :tenant_id_val' in executed_sql
            assert executed_params['tenant_id_val'] == 'tenant_1'
            assert "LIMIT 50" in executed_sql

if __name__ == "__main__":
    # Simple runner if pytest not available
    async def run():
        await test_validator_injection()
        print("test_validator_injection passed")
        
        await test_validator_tenant_isolation()
        print("test_validator_tenant_isolation passed")

    asyncio.run(run())
