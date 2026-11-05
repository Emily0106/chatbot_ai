
from httpx import AsyncClient, ASGITransport
import pytest

@pytest.mark.asyncio
async def test_metrics_endpoint():
    """Verify /metrics endpoint returns 200 and prometheus formatted text"""
    from app.main import app
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        
        # Check standard prometheus output (comments)
        text = resp.text
        assert "# HELP chat_requests_total" in text
        assert "# TYPE chat_requests_total counter" in text
