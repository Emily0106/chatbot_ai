import pytest
import os
import sys
import importlib.util
from unittest.mock import patch
from pathlib import Path

# Load preflight_env module from scripts directory
scripts_path = Path(__file__).parent.parent.parent.parent.parent / "scripts" / "preflight_env.py"
spec = importlib.util.spec_from_file_location("preflight_env", scripts_path)
preflight_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight_env)

validate_environment = preflight_env.validate_environment
check_api_keys_json = preflight_env.check_api_keys_json
mask_secret = preflight_env.mask_secret

def test_staging_missing_api_keys_fails():
    """Test C2.A: staging without API_KEYS_JSON should fail"""
    env = {
        "ENV_MODE": "staging",
        "CI_MODE": "false",
        "DB_URL": "postgresql://staging:pass@prodhost/db",
        "QDRANT_URL": "http://prodqdrant:6333",
        "REDIS_URL": "redis://prodredis:6379",
        "OPENAI_API_KEY": "sk-prod123",
        "ALLOW_DEFAULT_TENANT": "false"
    }
    
    with patch.dict(os.environ, env, clear=True):
        all_passed, messages = validate_environment("staging")
        assert not all_passed, "Should fail without API_KEYS_JSON"
        assert any("API_KEYS_JSON" in msg and "❌" in msg for msg in messages)

def test_staging_ci_mode_true_fails():
    """Test C2.B: staging with CI_MODE=true should fail"""
    env = {
        "ENV_MODE": "staging",
        "CI_MODE": "true",  # <- Invalid
        "API_KEYS_JSON": '{"key1":"tenant1"}',
        "DB_URL": "postgresql://staging:pass@prodhost/db",
        "QDRANT_URL": "http://prodqdrant:6333",
        "REDIS_URL": "redis://prodredis:6379",
        "OPENAI_API_KEY": "sk-prod123",
        "ALLOW_DEFAULT_TENANT": "false"
    }
    
    with patch.dict(os.environ, env, clear=True):
        all_passed, messages = validate_environment("staging")
        assert not all_passed, "Should fail with CI_MODE=true in staging"
        assert any("CI_MODE" in msg and "❌" in msg for msg in messages)

def test_staging_allow_default_tenant_fails():
    """Test C2.C: staging with ALLOW_DEFAULT_TENANT=true should fail"""
    env = {
        "ENV_MODE": "staging",
        "CI_MODE": "false",
        "API_KEYS_JSON": '{"key1":"tenant1"}',
        "DB_URL": "postgresql://staging:pass@prodhost/db",
        "QDRANT_URL": "http://prodqdrant:6333",
        "REDIS_URL": "redis://prodredis:6379",
        "OPENAI_API_KEY": "sk-prod123",
        "ALLOW_DEFAULT_TENANT": "true"  # <- Invalid
    }
    
    with patch.dict(os.environ, env, clear=True):
        all_passed, messages = validate_environment("staging")
        assert not all_passed, "Should fail with ALLOW_DEFAULT_TENANT=true"
        assert any("ALLOW_DEFAULT_TENANT" in msg and "❌" in msg for msg in messages)

def test_dev_mode_minimal_passes():
    """Test C2.D: dev mode with minimal config should pass"""
    env = {
        "ENV_MODE": "dev",
        "CI_MODE": "false"
    }
    
    with patch.dict(os.environ, env, clear=True):
        all_passed, messages = validate_environment("dev")
        assert all_passed, f"Dev mode should pass with minimal config. Messages: {messages}"

def test_prod_valid_config_passes():
    """Test C2.E: prod mode with all valid config should pass"""
    env = {
        "ENV_MODE": "prod",
        "CI_MODE": "false",
        "API_KEYS_JSON": '{"prod-key-abc123xyz":"tenant-prod-1"}',
        "DB_URL": "postgresql://produser:prodpass@proddbhost.example.com:5432/proddb",
        "QDRANT_URL": "https://qdrant-prod.example.com",
        "REDIS_URL": "redis://redis-prod.example.com:6379/0",
        "OPENAI_API_KEY": "sk-prod-real-key-xyz789abc",
        "ALLOW_DEFAULT_TENANT": "false",
        "EMBEDDING_BACKEND": "local"
    }
    
    with patch.dict(os.environ, env, clear=True):
        all_passed, messages = validate_environment("prod")
        assert all_passed, f"Prod mode should pass with valid config. Messages: {messages}"

