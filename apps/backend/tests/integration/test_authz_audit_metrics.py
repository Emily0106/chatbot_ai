import pytest

pytestmark = pytest.mark.integration
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.security.auth import require_auth, AuthClaims
from app.core import metrics

client = TestClient(app)

@pytest.fixture
def mock_audit_logger():
    with patch("app.core.audit.audit.audit_logger") as mock:
        yield mock

# Helper to clear overrides
@pytest.fixture(autouse=True)
def clean_deps():
    app.dependency_overrides = {}
    yield
    app.dependency_overrides = {}

def test_rbac_denied_audit_and_metrics_blocking(mock_audit_logger):
    """
    Test A: RBAC denied logs audit + metrics (blocking)
    """
    # 1. Setup Auth: Allow "citizen" only
    claims = AuthClaims(
        tenant_id="t1", 
        sub="u1", 
        roles=["user"], 
        allowed_agents=["citizen"],
        security_level=1
    )
    app.dependency_overrides[require_auth] = lambda: claims
    
    # 2. Request restricted agent
    res = client.post(
        "/api/chat",
        json={"message": "secret", "agent_id": "doc_manager", "stream": False},
    )
    
    # 3. Assert Response
    assert res.status_code == 403
    
    # 4. Assert Audit Log
    assert mock_audit_logger.info.called
    logs = [json.loads(c[0][0]) for c in mock_audit_logger.info.call_args_list]
    denial_log = next((l for l in logs if l.get("event") == "authz.denied"), None)
    
    assert denial_log is not None
    assert denial_log["reason"] == "agent_not_allowed"
    assert denial_log["agent_id"] == "doc_manager"
    assert denial_log["allowed_agents"] == ["citizen"]
    assert denial_log["allowed_agents_count"] == 1
    # PII Check
    assert "message" not in denial_log
    assert "query" not in denial_log
    assert "query_len" in denial_log
    
    # 5. Assert Metrics via /metrics endpoint
    # Note: Metrics accumulate global state, so we check for presence/increase
    metrics_res = client.get("/metrics")
    assert metrics_res.status_code == 200
    metrics_text = metrics_res.text
    
    # Option A check
    assert 'govai_chat_requests_total{agent_id="doc_manager",lane="all",status="denied",stream="false"}' in metrics_text
    # Option B check (New metric)
    assert 'govai_authz_denials_total{agent_id="doc_manager",reason="agent_not_allowed",stream="false"}' in metrics_text

def test_security_escalation_denied_audit_metrics_blocking(mock_audit_logger):
    """
    Test B: Security level escalation denied logs audit + metrics (blocking)
    """
    # 1. Setup Auth: Security Level 1
    claims = AuthClaims(
        tenant_id="t1", 
        sub="u1", 
        roles=["user"], 
        allowed_agents=["citizen"],
        security_level=1
    )
    app.dependency_overrides[require_auth] = lambda: claims
    
    # Patch strict mode = True to enforce check
    with patch("app.security.policy.get_strict_mode", return_value=True):
        # 2. Request Security Level 5
        res = client.post(
            "/api/chat",
            json={"message": "top secret", "agent_id": "citizen", "security_level": 5, "stream": False},
        )
    
    # 3. Assert Response
    assert res.status_code == 403
    assert "Security level escalation denied" in res.json()["detail"]
    
    # 4. Assert Audit
    assert mock_audit_logger.info.called
    logs = [json.loads(c[0][0]) for c in mock_audit_logger.info.call_args_list]
    denial_log = next((l for l in logs if l.get("event") == "authz.denied"), None)
    
    assert denial_log is not None
    assert denial_log["reason"] == "security_level_escalation"
    assert denial_log["requested_level"] == 5
    assert denial_log["user_level"] == 1
    
    # 5. Assert Metrics
    metrics_res = client.get("/metrics")
    assert 'govai_authz_denials_total{agent_id="citizen",reason="security_level_escalation",stream="false"}' in metrics_res.text

def test_streaming_denial_audit_metrics(mock_audit_logger):
    """
    Test C: Streaming denial returns HTTP 403 and metrics reflect denied (stream=True)
    """
    # 1. Setup Auth: Deny access
    claims = AuthClaims(
        tenant_id="t1", 
        sub="u1", 
        roles=["user"], 
        allowed_agents=["citizen"],
        security_level=1
    )
    app.dependency_overrides[require_auth] = lambda: claims
    
    # 2. Request stream from forbidden agent
    res = client.post(
        "/api/chat",
        json={"message": "hi", "agent_id": "doc_manager", "stream": True},
    )
    
    # 3. Assert Response
    assert res.status_code == 403
    # Ensure NOT text/event-stream (fail closed before stream starts)
    assert "text/event-stream" not in res.headers.get("content-type", "")
    
    # 4. Assert Audit
    logs = [json.loads(c[0][0]) for c in mock_audit_logger.info.call_args_list if c[0]]
    denial_log = next((l for l in logs if l.get("event") == "authz.denied"), None)
    assert denial_log is not None
    assert denial_log["stream"] is True
    
    # 5. Assert Metrics
    metrics_res = client.get("/metrics")
    assert 'govai_authz_denials_total{agent_id="doc_manager",reason="agent_not_allowed",stream="true"}' in metrics_res.text
