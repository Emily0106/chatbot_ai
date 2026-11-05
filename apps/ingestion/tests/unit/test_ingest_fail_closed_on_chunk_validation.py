from __future__ import annotations

from uuid import uuid4
from unittest.mock import MagicMock

import app.workers.worker_main as worker_main


def _job_dict(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "job_type": "ingest",
        "meta": {
            "tenant_id": "tenant-a",
            "doc_type": "other",
            "scope": "public",
            "security_level": 1,
        },
        "mime_type": "text/plain",
        "source_uri": "/tmp/e2e_doc.txt",
        "checksum": "abc123",
        "title": "e2e_doc.txt",
        "pipeline_version": "v1",
    }


def test_ingest_zero_chunks_is_fail_closed(monkeypatch) -> None:
    """
    Guard against fail-open behavior:
    if ingest processing returns zero chunks and zero rows, job must be failed.
    """
    job_id = uuid4()
    pg = MagicMock()
    pg.get_job.return_value = _job_dict(str(job_id))

    orch = MagicMock()
    orch.process.return_value = {
        "doc_id": str(uuid4()),
        "chunks": 0,
        "rows": 0,
        "embedded_chunks": 0,
    }

    monkeypatch.setattr(worker_main, "get_pg_repo", lambda: pg)
    monkeypatch.setattr(worker_main, "get_orchestrator", lambda: orch)
    monkeypatch.setattr(worker_main, "get_qdrant_client", lambda: MagicMock())
    monkeypatch.setattr(worker_main, "_ensure_qdrant_parity", lambda client, collection: None)

    res = worker_main.run_job(str(job_id))

    assert res["ok"] is False
    assert "empty" in str(res.get("error", "")).lower()
    assert any(
        kwargs.get("status") == "failed"
        for _, kwargs in (call for call in pg.update_job.call_args_list)
    )
