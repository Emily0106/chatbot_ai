
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.workers.worker_main import _on_worker_start, run_job
from app.preproc.stores.postgres_repo import PostgresRepo

@pytest.fixture
def mock_pg():
    pg = MagicMock(spec=PostgresRepo)
    with patch("app.workers.worker_main.get_pg_repo", return_value=pg):
        yield pg

@pytest.fixture
def mock_orch():
    orch = MagicMock()
    orch.qdrant_repo.client = MagicMock()
    orch.qdrant_repo.cfg.collection_name = "test_collection"
    with patch("app.workers.worker_main.get_orchestrator", return_value=orch):
        yield orch

def test_zombie_killer(mock_pg):
    """
    Test that stale running jobs are marked as failed on startup.
    """
    # Simulate DB returning 5 stale jobs
    mock_pg.fail_stale_running_jobs.return_value = 5
    
    # Run startup hook
    # Note: We can't easily run celery signal handlers directly without context, 
    # but we can call the decorated function logic if we extract it or if we mock env.
    
    with patch("app.workers.worker_main.ensure_qdrant_schema"), patch(
        "app.workers.worker_main._extract_vector_size", return_value=768
    ):
        with patch("app.workers.worker_main.get_orchestrator"):
            _on_worker_start()
             
    mock_pg.fail_stale_running_jobs.assert_called_once()


def test_schema_enforcer_init(mock_orch, mock_pg):
    """
    Test that Qdrant schema is checked on startup.
    """
    with patch("app.workers.worker_main.ensure_qdrant_schema") as mock_ensure, patch(
        "app.workers.worker_main._extract_vector_size", return_value=768
    ):
        _on_worker_start()
        mock_ensure.assert_called_once_with(mock_orch.qdrant_repo.client, "test_collection")

def test_metadata_propagation(mock_pg, mock_orch):
    """
    Test that _score_kind is injected into IngestMeta during run_job.
    """
    job_id = uuid4()
    job_data = {
        "job_id": str(job_id),
        "job_type": "ingest",
        "mime_type": "text/plain",
        "source_uri": "s3://bucket/file.txt",
        "checksum": "abc",
        "title": "Test Doc",
        "scope": "public",
        "tenant_id": "T1",
        "pipeline_version": "v1",
        "meta": {"tenant_id": "T1", "doc_type": "law"}
    }
    mock_pg.get_job.return_value = job_data
    mock_orch.process.return_value = {"doc_id": "123", "chunks": 1, "rows": 0, "embedded_chunks": 1}
    
    with patch("app.workers.worker_main._ensure_qdrant_parity"):
        res = run_job(str(job_id))
    print(f"RunJob Result: {res}")
    assert res["ok"] is True
    
    # Verify Orchestrator was called with meta containing _score_kind
    args, _ = mock_orch.process.call_args
    uri, meta = args
    assert meta.metadata.get("_score_kind") == "cosine"
