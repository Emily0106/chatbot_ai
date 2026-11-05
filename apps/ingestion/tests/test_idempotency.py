
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.api.endpoints import router
from app.main import app
from app.core.config import settings

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

def test_duplicate_upload_idempotency(tmp_path, monkeypatch):
    """
    Verify that uploading the same file twice results in success (202) both times.
    And jobs are created/enqueued both times (or reused).
    """
    # Mock storage path to separate from real env
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))

    files = {'file': ('duplicate.txt', b'hello world content', 'text/plain')}
    data = {
        'doc_type': 'law',
        'scope': 'public',
        'security_level': 1
    }
    headers = _with_internal_token({"X-GOVAI-TENANT-ID": "tenant_test"})

    with patch("app.api.endpoints._pg") as mock_pg:
        mock_repo = MagicMock()
        mock_pg.return_value = mock_repo
        
        # Mock create_job to succeed
        mock_repo.create_job.return_value = None

        with patch("app.api.endpoints.celery_app.send_task") as mock_send:
            # First Upload
            r1 = client.post("/api/v1/ingest", files=files, data=data, headers=headers)
            assert r1.status_code == 202
            job1 = r1.json()["job_id"]

            # Second Upload (Same content)
            # Need to re-create file tuple as requests consumes it? 
            # TestClient usually handles it but safer to recreate
            files2 = {'file': ('duplicate.txt', b'hello world content', 'text/plain')}
            r2 = client.post("/api/v1/ingest", files=files2, data=data, headers=headers)
            assert r2.status_code == 202
            job2 = r2.json()["job_id"]

            # Requirement: Job IDs should be present (new or reused)
            assert job1
            assert job2
            
            # Since we implemented "Always create job", we expect 2 calls
            assert mock_repo.create_job.call_count == 2
            assert mock_send.call_count == 2
