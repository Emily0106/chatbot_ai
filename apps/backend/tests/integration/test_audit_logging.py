import pytest

pytestmark = pytest.mark.integration
import json
import logging
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from app.api.routes import chat
from app.main import app
from app.schemas.chat import ChatResponse, ChatMeta, Citation

client = TestClient(app)

# --- Test Data ---
VALID_KEY = "dev-key-123"
TENANT_ID = "t1"
PAYLOAD = {
    "agent_id": "citizen",
    "message": "Hello Audit",
    "tenant_id": TENANT_ID, # Client tenant (should be ignored/warned)
}

# --- Fixtures ---

@pytest.fixture
def mock_audit_logger():
    with patch("app.core.audit.audit.audit_logger") as mock:
        yield mock

@pytest.fixture
def mock_auth():
    from app.security.auth import require_auth, AuthClaims
    app.dependency_overrides[require_auth] = lambda: AuthClaims(tenant_id="t1", sub="u1", roles=["user"])
    yield
    app.dependency_overrides = {}

# --- Tests ---

def test_chat_audit_events_emitted(mock_audit_logger, mock_auth):
    """
    Test A: Verify chat.request and chat.response events are logged with correct fields.
    """
    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value=ChatResponse(
        answer="Hello", citations=[], meta=ChatMeta(), handoff=None
    ))
    
    # Use patch.object to ensure we patch the exact module object identified by 'chat'
    # 'chat' was imported from app.api.routes
    
    with patch.object(chat, "get_agent", return_value=mock_agent):
        res = client.post(
            "/api/chat",
            json={**PAYLOAD, "stream": False},
            headers={"X-API-Key": VALID_KEY}
        )
        assert res.status_code == 200, f"Response: {res.text}"
        
    # Verify logs
    assert mock_audit_logger.info.called
    calls = mock_audit_logger.info.call_args_list
    
    logs = []
    for c in calls:
        try:
            logs.append(json.loads(c[0][0]))
        except:
            pass
            
    # Check chat.request
    req_log = next((l for l in logs if l["event"] == "chat.request"), None)
    assert req_log is not None, f"Request Log Missing. Found: {logs}"
    assert req_log["tenant_id"] == "t1"
    assert req_log["endpoint"] == "/api/chat"
    assert "query_sha1" in req_log
    
    # Check chat.response
    res_log = next((l for l in logs if l["event"] == "chat.response"), None)
    assert res_log is not None
    assert res_log["status"] == "ok"
    assert res_log["tenant_id"] == "t1"

def test_chat_error_audit_emitted(mock_audit_logger, mock_auth):
    """
    Test B: Verify chat.error is emitted on exception.
    """
    mock_agent = MagicMock()
    # Simulate error
    # process is async
    mock_agent.process = AsyncMock(side_effect=ValueError("Simulated Agent Failure"))
    
    with patch.object(chat, "get_agent", return_value=mock_agent):
        res = client.post(
            "/api/chat",
            json={**PAYLOAD, "stream": False},
            headers={"X-API-Key": VALID_KEY}
        )
        assert res.status_code == 500
        
    logs = []
    for c in mock_audit_logger.info.call_args_list:
        try:
            logs.append(json.loads(c[0][0]))
        except:
            pass
            
    err_log = next((l for l in logs if l["event"] == "chat.error"), None)
    assert err_log is not None, f"Logs found: {logs}"
    assert err_log["error_type"] == "ValueError"
    assert "Simulated Agent Failure" in err_log["error_msg"]

def test_rag_access_audit_emitted(mock_audit_logger, mock_auth):
    """
    Test C: Verify rag.access is emitted when citations exist.
    """
    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value=ChatResponse(
        answer="With citations", 
        citations=[Citation(document_id="doc1", chunk_id="ch1")], 
        meta=ChatMeta(), handoff=None
    ))
    
    with patch.object(chat, "get_agent", return_value=mock_agent):
        client.post(
            "/api/chat",
            json={**PAYLOAD, "stream": False},
            headers={"X-API-Key": VALID_KEY}
        )
        
    logs = [json.loads(c[0][0]) for c in mock_audit_logger.info.call_args_list]
    rag_log = next((l for l in logs if l["event"] == "rag.access"), None)
    
    assert rag_log is not None, f"Logs: {logs}"
    assert rag_log["citations_count"] == 1
    assert "doc1" in rag_log["doc_ids"]
