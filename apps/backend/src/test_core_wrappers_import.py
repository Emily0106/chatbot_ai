import pytest
from app.core.sql.api import sql_execute_safe
from app.core.tools.web import web_search, external_api_call

@pytest.mark.asyncio
async def test_core_wrappers_exist_and_fail_closed():
    """
    Verifies that core agent wrappers:
    1. Are importable from expected paths
    2. Are callable
    3. Fail-closed (raise RuntimeError) when called without mocks (for tools)
    """
    assert callable(sql_execute_safe)
    assert callable(web_search)
    assert callable(external_api_call)

    # Verify fail-closed behavior for web_search
    with pytest.raises(RuntimeError) as exc:
        await web_search("test query")
    assert "web_search is not configured" in str(exc.value)

    # Verify fail-closed behavior for external_api_call
    with pytest.raises(RuntimeError) as exc:
        await external_api_call("GET", "http://example.com")
    assert "external_api_call is not configured" in str(exc.value)
