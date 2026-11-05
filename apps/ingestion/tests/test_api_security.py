import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.core.taxonomy import IngestionError

TEST_INTERNAL_TOKEN = "test-internal-token"
client = TestClient(app)


def _with_internal_token(headers: dict | None = None) -> dict:
    merged = {"X-Internal-Token": TEST_INTERNAL_TOKEN}
    if headers:
        merged.update(headers)
    return merged


@pytest.fixture(autouse=True)
def _set_internal_token(monkeypatch):
    monkeypatch.setattr(settings, "INGEST_INTERNAL_TOKEN", TEST_INTERNAL_TOKEN, raising=False)

def test_reject_missing_tenant_header():
    """Fail-closed: Missing X-GOVAI-TENANT-ID should be rejected."""
    files = {'file': ('test.txt', b'content', 'text/plain')}
    data = {
        'doc_type': 'law',
        'scope': 'public',
        'security_level': 1
    }
    response = client.post("/api/v1/ingest", files=files, data=data, headers=_with_internal_token())
    # FastAPI Header(..., alias=...) missing raises 422 by default
    assert response.status_code == 422 

def test_reject_internal_missing_dept():
    """Fail-closed: INTERNAL scope requires X-GOVAI-DEPARTMENT-ID."""
    files = {'file': ('test.txt', b'content', 'text/plain')}
    data = {
        'doc_type': 'law',
        'scope': 'internal',
        'security_level': 2
    }
    headers = {
        "X-GOVAI-TENANT-ID": "tenant_1"
    }
    response = client.post("/api/v1/ingest", files=files, data=data, headers=_with_internal_token(headers))
    assert response.status_code == 403
    json_resp = response.json()
    assert json_resp["detail"]["code"] == IngestionError.ERR_MISSING_DEPARTMENT_CONTEXT.value

def test_accept_valid_request():
    """Happy path: Trusted context present."""
    # We need to mock Postgres/Redis to not crash on DB connection?
    # Or expect 500 but at least pass security gate?
    # endpoints.py calls _pg() -> PostgresRepo -> might fail if DB not running.
    # But security check happens BEFORE DB.
    # So we can mock app.api.endpoints._pg if needed.
    
    files = {'file': ('test.txt', b'content', 'text/plain')}
    data = {
        'doc_type': 'law',
        'scope': 'public',
        'security_level': 1
    }
    headers = {
        "X-GOVAI-TENANT-ID": "tenant_1"
    }
    
    from unittest.mock import patch, MagicMock
    
    with patch("app.api.endpoints._pg") as mock_pg:
        mock_repo = MagicMock()
        mock_pg.return_value = mock_repo
        
        with patch("app.api.endpoints.celery_app.send_task"):
            response = client.post(
                "/api/v1/ingest",
                files=files,
                data=data,
                headers=_with_internal_token(headers),
            )
            assert response.status_code == 202
            assert response.json()["status"] == "accepted"

def test_reject_restricted_low_level():
    """Fail-closed: RESTRICTED scope requires security_level >= 3."""
    files = {'file': ('test.txt', b'content', 'text/plain')}
    data = {
        'doc_type': 'law',
        'scope': 'restricted',
        'security_level': 2 # Too low
    }
    headers = {
        "X-GOVAI-TENANT-ID": "tenant_1"
    }
    response = client.post("/api/v1/ingest", files=files, data=data, headers=_with_internal_token(headers))
    assert response.status_code == 403
    # Check standardized error format
    json_resp = response.json()
    assert json_resp["detail"]["code"] == "ERR_SCOPE_SECURITY_VIOLATION"
    assert "RESTRICTED scope" in json_resp["detail"]["message"]
