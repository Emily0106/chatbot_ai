
import pytest
from unittest.mock import MagicMock
from app.agents.citizen_agent import CitizenAgent
from app.agents.contract import TrustedContext

@pytest.mark.asyncio
async def test_citizen_agent_handles_none_filters():
    """
    Verify that CitizenAgent.process handles payload with missing or None 'filters'
    without raising TypeError.
    """
    # Setup
    agent = CitizenAgent()
    
    # Mock dependencies inside process via patching or safe imports
    # Since process imports internal deps, we might need to mock them if we run this.
    # However, strict unit testing of 'process' is hard without mocking the heavy imports.
    # We can inspect the method code logic or try to run it and expect it to fail LATER (at RAG step)
    # but NOT at the filter extraction step.
    
    # Actually, simpler: we want to verify the logic `filters = ctx.request_payload.get("filters") or {}`
    # We can construct a context with None filters
    
    ctx = TrustedContext(
        tenant_id="test_tenant",
        user_id="test_user",
        request_payload={"filters": None}, # Explicit None
        security_level=1,
        geo_code="VN"
    )
    
    # We need to mock 'rag_retrieve' and 'achat' to allow process to run to completion (or at least past filter logic)
    # We can use sys.modules patching or unittest.mock.patch
    
    with pytest.raises(Exception) as excinfo:
        # We expect it to fail at get_async_db or rag_retrieve if we don't mock them,
        # BUT NOT TypeError: 'NoneType' object does not support item assignment
        await agent.process(ctx, "test query")
    
    # If the fix works, it should proceed to try invalid imports or DB calls, raising ImportError or RuntimeError
    # OR if we mocked well, it passes.
    # If the fix is BROKEN, it raises TypeError immediately when doing filters["doc_types"] = ...
    
    assert "NoneType" not in str(excinfo.value)

@pytest.mark.asyncio
async def test_citizen_agent_handles_missing_filters_key():
    """
    Verify that CitizenAgent.process handles payload with MISSING 'filters' key.
    """
    agent = CitizenAgent()
    ctx = TrustedContext(
        tenant_id="test_tenant",
        user_id="test_user",
        request_payload={}, # Missing filters key
        security_level=1,
        geo_code="VN"
    )
    
    with pytest.raises(Exception) as excinfo:
         await agent.process(ctx, "test query")
         
    assert "NoneType" not in str(excinfo.value)
