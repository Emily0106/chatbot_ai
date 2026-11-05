
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

@pytest.mark.asyncio
async def test_stream_rate_limit_lifecycle_isolated(monkeypatch):
    """
    Robust test for Streaming Rate Limit behavior:
    1. Mocks RateLimiter to track enter/exit calls.
    2. Mocks LLM stream to yield data.
    3. Verifies 'enter' is called before stream, and 'exit' is called after disconnect.
    """
    # 1. Mock Settings (Patch where it is imported/used)
    # We patch app.config.settings to ensure any module reading it sees checks enabled
    import app.config
    monkeypatch.setattr(app.config.settings, "ENABLE_STREAMING_CHAT", True)
    monkeypatch.setattr(app.config.settings, "ENABLE_RATE_LIMITING", True)

    # 2. Mock RAG Pipeline (Gate Pass)
    async def mock_retrieve(**kwargs):
        class MockRes:
             context = "Context found"
             citations = []
             meta = {}
             debug = {}
        return MockRes()
    
    # Patch where it is used in chat.py
    monkeypatch.setattr("app.api.routes.chat.rag_retrieve", mock_retrieve)

    # 3. Mock LLM Generator
    async def mock_gen_stream(*args, **kwargs):
        yield "Hello "
        yield "World"
        # Simulate small delay to allow us to close connection if we wanted, 
        # but here we just consume it all.
        
    monkeypatch.setattr("app.core.llm_client.generate_stream", mock_gen_stream)
    monkeypatch.setattr("app.api.routes.chat.achat", AsyncMock(return_value="Hello World"))

    # 4. Mock RateLimiter
    # We create a mock that returns "Allowed" for everything
    mock_rl = AsyncMock()
    mock_rl.allow_request.return_value = MagicMock(allowed=True)
    mock_rl.enter_stream.return_value = MagicMock(allowed=True)
    mock_rl.enter_inflight.return_value = MagicMock(allowed=True)
    
    # Patch the INSTANCE used in chat.py
    # We must make sure app.api.routes.chat is imported so we can patch the attribute
    import app.api.routes.chat
    monkeypatch.setattr(app.api.routes.chat, "rate_limiter", mock_rl)

    # 5. Execute Request
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        payload = {
            "agent_id": "citizen", 
            "message": "test stream", 
            "stream": True
        }
        
        async with ac.stream("POST", "/api/chat/stream", json=payload) as response:
            assert response.status_code == 200
            events = []
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    events.append(line.split(": ")[1].strip())
            
            # Verify we got events
            assert "meta" in events
            assert "delta" in events
            assert "final" in events
            
    # 6. Verify Rate Limit Interaction
    # Should check allow_request (RPS)
    assert mock_rl.allow_request.called
    # Should check enter_stream
    assert mock_rl.enter_stream.called
    # Should check enter_inflight
    assert mock_rl.enter_inflight.called
    
    # Should cleanup
    assert mock_rl.exit_stream.call_count == 1
    assert mock_rl.exit_inflight.call_count == 1

@pytest.mark.asyncio
async def test_stream_rate_limit_deny_isolated(monkeypatch):
    """
    Robust test for Deny behavior (Mocking RateLimiter to deny)
    """
    import app.config
    monkeypatch.setattr(app.config.settings, "ENABLE_STREAMING_CHAT", True)
    monkeypatch.setattr(app.config.settings, "ENABLE_RATE_LIMITING", True)

    mock_rl = AsyncMock()
    mock_rl.allow_request.return_value = MagicMock(allowed=True)
    # DENY STREAM
    mock_rl.enter_stream.return_value = MagicMock(allowed=False)
    
    import app.api.routes.chat
    monkeypatch.setattr(app.api.routes.chat, "rate_limiter", mock_rl)
    
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        payload = {"agent_id": "citizen", "message": "test"}
        response = await ac.post("/api/chat/stream", json=payload)
        
        assert response.status_code == 429
        # Should not enter inflight
        assert not mock_rl.enter_inflight.called
