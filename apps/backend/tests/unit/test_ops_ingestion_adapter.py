from __future__ import annotations

from typing import Any, Dict

import pytest

from app.core.ops.ingestion_adapter import IngestionOpsClient
import app.core.ops.ingestion_adapter as ingestion_adapter


class _Resp:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)
        self.content = b"1"

    def json(self):
        return self._payload


class _Client:
    def __init__(self, store: Dict[str, Any], response: _Resp):
        self.store = store
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, *, method: str, url: str, headers: dict, params=None, json=None):
        self.store["method"] = method
        self.store["url"] = url
        self.store["headers"] = headers
        self.store["params"] = params
        self.store["json"] = json
        return self.response


@pytest.fixture(autouse=True)
def _set_internal_token(monkeypatch):
    monkeypatch.setattr(ingestion_adapter.settings, "INGEST_INTERNAL_TOKEN", "internal-test-token", raising=False)


@pytest.mark.asyncio
async def test_list_jobs_builds_expected_request(monkeypatch):
    seen: Dict[str, Any] = {}
    resp = _Resp(200, [{"job_id": "j1"}])

    monkeypatch.setattr(ingestion_adapter.httpx, "AsyncClient", lambda timeout: _Client(seen, resp))

    c = IngestionOpsClient(base_url="http://ingest-api:8010")
    rows = await c.list_jobs(tenant_id="tenant-a", limit=55)

    assert rows == [{"job_id": "j1"}]
    assert seen["method"] == "GET"
    assert seen["url"] == "http://ingest-api:8010/api/v1/admin/jobs"
    assert seen["headers"]["X-GOVAI-TENANT-ID"] == "tenant-a"
    assert seen["headers"]["X-Internal-Token"] == "internal-test-token"
    assert seen["params"]["limit"] == 55


@pytest.mark.asyncio
async def test_list_documents_sends_filters(monkeypatch):
    seen: Dict[str, Any] = {}
    resp = _Resp(200, [{"doc_id": "d1"}])
    monkeypatch.setattr(ingestion_adapter.httpx, "AsyncClient", lambda timeout: _Client(seen, resp))

    c = IngestionOpsClient(base_url="http://ingest-api:8010")
    rows = await c.list_documents(
        tenant_id="tenant-b",
        scope="public",
        doc_type="law",
        is_deleted=False,
        limit=10,
    )

    assert rows == [{"doc_id": "d1"}]
    assert seen["url"] == "http://ingest-api:8010/api/v1/admin/documents"
    assert seen["params"] == {
        "limit": 10,
        "scope": "public",
        "doc_type": "law",
        "is_deleted": False,
    }


@pytest.mark.asyncio
async def test_delete_doc_uses_delete_method(monkeypatch):
    seen: Dict[str, Any] = {}
    resp = _Resp(200, {"status": "accepted"})
    monkeypatch.setattr(ingestion_adapter.httpx, "AsyncClient", lambda timeout: _Client(seen, resp))

    c = IngestionOpsClient(base_url="http://ingest-api:8010")
    body = await c.delete_doc(tenant_id="tenant-c", doc_id="doc-9")

    assert body["status"] == "accepted"
    assert seen["method"] == "DELETE"
    assert seen["url"] == "http://ingest-api:8010/api/v1/docs/doc-9"


@pytest.mark.asyncio
async def test_adapter_raises_runtime_error_on_http_failure(monkeypatch):
    seen: Dict[str, Any] = {}
    resp = _Resp(404, {"detail": "not found"})
    monkeypatch.setattr(ingestion_adapter.httpx, "AsyncClient", lambda timeout: _Client(seen, resp))

    c = IngestionOpsClient(base_url="http://ingest-api:8010")
    with pytest.raises(RuntimeError) as exc:
        await c.reindex_doc(tenant_id="tenant-z", doc_id="doc-x")

    assert "Ingestion request failed 404" in str(exc.value)


def test_adapter_fails_closed_without_internal_token(monkeypatch):
    monkeypatch.setattr(ingestion_adapter.settings, "INGEST_INTERNAL_TOKEN", "", raising=False)
    c = IngestionOpsClient(base_url="http://ingest-api:8010")
    with pytest.raises(RuntimeError) as exc:
        c._headers("tenant-a")
    assert "INGEST_INTERNAL_TOKEN is required" in str(exc.value)
