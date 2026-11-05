from __future__ import annotations

from uuid import UUID
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import app.api.endpoints as endpoints
from app.api.endpoints import delete_doc, reindex_doc
from app.core.auth_context import TrustedContext, UserRole


def _ctx(tenant_id: str) -> TrustedContext:
    return TrustedContext(
        tenant_id=tenant_id,
        geo_code="g01",
        user_role=UserRole.CITIZEN,
        is_trusted=True,
    )


def _doc_row() -> dict:
    return {
        "scope": "internal",
        "commune_id": "g01",
        "source_uri": "/tmp/doc.pdf",
        "mime_type": "application/pdf",
        "checksum": "abc123",
        "title": "Doc",
        "pipeline_version": "v2",
        "doc_category": "other",
    }


def _deleted_doc_row() -> dict:
    row = _doc_row()
    row["is_deleted"] = True
    return row


def test_reindex_wrong_tenant_returns_404(monkeypatch) -> None:
    pg = MagicMock()
    pg.get_document_for_tenant.return_value = None
    send_task = MagicMock()
    monkeypatch.setattr(endpoints, "_pg", lambda: pg)
    monkeypatch.setattr(endpoints.celery_app, "send_task", send_task)

    doc_id = "11111111-1111-1111-1111-111111111111"
    with pytest.raises(HTTPException) as exc:
        reindex_doc(doc_id, ctx=_ctx("tenant-a"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document not found (security)"
    pg.get_document_for_tenant.assert_called_once_with(UUID(doc_id), "tenant-a")
    send_task.assert_not_called()


def test_reindex_correct_tenant_enqueues_job(monkeypatch) -> None:
    pg = MagicMock()
    pg.get_document_for_tenant.return_value = _doc_row()
    send_task = MagicMock()
    monkeypatch.setattr(endpoints, "_pg", lambda: pg)
    monkeypatch.setattr(endpoints.celery_app, "send_task", send_task)

    doc_id = "22222222-2222-2222-2222-222222222222"
    resp = reindex_doc(doc_id, ctx=_ctx("tenant-a"))

    assert resp["status"] == "accepted"
    assert resp["doc_id"] == doc_id
    pg.get_document_for_tenant.assert_called_once_with(UUID(doc_id), "tenant-a")
    pg.create_job.assert_called_once()
    create_kwargs = pg.create_job.call_args.kwargs
    assert create_kwargs["scope"] == "internal"
    assert create_kwargs["meta"]["tenant_id"] == "tenant-a"
    pg.update_job.assert_called_once()
    send_task.assert_called_once()
    assert send_task.call_args.args[0] == "ingestion.run_job"


def test_reindex_nonexistent_doc_returns_404(monkeypatch) -> None:
    pg = MagicMock()
    pg.get_document_for_tenant.return_value = None
    send_task = MagicMock()
    monkeypatch.setattr(endpoints, "_pg", lambda: pg)
    monkeypatch.setattr(endpoints.celery_app, "send_task", send_task)

    doc_id = "33333333-3333-3333-3333-333333333333"
    with pytest.raises(HTTPException) as exc:
        reindex_doc(doc_id, ctx=_ctx("tenant-a"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document not found (security)"
    send_task.assert_not_called()


def test_reindex_deleted_doc_fails_closed_404(monkeypatch) -> None:
    pg = MagicMock()
    # get_document_for_tenant(include_deleted=False) should hide deleted docs.
    pg.get_document_for_tenant.return_value = None
    send_task = MagicMock()
    monkeypatch.setattr(endpoints, "_pg", lambda: pg)
    monkeypatch.setattr(endpoints.celery_app, "send_task", send_task)

    doc_id = "77777777-7777-7777-7777-777777777777"
    with pytest.raises(HTTPException) as exc:
        reindex_doc(doc_id, ctx=_ctx("tenant-a"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document not found (security)"
    send_task.assert_not_called()


def test_delete_wrong_tenant_returns_404(monkeypatch) -> None:
    pg = MagicMock()
    pg.get_document_for_tenant.return_value = None
    send_task = MagicMock()
    monkeypatch.setattr(endpoints, "_pg", lambda: pg)
    monkeypatch.setattr(endpoints.celery_app, "send_task", send_task)

    doc_id = "44444444-4444-4444-4444-444444444444"
    with pytest.raises(HTTPException) as exc:
        delete_doc(doc_id, ctx=_ctx("tenant-a"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document not found (security)"
    pg.get_document_for_tenant.assert_called_once_with(UUID(doc_id), "tenant-a", include_deleted=True)
    send_task.assert_not_called()


def test_delete_correct_tenant_enqueues_job(monkeypatch) -> None:
    pg = MagicMock()
    pg.get_document_for_tenant.return_value = _doc_row()
    send_task = MagicMock()
    monkeypatch.setattr(endpoints, "_pg", lambda: pg)
    monkeypatch.setattr(endpoints.celery_app, "send_task", send_task)

    doc_id = "55555555-5555-5555-5555-555555555555"
    resp = delete_doc(doc_id, ctx=_ctx("tenant-a"))

    assert resp["status"] == "accepted"
    assert resp["doc_id"] == doc_id
    pg.get_document_for_tenant.assert_called_once_with(UUID(doc_id), "tenant-a", include_deleted=True)
    pg.create_job.assert_called_once()
    create_kwargs = pg.create_job.call_args.kwargs
    assert create_kwargs["scope"] == "internal"
    assert create_kwargs["meta"]["tenant_id"] == "tenant-a"
    pg.update_job.assert_called_once()
    send_task.assert_called_once()
    assert send_task.call_args.args[0] == "ingestion.run_job"


def test_delete_nonexistent_doc_returns_404(monkeypatch) -> None:
    pg = MagicMock()
    pg.get_document_for_tenant.return_value = None
    send_task = MagicMock()
    monkeypatch.setattr(endpoints, "_pg", lambda: pg)
    monkeypatch.setattr(endpoints.celery_app, "send_task", send_task)

    doc_id = "66666666-6666-6666-6666-666666666666"
    with pytest.raises(HTTPException) as exc:
        delete_doc(doc_id, ctx=_ctx("tenant-a"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document not found (security)"
    send_task.assert_not_called()


def test_delete_already_deleted_same_tenant_returns_202_without_enqueue(monkeypatch) -> None:
    pg = MagicMock()
    pg.get_document_for_tenant.return_value = _deleted_doc_row()
    send_task = MagicMock()
    monkeypatch.setattr(endpoints, "_pg", lambda: pg)
    monkeypatch.setattr(endpoints.celery_app, "send_task", send_task)

    doc_id = "88888888-8888-8888-8888-888888888888"
    resp = delete_doc(doc_id, ctx=_ctx("tenant-a"))

    assert resp["status"] == "accepted"
    assert resp["doc_id"] == doc_id
    assert resp["already_deleted"] is True
    pg.get_document_for_tenant.assert_called_once_with(UUID(doc_id), "tenant-a", include_deleted=True)
    pg.create_job.assert_not_called()
    pg.update_job.assert_not_called()
    send_task.assert_not_called()
