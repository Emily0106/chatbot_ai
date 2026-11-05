from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
import app.api.routes.ops_console as ops_console


def _request(path: str = "/ops", *, headers: dict[str, str] | None = None, query_string: str = "") -> Request:
    raw_headers = []
    for k, v in (headers or {}).items():
        raw_headers.append((k.lower().encode("utf-8"), str(v).encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query_string.encode("utf-8"),
        "headers": raw_headers,
        "client": ("127.0.0.1", 4321),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _ops_defaults(monkeypatch):
    monkeypatch.setattr(settings, "OPS_CONSOLE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OPS_ADMIN_KEY", "ops-secret", raising=False)


def test_ops_returns_404_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "OPS_CONSOLE_ENABLED", False, raising=False)
    with pytest.raises(HTTPException) as exc:
        ops_console.require_ops_admin(_request())
    assert exc.value.status_code == 404


def test_ops_requires_admin_key_header_when_no_cookie():
    with pytest.raises(HTTPException) as exc:
        ops_console.require_ops_admin(_request())
    assert exc.value.status_code == 401


def test_ops_rejects_wrong_admin_key():
    with pytest.raises(HTTPException) as exc:
        ops_console.require_ops_admin(_request(headers={"X-Admin-Key": "wrong"}))
    assert exc.value.status_code == 403


def test_ops_allows_correct_admin_key():
    ctx = ops_console.require_ops_admin(_request(headers={"X-Admin-Key": "ops-secret"}))
    assert ctx["auth_via"] == "header"
    assert ctx["actor_id"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_ops_requires_tenant_filter_before_query(monkeypatch):
    called = {"jobs": 0, "docs": 0}

    class StubClient:
        async def list_jobs(self, *, tenant_id: str, limit: int = 100):
            called["jobs"] += 1
            return []

        async def list_documents(self, *, tenant_id: str, scope=None, doc_type=None, is_deleted=None, limit: int = 100):
            called["docs"] += 1
            return []

    monkeypatch.setattr(ops_console, "_ops_client", lambda: StubClient())
    monkeypatch.setattr(ops_console, "cache_get_tenant_epoch", AsyncMock(return_value=(0, False)))

    resp = await ops_console.ops_console(
        request=_request(headers={"X-Admin-Key": "ops-secret"}),
        tenant_id="",
        scope="",
        doc_type="",
        is_deleted="",
        admin={"actor_id": "tester", "auth_via": "header"},
    )
    assert resp.status_code == 200
    body = resp.body.decode("utf-8")
    assert "tenant_id is required before querying jobs/documents." in body
    assert called["jobs"] == 0
    assert called["docs"] == 0


@pytest.mark.asyncio
async def test_action_delete_calls_ingestion_with_expected_payload(monkeypatch):
    seen = {}

    class StubClient:
        async def delete_doc(self, *, tenant_id: str, doc_id: str):
            seen["tenant_id"] = tenant_id
            seen["doc_id"] = doc_id
            return {"status": "accepted", "job_id": "j-delete"}

    monkeypatch.setattr(ops_console, "_ops_client", lambda: StubClient())

    resp = await ops_console.ops_action_delete(
        request=_request(path="/ops/action/delete"),
        tenant_id="tenant-a",
        doc_id="doc-1",
        admin={"actor_id": "tester", "auth_via": "header"},
    )
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["ok"] is True
    assert body["action"] == "delete"
    assert body["result"]["job_id"] == "j-delete"
    assert seen == {"tenant_id": "tenant-a", "doc_id": "doc-1"}


@pytest.mark.asyncio
async def test_action_reindex_calls_ingestion_with_expected_payload(monkeypatch):
    seen = {}

    class StubClient:
        async def reindex_doc(self, *, tenant_id: str, doc_id: str):
            seen["tenant_id"] = tenant_id
            seen["doc_id"] = doc_id
            return {"status": "accepted", "job_id": "j-reindex"}

    monkeypatch.setattr(ops_console, "_ops_client", lambda: StubClient())

    resp = await ops_console.ops_action_reindex(
        request=_request(path="/ops/action/reindex"),
        tenant_id="tenant-a",
        doc_id="doc-1",
        admin={"actor_id": "tester", "auth_via": "header"},
    )
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["ok"] is True
    assert body["action"] == "reindex"
    assert body["result"]["job_id"] == "j-reindex"
    assert seen == {"tenant_id": "tenant-a", "doc_id": "doc-1"}


@pytest.mark.asyncio
async def test_action_bump_epoch_increments(monkeypatch):
    monkeypatch.setattr(ops_console, "cache_incr_tenant_epoch", AsyncMock(return_value=(9, True)))

    resp = await ops_console.ops_action_bump_epoch(
        request=_request(path="/ops/action/bump-epoch"),
        tenant_id="tenant-a",
        admin={"actor_id": "tester", "auth_via": "header"},
    )
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["ok"] is True
    assert body["new_epoch"] == 9
