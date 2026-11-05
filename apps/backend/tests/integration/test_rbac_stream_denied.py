import pytest

pytestmark = pytest.mark.integration

from unittest.mock import patch

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.security.auth import AuthClaims, require_auth


@pytest.mark.asyncio
async def test_streaming_access_denied_returns_403():
    claims = AuthClaims(
        tenant_id="t1",
        roles=["user"],
        security_level=1,
        allowed_agents=["citizen"],
    )
    app.dependency_overrides[require_auth] = lambda: claims
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/chat",
                json={"message": "hello", "agent_id": "doc_manager", "stream": True},
            )
        assert res.status_code == 403
        assert "Access denied" in res.json()["detail"]
        assert "text/event-stream" not in res.headers.get("content-type", "")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_streaming_security_escalation_denied_returns_403():
    claims = AuthClaims(tenant_id="t1", roles=["user"], security_level=1)
    app.dependency_overrides[require_auth] = lambda: claims
    try:
        with patch("app.security.policy.get_strict_mode", return_value=True):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                res = await ac.post(
                    "/api/chat",
                    json={
                        "message": "top secret",
                        "agent_id": "citizen",
                        "security_level": 5,
                        "stream": True,
                    },
                )
        assert res.status_code == 403
        assert "Security level escalation denied" in res.json()["detail"]
    finally:
        app.dependency_overrides.clear()
