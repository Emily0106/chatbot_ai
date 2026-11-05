from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth_context import require_internal_token
from app.core.config import settings


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/guarded", dependencies=[Depends(require_internal_token)])
    def guarded() -> dict:
        return {"ok": True}

    return app


def test_guard_returns_503_when_token_not_configured() -> None:
    settings.INGEST_INTERNAL_TOKEN = ""
    client = TestClient(_build_app())

    resp = client.get("/guarded")
    assert resp.status_code == 503


def test_guard_returns_401_when_header_missing() -> None:
    settings.INGEST_INTERNAL_TOKEN = "secret-token"
    client = TestClient(_build_app())

    resp = client.get("/guarded")
    assert resp.status_code == 401


def test_guard_returns_403_when_token_invalid() -> None:
    settings.INGEST_INTERNAL_TOKEN = "secret-token"
    client = TestClient(_build_app())

    resp = client.get("/guarded", headers={"X-Internal-Token": "wrong"})
    assert resp.status_code == 403


def test_guard_allows_valid_token() -> None:
    settings.INGEST_INTERNAL_TOKEN = "secret-token"
    client = TestClient(_build_app())

    resp = client.get("/guarded", headers={"X-Internal-Token": "secret-token"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
