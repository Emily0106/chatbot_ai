from __future__ import annotations

from uuid import uuid4
from unittest.mock import MagicMock

import app.workers.worker_main as worker_main


def _patch_repos(monkeypatch, pg: MagicMock, orch: MagicMock) -> None:
    monkeypatch.setattr(worker_main, "get_pg_repo", lambda: pg)
    monkeypatch.setattr(worker_main, "get_orchestrator", lambda: orch)


def test_delete_tenant_mismatch_skips_destructive_calls(monkeypatch) -> None:
    job_id = uuid4()
    pg = MagicMock()
    pg.get_job.return_value = {
        "job_id": str(job_id),
        "job_type": "delete",
        "doc_id": "doc-1",
        "meta": {"tenant_id": "tenant-a"},
    }
    pg.get_document_for_tenant.return_value = None

    orch = MagicMock()
    _patch_repos(monkeypatch, pg, orch)

    res = worker_main.run_job(str(job_id))

    assert res["ok"] is False
    assert res["error"] == "delete_job_tenant_mismatch"
    pg.get_document_for_tenant.assert_called_once_with("doc-1", "tenant-a", include_deleted=True)
    pg.soft_delete_document_for_tenant.assert_not_called()
    pg.delete_chunks_rows_for_doc.assert_not_called()
    orch.qdrant_repo.delete_by_doc_id_and_tenant.assert_not_called()


def test_delete_owned_doc_calls_soft_delete_and_tenant_qdrant_delete(monkeypatch) -> None:
    job_id = uuid4()
    pg = MagicMock()
    pg.get_job.return_value = {
        "job_id": str(job_id),
        "job_type": "delete",
        "doc_id": "doc-2",
        "meta": {"tenant_id": "tenant-b"},
    }
    pg.get_document_for_tenant.return_value = {"doc_id": "doc-2"}
    pg.soft_delete_document_for_tenant.return_value = 1

    orch = MagicMock()
    _patch_repos(monkeypatch, pg, orch)
    bump = MagicMock(return_value=2)
    monkeypatch.setattr(worker_main, "_bump_tenant_epoch", bump)

    res = worker_main.run_job(str(job_id))

    assert res["ok"] is True
    assert res["job_type"] == "delete"
    pg.get_document_for_tenant.assert_called_once_with("doc-2", "tenant-b", include_deleted=True)
    pg.soft_delete_document_for_tenant.assert_called_once_with("doc-2", "tenant-b")
    pg.delete_chunks_rows_for_doc.assert_called_once_with("doc-2")
    orch.qdrant_repo.delete_by_doc_id_and_tenant.assert_called_once_with("doc-2", "tenant-b")
    bump.assert_called_once_with("tenant-b")


def test_reindex_tenant_mismatch_fails_closed(monkeypatch) -> None:
    job_id = uuid4()
    pg = MagicMock()
    pg.get_job.return_value = {
        "job_id": str(job_id),
        "job_type": "reindex",
        "doc_id": "doc-3",
        "meta": {"tenant_id": "tenant-c"},
    }
    pg.get_document_for_tenant.return_value = None

    orch = MagicMock()
    _patch_repos(monkeypatch, pg, orch)

    res = worker_main.run_job(str(job_id))

    assert res["ok"] is False
    assert res["error"] == "reindex_job_tenant_mismatch"
    pg.get_document_for_tenant.assert_called_once_with("doc-3", "tenant-c")
    orch.process.assert_not_called()


def test_delete_already_deleted_same_tenant_is_idempotent_success(monkeypatch) -> None:
    job_id = uuid4()
    pg = MagicMock()
    pg.get_job.return_value = {
        "job_id": str(job_id),
        "job_type": "delete",
        "doc_id": "doc-4",
        "meta": {"tenant_id": "tenant-d"},
    }
    pg.get_document_for_tenant.return_value = {"doc_id": "doc-4", "is_deleted": True}
    pg.soft_delete_document_for_tenant.return_value = 0

    orch = MagicMock()
    _patch_repos(monkeypatch, pg, orch)
    bump = MagicMock(return_value=3)
    monkeypatch.setattr(worker_main, "_bump_tenant_epoch", bump)

    res = worker_main.run_job(str(job_id))

    assert res["ok"] is True
    assert res["job_type"] == "delete"
    pg.get_document_for_tenant.assert_called_once_with("doc-4", "tenant-d", include_deleted=True)
    pg.soft_delete_document_for_tenant.assert_called_once_with("doc-4", "tenant-d")
    pg.delete_chunks_rows_for_doc.assert_called_once_with("doc-4")
    orch.qdrant_repo.delete_by_doc_id_and_tenant.assert_called_once_with("doc-4", "tenant-d")
    bump.assert_called_once_with("tenant-d")


def test_reindex_success_bumps_tenant_epoch(monkeypatch) -> None:
    job_id = uuid4()
    pg = MagicMock()
    pg.get_job.return_value = {
        "job_id": str(job_id),
        "job_type": "reindex",
        "doc_id": "doc-9",
        "meta": {
            "tenant_id": "tenant-z",
            "scope": "public",
            "doc_type": "law",
            "security_level": 1,
        },
        "mime_type": "text/plain",
        "source_uri": "/tmp/doc-9.txt",
        "checksum": "abc",
        "title": "doc-9",
        "pipeline_version": "v1",
    }
    pg.get_document_for_tenant.return_value = {"doc_id": "doc-9"}

    orch = MagicMock()
    orch.process.return_value = {"chunks": 1, "rows": 0, "embedded_chunks": 1, "doc_id": "doc-9"}

    _patch_repos(monkeypatch, pg, orch)
    monkeypatch.setattr(worker_main, "_ensure_qdrant_parity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker_main, "get_qdrant_client", lambda: MagicMock())
    bump = MagicMock(return_value=4)
    monkeypatch.setattr(worker_main, "_bump_tenant_epoch", bump)

    res = worker_main.run_job(str(job_id))

    assert res["ok"] is True
    assert res["doc_id"] == "doc-9"
    bump.assert_called_once_with("tenant-z")