def test_api_keys_json_invalid_format_fails():
    """Test C2.F: Invalid JSON format should fail"""
    # Test invalid JSON
    passed, msg = check_api_keys_json("{invalid json")
    assert not passed
    assert "Invalid JSON" in msg
    
    # Test non-object
    passed, msg = check_api_keys_json('["array", "not", "object"]')
    assert not passed
    assert "Must be a JSON object" in msg
    
    # Test empty object
    passed, msg = check_api_keys_json('{}')
    assert not passed
    assert "at least one key" in msg
    
    # Test key too short
    passed, msg = check_api_keys_json('{"short":"tenant1"}')
    assert not passed
    assert "too short" in msg

def test_api_keys_json_valid_format_passes():
    """Test valid API_KEYS_JSON formats"""
    # Single key (must be 16+ chars)
    passed, msg = check_api_keys_json('{"test-key-1234567":"tenant1"}')
    assert passed, f"Should pass with valid key. Message: {msg}"
    assert "1 key" in msg
    
    # Multiple keys
    passed, msg = check_api_keys_json('{"test-key-12345678":"tenant1","another-key-98765":"tenant2"}')
    assert passed, f"Should pass with multiple keys. Message: {msg}"
    assert "2 key" in msg

def test_secret_masking():
    """Test C2.G: Verify secrets are masked correctly"""
    # Short secret
    assert mask_secret("short") == "***"
    
    # Normal secret
    masked = mask_secret("sk-1234567890abcdefghijklmnopqrstuvwxyz")
    assert "sk-1" in masked
    assert "wxyz" in masked
    assert "..." in masked
    assert len(masked) < 20  # Much shorter than original
    
    # Ensure full secret not in masked output
    assert "1234567890abcdefghijklmnop" not in masked

def test_staging_dev_db_url_fails():
    """Test that dev/CI DB URLs are rejected in staging"""
    env = {
        "ENV_MODE": "staging",
        "CI_MODE": "false",
        "API_KEYS_JSON": '{"key1-1234567890":"tenant1"}',
        "DB_URL": "postgresql://postgres:postgres@localhost:5432/test",  # <- Dev default
        "QDRANT_URL": "http://prodqdrant:6333",
        "REDIS_URL": "redis://prodredis:6379",
        "OPENAI_API_KEY": "sk-prod123",
        "ALLOW_DEFAULT_TENANT": "false"
    }
    
    with patch.dict(os.environ, env, clear=True):
        all_passed, messages = validate_environment("staging")
        assert not all_passed, "Should reject dev DB URL in staging"
        assert any("DB_URL" in msg and "dev/CI default" in msg for msg in messages)

def test_migration_mode_allows_default_tenant():
    """Test that MIGRATION_MODE=true allows ALLOW_DEFAULT_TENANT in staging"""
    env = {
        "ENV_MODE": "staging",
        "CI_MODE": "false",
        "API_KEYS_JSON": '{"test-staging-key-12345":"tenant1"}',  # 21 chars
        "DB_URL": "postgresql://staginguser:stagingpass@prodhost.example.com:5432/stagingdb",
        "QDRANT_URL": "http://qdrant-staging.example.com:6333",
        "REDIS_URL": "redis://redis-staging.example.com:6379",
        "OPENAI_API_KEY": "sk-staging-key-123",
        "EMBEDDING_BACKEND": "local",  # Don't require OpenAI in staging with local backend
        "ALLOW_DEFAULT_TENANT": "true",
        "MIGRATION_MODE": "true"  # <- Allows ALLOW_DEFAULT_TENANT
    }
    
    with patch.dict(os.environ, env, clear=True):
        all_passed, messages = validate_environment("staging")
        assert all_passed, f"MIGRATION_MODE should allow ALLOW_DEFAULT_TENANT. Messages: {messages}"
