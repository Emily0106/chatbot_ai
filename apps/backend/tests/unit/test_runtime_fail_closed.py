import pytest
import os
from unittest.mock import patch
from app.config import Settings

def test_prod_mode_with_ci_mode_fails():
    """
    Test C0.A: ENV_MODE=prod + CI_MODE=True should raise RuntimeError
    """
    with patch.dict(os.environ, {"ENV_MODE": "prod", "CI_MODE": "false"}):
        # Create new settings instance
        settings = Settings()
        settings.CI_MODE = True  # Force CI_MODE on
        settings.ENV_MODE = "prod"
        
        with pytest.raises(RuntimeError, match="CI_MODE cannot be enabled in PROD"):
            settings.runtime_validate()

def test_prod_mode_missing_api_keys_fails():
    """
    Test C0.B: ENV_MODE=prod + missing API_KEYS_JSON should raise RuntimeError
    """
    # Ensure API_KEYS_JSON is not set
    env_without_keys = os.environ.copy()
    env_without_keys.pop("API_KEYS_JSON", None)
    
    with patch.dict(os.environ, env_without_keys, clear=True):
        with patch.dict(os.environ, {
            "ENV_MODE": "prod",
            "CI_MODE": "false",
            "DB_URL": "postgresql://prod:prod@prodhost/proddb",
            "QDRANT_URL": "http://prodqdrant:6333",
            "REDIS_URL": "redis://prodredis:6379/0",
            "OPENAI_API_KEY": "sk-prod-key"
        }):
            settings = Settings()
            
            with pytest.raises(RuntimeError, match="API_KEYS_JSON must be set"):
                settings.runtime_validate()

def test_staging_default_tenant_enabled_fails():
    """
    Test C0.D: ENV_MODE=staging + ALLOW_DEFAULT_TENANT=True should raise RuntimeError
    """
    with patch.dict(os.environ, {
        "ENV_MODE": "staging",
        "CI_MODE": "false",
        "ALLOW_DEFAULT_TENANT": "true",
        "API_KEYS_JSON": '{"key1": "tenant1"}',
        "DB_URL": "postgresql://staging:staging@staginghost/stagingdb",
        "QDRANT_URL": "http://stagingqdrant:6333",
        "REDIS_URL": "redis://stagingredis:6379/0",
        "OPENAI_API_KEY": "sk-staging-key"
    }):
        settings = Settings()
        settings.ALLOW_DEFAULT_TENANT = True  # Force it on
        
        with pytest.raises(RuntimeError, match="ALLOW_DEFAULT_TENANT cannot be enabled"):
            settings.runtime_validate()

def test_dev_mode_relaxed():
    """
    Test C0.C: ENV_MODE=dev + missing configs should NOT fail
    """
    with patch.dict(os.environ, {"ENV_MODE": "dev", "CI_MODE": "false"}):
        settings = Settings()
        # Should not raise
        settings.runtime_validate()

def test_ci_mode_bypasses_validation():
    """
    Test C0.E: CI_MODE=True in dev/ci environments should bypass validation,
    but CI_MODE=True in staging/prod should still raise an error.
    """
    # CI_MODE in dev is fine
    with patch.dict(os.environ, {
        "ENV_MODE": "dev",
        "CI_MODE": "true"
    }):
        settings = Settings()
        # Should not raise
        settings.runtime_validate()
    
    # CI_MODE in ci environment is fine
    with patch.dict(os.environ, {
        "ENV_MODE": "ci",
        "CI_MODE": "true"
    }):
        settings = Settings()
        # Should not raise
        settings.runtime_validate()

def test_prod_mode_missing_secrets_fails():
    """
    Test C0.F: ENV_MODE=prod with dev/CI default secrets should fail
    """
    with patch.dict(os.environ, {
        "ENV_MODE": "prod",
        "CI_MODE": "false",
        "API_KEYS_JSON": '{"key1": "tenant1"}',
        # Using CI defaults - should fail
        "DB_URL": "postgresql://postgres:postgres@postgres:5432/postgres",
        "QDRANT_URL": "http://qdrant:6333",
        "REDIS_URL": "redis://redis:6379/0",
        "OPENAI_API_KEY": "dummy"
    }):
        settings = Settings()
        
        with pytest.raises(RuntimeError, match="Missing or invalid configuration"):
            settings.runtime_validate()

def test_prod_mode_with_valid_config_passes():
    """
    Test C0.G: ENV_MODE=prod with all valid configs should pass
    """
    with patch.dict(os.environ, {
        "ENV_MODE": "prod",
        "CI_MODE": "false",
        "API_KEYS_JSON": '{"key1": "tenant1"}',
        "DB_URL": "postgresql://produser:prodpass@prodhost:5432/proddb",
        "QDRANT_URL": "https://prodqdrant.example.com",
        "REDIS_URL": "redis://prodredis.example.com:6379/0",
        "OPENAI_API_KEY": "sk-prod-real-key-123",
        "EMBEDDING_BACKEND": "local"  # Don't require OpenAI key
    }):
        settings = Settings()
        # Should not raise
        settings.runtime_validate()
