import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

pytestmark = pytest.mark.integration

client = TestClient(app)

# Use the default dev key logic
# key: "dev-key-123" -> tenant: "default"

@pytest.fixture(autouse=True)
def _reset_auth_env():
    """Reset ENV_MODE to dev before each test to prevent state leakage"""
    original_env_mode = settings.ENV_MODE
    settings.ENV_MODE = "dev"  # Reset to safe default
    yield
    settings.ENV_MODE = original_env_mode  # Restore

def test_chat_missing_header_401():
    """Missing X-API-Key header -> 401"""
    res = client.post("/api/chat", json={"message": "hi", "agent_id": "citizen"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Missing X-API-Key header"

def test_chat_invalid_key_401():
    """Invalid X-API-Key -> 401"""
    res = client.post("/api/chat", json={"message": "hi"}, headers={"X-API-Key": "wrong"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid API Key"

def test_chat_valid_key_pass_in_dev(monkeypatch):
    """Valid X-API-Key -> 200 (or validation error 422) IN DEV MODE"""
    # Force Dev Mode
    monkeypatch.setattr(settings, "ENV_MODE", "dev")
    # Force empty API_KEYS_JSON so fallback runs
    monkeypatch.setenv("API_KEYS_JSON", "")
    # Note: _load_api_keys reads env var directly or settings check. 
    # Since we modified auth.py to read settings, we rely on settings being modifiable or environment being set.
    # settings is instantiated global, so patching it works if auth.py refers to 'settings' module object.
    
    res = client.post(
        "/api/chat", 
        json={"message": "test", "agent_id": "citizen"},
        headers={"X-API-Key": "dev-key-123"}
    )
    assert res.status_code != 401

def test_fail_closed_prod_mode(monkeypatch):
    """Ensure in PROD mode, default key is ILLEGAL if config missing -> 401"""
    # Force Prod Mode (must also disable CI_MODE which auto-loads dev keys)
    monkeypatch.setattr(settings, "ENV_MODE", "prod")
    monkeypatch.setattr(settings, "CI_MODE", False)  # Critical: disable CI mode
    monkeypatch.setenv("API_KEYS_JSON", "") # Empty config
    
    res = client.post(
        "/api/chat", 
        json={"message": "hi", "agent_id": "citizen"},  # Include required field
        headers={"X-API-Key": "dev-key-123"} # Try using the dev key
    )
    # MUST FAIL because dev key should not exist
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid API Key"
