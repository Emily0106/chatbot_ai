import pytest


@pytest.fixture(autouse=True)
def _disable_rate_limit_for_integration(monkeypatch):
    """Keep integration suite deterministic; rate-limit behavior is tested elsewhere."""
    from app.config import settings
    from app.agents.registry import register_defaults, registry

    monkeypatch.setattr(settings, "ENABLE_RATE_LIMITING", False)
    if not registry.list_agents():
        register_defaults()


@pytest.fixture
def auth_headers():
    return {"X-API-Key": "dev-key-123", "Content-Type": "application/json"}
