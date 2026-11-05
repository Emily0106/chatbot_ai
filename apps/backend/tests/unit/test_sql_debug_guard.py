from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.sql_debug import router as sql_debug_router
from app.config import settings


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(sql_debug_router, prefix="/api")
    return TestClient(app)


def test_sql_debug_plan_requires_admin_key(monkeypatch):
    monkeypatch.setattr(settings, "OPS_CONSOLE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OPS_ADMIN_KEY", "ops-secret", raising=False)
    client = _make_client()

    resp = client.post(
        "/api/debug/sql/plan",
        json={"sql": "select * from view_people", "tenant_id": "tenant_a"},
    )
    assert resp.status_code == 401


def test_sql_debug_plan_rejects_wrong_admin_key(monkeypatch):
    monkeypatch.setattr(settings, "OPS_CONSOLE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OPS_ADMIN_KEY", "ops-secret", raising=False)
    client = _make_client()

    resp = client.post(
        "/api/debug/sql/plan",
        headers={"X-Admin-Key": "wrong"},
        json={"sql": "select * from view_people", "tenant_id": "tenant_a"},
    )
    assert resp.status_code == 403


def test_sql_debug_plan_allows_valid_admin_key(monkeypatch):
    monkeypatch.setattr(settings, "OPS_CONSOLE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OPS_ADMIN_KEY", "ops-secret", raising=False)
    client = _make_client()

    resp = client.post(
        "/api/debug/sql/plan",
        headers={"X-Admin-Key": "ops-secret"},
        json={"sql": "select * from view_people", "tenant_id": "tenant_a"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ALLOWED"
    assert body["safe_sql"]
