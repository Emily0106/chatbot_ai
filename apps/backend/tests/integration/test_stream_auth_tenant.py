import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.chat import ChatResponse
from app.config import settings

pytestmark = pytest.mark.integration

client = TestClient(app)

@pytest.fixture
def mock_auth_dep(monkeypatch):
    # Bypass auth for simple endpoint check (or mock it to pass)
    # For 410 check, we don't strictly need auth if it's deprecated?
    # Actually 410 checks happen before logic. 
    pass

def test_deprecated_stream_endpoint_returns_410():
    """
    Verify /api/chat/stream returns 410 Gone.
    """
    res = client.post("/api/chat/stream", json={"message": "hi", "tenant_id": "t1"})
    assert res.status_code == 410
    assert "deprecated" in res.json()["detail"]

@pytest.mark.asyncio
async def test_secure_stream_endpoint_enforces_tenant():
    """
    Verify POST /api/chat with stream=True enforces tenant_id from claims.
    """
    # We use TestClient but mock the internal rate limiter/agent to verify ctx
    
    mock_agent = MagicMock()
    # Mock process_stream to yield nothing
    async def mock_gen(*args, **kwargs):
        yield "data: chunk\n\n"
    mock_agent.process_stream.side_effect = mock_gen

    from app.security.auth import AuthClaims
    
    # Mock Rate Limiter
    mock_rl = AsyncMock()
    mock_rl.allow_request.return_value = MagicMock(allowed=True)
    mock_rl.enter_stream.return_value = MagicMock(allowed=True)
    mock_rl.enter_inflight.return_value = MagicMock(allowed=True)
    
    from app.security.auth import require_auth
    
    with patch("app.api.routes.chat.get_agent", return_value=mock_agent), \
         patch("app.core.rate_limit.rate_limiter", mock_rl):
         
        # We need to override the dependency in app using app.dependency_overrides
        app.dependency_overrides[require_auth] = lambda: AuthClaims(tenant_id="t1", sub="u1", roles=["user"])
        
        try:
             # Payload tries to spoof t2
             res = client.post(
                 "/api/chat", 
                 json={"message": "hi", "tenant_id": "t2", "stream": True, "agent_id": "citizen"},
                 headers={"X-API-Key": "dev-key-123"} 
             )
             
             assert res.status_code == 200
             # Verify strict auth: Rate limiter should use t1
             mock_rl.enter_stream.assert_called_with("t1")
             assert mock_rl.enter_stream.call_args[0][0] == "t1"
             
             # Verify agent called with TrustedContext having t1
             call_args = mock_agent.process_stream.call_args
             assert call_args, "Process stream not called"
             ctx = call_args[0][0]
             assert ctx.tenant_id == "t1"
             
        finally:
             app.dependency_overrides = {}
