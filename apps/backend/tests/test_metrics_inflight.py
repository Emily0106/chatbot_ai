
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_inflight_gauge_lifecycle(monkeypatch):
    """
    Verify INFLIGHT_ACTIVE gauge increments before impl and decrements after.
    Mocking _chat_endpoint_impl to avoid schema validation hell.
    """
    # 1. Mock RateLimiter
    mock_rl = AsyncMock()
    mock_rl.allow_request.return_value = MagicMock(allowed=True)
    mock_rl.enter_inflight.return_value = MagicMock(allowed=True)
    
    # Patch where used
    import app.core.rate_limit
    monkeypatch.setattr(app.core.rate_limit, "rate_limiter", mock_rl)
    
    from app.schemas.chat import ChatResponse
    
    # 2. Mock _chat_endpoint_impl (The inner function)
    # We want to verify that when chat_endpoint calls it, the gauge is ++
    # But since it's async, we can't easily peek "during" execution from outside 
    # unless we use a side effect that checks the gauge.
    
    from app.core.metrics import INFLIGHT_ACTIVE
    
    async def mock_impl(*args, **kwargs):
        # Check gauge inside
        val = INFLIGHT_ACTIVE.labels(lane="all")._value.get()
        # Note: if parallel tests run, this might be noisy, but isolated it's fine
        # We assume start at 0
        assert val >= 1.0, f"Gauge should be incremented (val={val})"
        return ChatResponse(answer="Mock", citations=[], meta={})
        
    monkeypatch.setattr("app.api.routes.chat._chat_endpoint_impl", mock_impl)
    
    # 3. Call Endpoint
    from app.main import app
    initial = INFLIGHT_ACTIVE.labels(lane="all")._value.get()
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        payload = {"agent_id": "citizen", "message": "hi"}
        resp = await ac.post("/api/chat", json=payload)
        assert resp.status_code == 200
        
    # 4. Assert Decrement
    final = INFLIGHT_ACTIVE.labels(lane="all")._value.get()
    assert final == initial
