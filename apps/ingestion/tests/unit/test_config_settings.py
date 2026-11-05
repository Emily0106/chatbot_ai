import importlib
import os

import app.core.config as config_module


def test_settings_exposes_qdrant_url():
    mod = importlib.reload(config_module)
    settings = mod.Settings()
    assert hasattr(settings, "QDRANT_URL")


def test_settings_reads_qdrant_url_from_env(monkeypatch):
    original = os.getenv("QDRANT_URL")
    monkeypatch.setenv("QDRANT_URL", "http://example")
    mod = importlib.reload(config_module)
    assert mod.Settings().QDRANT_URL == "http://example"

    if original is None:
        monkeypatch.delenv("QDRANT_URL", raising=False)
    else:
        monkeypatch.setenv("QDRANT_URL", original)
    importlib.reload(config_module)


def test_settings_reads_ingest_internal_token_from_env(monkeypatch):
    original = os.getenv("INGEST_INTERNAL_TOKEN")
    monkeypatch.setenv("INGEST_INTERNAL_TOKEN", "token-for-tests")

    mod = importlib.reload(config_module)
    assert mod.Settings().INGEST_INTERNAL_TOKEN == "token-for-tests"

    if original is None:
        monkeypatch.delenv("INGEST_INTERNAL_TOKEN", raising=False)
    else:
        monkeypatch.setenv("INGEST_INTERNAL_TOKEN", original)
    importlib.reload(config_module)
