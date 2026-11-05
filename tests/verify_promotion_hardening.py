# tests/verify_promotion_hardening.py
import asyncio
import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

# Mock TempDocStore to avoid Redis dependency in this unit test
async def mock_get(*args, **kwargs):
    return {
        "text": "Mock content",
        "meta": {"filename": "test.txt"}
    }

class TestPromotionHardening(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        settings.ENABLE_TEMP_DOCS = True
        settings.INGESTION_BASE_URL = "http://mock-ingestion"

    @patch("app.core.temp_docs.store.TempDocStore.get", side_effect=mock_get)
    @patch("httpx.AsyncClient.get")
    @patch("httpx.AsyncClient.post")
    def test_promotion_health_check_fail(self, mock_post, mock_get, mock_store):
        """Test that promotion fails fast if health check fails."""
        # Mock health check failure
        mock_get.return_value = MagicMock(status_code=503)
        
        resp = self.client.post("/api/temp/promote", json={
            "tenant_id": "test",
            "temp_doc_id": "tmp_123",
            "doc_type": "meeting"
        })
        
        self.assertEqual(resp.status_code, 502)
        self.assertIn("Ingestion service reported unhealthy", resp.json()["detail"])

    @patch("app.core.temp_docs.store.TempDocStore.get", side_effect=mock_get)
    @patch("httpx.AsyncClient.get")
    @patch("httpx.AsyncClient.post")
    def test_promotion_retry_success(self, mock_post, mock_get, mock_store):
        """Test that promotion retries and succeeds."""
        # Mock health check success
        mock_get.return_value = MagicMock(status_code=200)
        
        # Mock post: Fail once, then succeed
        import httpx
        mock_post.side_effect = [
            httpx.ConnectError("Connection failed"),
            MagicMock(status_code=200)
        ]
        
        resp = self.client.post("/api/temp/promote", json={
            "tenant_id": "test",
            "temp_doc_id": "tmp_123",
            "doc_type": "meeting"
        })
        
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "promoted")
        self.assertEqual(mock_post.call_count, 2) # Should be called twice

    @patch("app.core.temp_docs.store.TempDocStore.get", side_effect=mock_get)
    @patch("httpx.AsyncClient.get")
    @patch("httpx.AsyncClient.post")
    def test_promotion_retry_exhausted(self, mock_post, mock_get, mock_store):
        """Test that promotion fails after retries exhausted."""
        # Mock health check success
        mock_get.return_value = MagicMock(status_code=200)
        
        # Mock post: Fail always
        import httpx
        mock_post.side_effect = httpx.ConnectError("Connection failed")
        
        resp = self.client.post("/api/temp/promote", json={
            "tenant_id": "test",
            "temp_doc_id": "tmp_123",
            "doc_type": "meeting"
        })
        
        self.assertEqual(resp.status_code, 502)
        self.assertIn("Trace ID", resp.json()["detail"])
        self.assertIn("Ingestion service unavailable after retries", resp.json()["detail"])

if __name__ == "__main__":
    unittest.main()
