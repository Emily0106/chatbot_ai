from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.canonical_models import IngestionProfile
from app.api.routes.admin import JobSubmissionResponse
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

@pytest.fixture
def mock_pg():
    with patch("app.api.routes.admin.PostgresRepo") as mock_repo_cls:
        mock_instance = mock_repo_cls.return_value
        yield mock_instance

@pytest.fixture
def mock_celery():
    with patch("app.workers.worker_main.celery_app") as mock_cel:
        yield mock_cel

def test_presign_upload(mock_pg):
    # Setup
    profile_id = str(uuid4())
    mock_pg.get_profile.return_value = {
        "profile_id": profile_id,
        "tenant_id": "default",
        "name": "Legal Private",
        "config": {}
    }
    
    payload = {
        "profile_id": profile_id,
        "filename": "contract.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1024
    }
    
    headers = {
        "X-GOVAI-TENANT-ID": "default",
        "X-GOVAI-USER-ROLE": "admin"
    }
    
    # Execute
    response = client.post(
        "/api/v1/admin/upload/presign",
        json=payload,
        headers=_with_internal_token(headers),
    )
    
    # Verify
    assert response.status_code == 200
    data = response.json()
    assert "upload_url" in data
    assert "object_key" in data
    assert "raw/default/" in data["object_key"]

def test_submit_job_quarantine(mock_pg, mock_celery):
    # Setup: Profile with auto_approve=False (default) -> Quarantine
    profile_id = str(uuid4())
    mock_pg.get_profile.return_value = {
        "profile_id": profile_id,
        "tenant_id": "default",
        "name": "Sensitive Docs",
        "config": {"auto_approve": False, "scope": "restricted"}
    }
    
    payload = {
        "profile_id": profile_id,
        "files": [
            {
                "object_key": "raw/default/file1.pdf",
                "original_name": "file1.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1000,
                "checksum": "sha256:123"
            }
        ],
        "note": "Sensitive upload"
    }
    
    headers = {
        "X-GOVAI-TENANT-ID": "default",
        "X-GOVAI-USER-ROLE": "officer"
    }
    
    # Execute
    response = client.post("/api/v1/admin/jobs", json=payload, headers=_with_internal_token(headers))
    
    # Verify Response
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending_approval"
    
    # Verify Repo Call
    mock_pg.create_job_with_profile.assert_called_once()
    call_args = mock_pg.create_job_with_profile.call_args[1]
    assert call_args["status"] == "pending_approval"
    assert call_args["meta"]["scope"] == "restricted" # Derived from Profile
    
    # Verify Worker NOT triggered
    mock_celery.send_task.assert_not_called()

def test_approve_job(mock_pg, mock_celery):
    # Setup
    job_id = str(uuid4())
    mock_pg.get_job.return_value = {"job_id": job_id, "status": "pending_approval"}
    
    headers = {
        "X-GOVAI-TENANT-ID": "default",
        "X-GOVAI-USER-ROLE": "admin"
    }
    
    # Execute
    response = client.post(
        f"/api/v1/admin/jobs/{job_id}/approve",
        headers=_with_internal_token(headers),
    )
    
    # Verify
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    
    # Verify Status Update
    from uuid import UUID as UUID_Type
    mock_pg.update_job_approval.assert_called_with(
        job_id=UUID_Type(job_id),
        status="queued",
        approved_by="UserRole.ADMIN",
        approver_role="UserRole.ADMIN"
    )
    
    # Verify Worker Triggered
    mock_celery.send_task.assert_called_with("ingestion.run_job", args=[job_id])
