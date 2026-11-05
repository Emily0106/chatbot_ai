
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_chat_rps_deny(monkeypatch):
    """Verify endpoint returns 429 when RPS limit is exceeded"""
    import app.config
    import app.main
    
    # Access via module to avoid NameError if local import is weird
    monkeypatch.setattr(app.config.settings, "ENABLE_RATE_LIMITING", True)
    
    from app.core import rate_limit
    mock_rl = AsyncMock()
    # allow_request -> (allowed=False, reason="...", retry_after=5.0)
    mock_rl.allow_request.return_value = rate_limit.RateLimitResult(False, "rate_limit_exceeded", 5.0)
    
    # Inject mock - patch where USED in route
    import app.api.routes.chat
    monkeypatch.setattr("app.api.routes.chat.rate_limiter", mock_rl)
    
    async with AsyncClient(transport=ASGITransport(app=app.main.app), base_url="http://test") as ac:
        payload = {"agent_id": "citizen", "message": "hi"}
        resp = await ac.post("/api/chat", json=payload)
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "5"
        
@pytest.mark.asyncio
async def test_chat_inflight_deny(monkeypatch):
    """Verify endpoint returns 503 when Inflight limit is exceeded"""
    import app.config
    import app.main
    
    monkeypatch.setattr(app.config.settings, "ENABLE_RATE_LIMITING", True)
    
    from app.core import rate_limit
    mock_rl = AsyncMock()
    # RPS Pass
    mock_rl.allow_request.return_value = rate_limit.RateLimitResult(True, "ok", None)
    # Inflight Deny
    mock_rl.enter_inflight.return_value = rate_limit.RateLimitResult(False, "inflight_limit_exceeded", None)
    
    import app.api.routes.chat
    monkeypatch.setattr("app.api.routes.chat.rate_limiter", mock_rl)
    
    async with AsyncClient(transport=ASGITransport(app=app.main.app), base_url="http://test") as ac:
        payload = {"agent_id": "citizen", "message": "hi"}
        resp = await ac.post("/api/chat", json=payload)
        assert resp.status_code == 503

@pytest.mark.asyncio
async def test_stream_concurrency_deny(monkeypatch):
    """Verify stream endpoint returns 429 when max streams exceeded"""
    import app.config
    import app.main
    
    monkeypatch.setattr(app.config.settings, "ENABLE_STREAMING_CHAT", True)
    monkeypatch.setattr(app.config.settings, "ENABLE_RATE_LIMITING", True)
    
    from app.core import rate_limit
    mock_rl = AsyncMock()
    mock_rl.allow_request.return_value = rate_limit.RateLimitResult(True, "ok", None)
    mock_rl.enter_stream.return_value = rate_limit.RateLimitResult(False, "stream_limit_exceeded", None)
    
    import app.api.routes.chat
    monkeypatch.setattr("app.api.routes.chat.rate_limiter", mock_rl)
    
    async with AsyncClient(transport=ASGITransport(app=app.main.app), base_url="http://test") as ac:
        payload = {"agent_id": "citizen", "message": "hi"}
        resp = await ac.post("/api/chat/stream", json=payload)
        assert resp.status_code == 429
