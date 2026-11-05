import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.api.routes.chat import _chat_endpoint_impl
from app.security.auth import AuthClaims
from app.schemas.chat import ChatRequest, ChatResponse
from app.agents import contract

# We will test the critical logic in _chat_endpoint_impl (or by integration test)
# Integration test via TestClient with patched auth is better.

from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

pytestmark = pytest.mark.integration

client = TestClient(app)

@pytest.fixture
def mock_load_api_keys(monkeypatch):
    """Mock API Keys to control tenant_id scenarios"""
    db = {
        "key-t1": {"tenant_id": "t1", "roles": ["user"], "security_level": 1},
        "key-no-tenant": {"roles": ["user"]}, # Invalid
    }
    monkeypatch.setattr("app.security.auth._load_api_keys", lambda: db)
    # Ensure mode allows checks
    monkeypatch.setattr(settings, "ENV_MODE", "prod")

def test_spoof_attempt_ignored(mock_load_api_keys):
    """
    Scenario A: 
    - Header Key maps to Tenant 't1'.
    - Body Payload sends Tenant 't2' (Spoof).
    - Expectation: System uses 't1'. Request succeeds (200 or 422 if other validation fails).
    - We verify by mocking the 'agent.process' or inspecting response if we can.
    """
    
    mock_agent = AsyncMock()
    mock_agent.process.return_value = ChatResponse(answer="ok")
    
    with patch("app.api.routes.chat.get_agent", return_value=mock_agent):
        res = client.post(
            "/api/chat",
            json={"message": "hi", "tenant_id": "t2", "agent_id": "citizen", "stream": False}, # SPOOF t2, Block Mode
            headers={"X-API-Key": "key-t1"} # REAL t1
        )
        
        assert res.status_code == 200, f"Failed with {res.status_code}: {res.text}"
        
        # Verify call args
        # mock_agent.process(ctx, query)
        call_args = mock_agent.process.call_args
        assert call_args is not None
        ctx_arg = call_args[0][0] # First arg is ctx
        
        assert isinstance(ctx_arg, contract.TrustedContext)
        assert ctx_arg.tenant_id == "t1" # MUST BE T1
        assert ctx_arg.tenant_id != "t2" # Spoof failed

def test_missing_tenant_in_claims_403(mock_load_api_keys):
    """
    Scenario B:
    - Key exists but maps to data without tenant_id.
    - Expect 403 (Auth layer fails logic)
    """
    res = client.post(
        "/api/chat",
        json={"message": "hi"},
        headers={"X-API-Key": "key-no-tenant"}
    )
    assert res.status_code == 403
    assert "Misconfigured Key" in res.json()["detail"]
