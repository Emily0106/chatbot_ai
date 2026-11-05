import pytest

pytestmark = pytest.mark.integration
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_metrics_endpoint_exists():
    """
    Test B7.1: Verify /metrics endpoint exists and returns prometheus text.
    """
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "govai_chat_requests_total" in resp.text
    assert "govai_chat_latency_seconds" in resp.text
    assert "govai_gate_fail_total" in resp.text
    assert "govai_streams_active" in resp.text
    assert "govai_inflight_active" in resp.text

def test_metrics_format():
    """
    Test B7.2: Verify metrics are in Prometheus exposition format.
    """
    resp = client.get("/metrics")
    assert resp.status_code == 200
    # Should contain TYPE and HELP comments
    assert "# TYPE govai_chat_requests_total counter" in resp.text
    assert "# TYPE govai_chat_latency_seconds histogram" in resp.text
