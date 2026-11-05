import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_chat_stream_contract(monkeypatch):
    import app.main
    import app.config
    
    monkeypatch.setattr(app.config.settings, "ENABLE_STREAMING_CHAT", True)
    
    async def mock_retrieve(**kwargs):
        class MockRes:
            context = "Context"
            citations = [{"chunk_id": "c1", "title": "T1", "source_url": "u1", "snippet": "s1"}]
            meta = {"lane": "strict", "trace_id": "test_trace"}
            debug = {}
        return MockRes()
        
    monkeypatch.setattr("app.api.routes.chat.rag_retrieve", mock_retrieve)
    
    async def mock_gen_stream(*args, **kwargs):
        yield "Xin "
        yield "chào"
        
    monkeypatch.setattr("app.api.routes.chat.achat", AsyncMock(return_value="Xin chào"))
    monkeypatch.setattr("app.core.llm_client.generate_stream", mock_gen_stream)
    
    async with AsyncClient(transport=ASGITransport(app=app.main.app), base_url="http://test") as ac:
        payload = {
            "agent_id": "general",
            "message": "hello",
            "stream": True 
        }
        
        async with ac.stream("POST", "/api/chat/stream", json=payload) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            events = []
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    events.append(line.split(": ")[1].strip())
            
            assert "meta" in events
            assert "delta" in events
            assert "final" in events
