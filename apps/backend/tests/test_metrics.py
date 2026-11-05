
# apps/backend/tests/test_metrics.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.api.routes.chat import chat_endpoint, chat_stream_gen
from app.schemas.chat import ChatRequest, ChatResponse

@pytest.fixture(autouse=True)
def reset_registry():
    pass

@pytest.mark.asyncio
async def test_metrics_chat_success():
    # Setup
    payload = ChatRequest(message="hello", agent_id="citizen")
    request = MagicMock()
    request.headers.get.return_value = "trace_ok"
    db = AsyncMock()
    
    # Create manual mock instances
    mock_rl_instance = MagicMock()
    mock_rl_instance.allow_request = AsyncMock(return_value=MagicMock(allowed=True, retry_after_s=None))
    mock_rl_instance.enter_inflight = AsyncMock(return_value=MagicMock(allowed=True))
    mock_rl_instance.exit_inflight = AsyncMock()
    
    mock_session_store = MagicMock()
    mock_session_store.get_cases = AsyncMock(return_value=[])
    mock_session_store.add_case = AsyncMock()
    
    mock_rag_func = AsyncMock(return_value=MagicMock(context="context", citations=[], meta={"timing": {}}))
    mock_achat_func = AsyncMock(return_value="Answer")
    
    mock_req_metric = MagicMock()
    
    # Patch
    with patch("app.core.rate_limit.rate_limiter", new=mock_rl_instance), \
         patch("app.core.memory.session_store.get_session_store", return_value=mock_session_store), \
         patch("app.api.routes.chat._call_rag_retrieve_tolerant", new=mock_rag_func), \
         patch("app.api.routes.chat.achat", new=mock_achat_func), \
         patch("app.api.routes.chat.get_agent", return_value=MagicMock()), \
         patch("app.api.routes.chat.CHAT_REQUESTS_TOTAL", new=mock_req_metric):
        
        # Act
        await chat_endpoint(payload, request, db)
        
        # Assert
        # Check if inc was called.
        # We don't enforce strict labels to avoid brittleness, but check basics.
        assert mock_req_metric.labels.called
        args, kwargs = mock_req_metric.labels.call_args
        # kwargs should contain status="ok"
        assert kwargs.get("status") == "ok"
        assert kwargs.get("agent_id") == "citizen"
        
        mock_req_metric.labels.return_value.inc.assert_called()

@pytest.mark.asyncio
async def test_metrics_stream_gauge():
    # Setup
    payload = ChatRequest(message="stream me", agent_id="meeting_assistant", stream=True)
    request = MagicMock()
    request.headers.get.return_value = "trace_stream"
    request.is_disconnected = AsyncMock(return_value=False)
    db = AsyncMock()
    
    mock_rl_instance = MagicMock()
    mock_rl_instance.allow_request = AsyncMock(return_value=MagicMock(allowed=True, retry_after_s=None))
    mock_rl_instance.enter_stream = AsyncMock(return_value=MagicMock(allowed=True))
    mock_rl_instance.enter_inflight = AsyncMock(return_value=MagicMock(allowed=True))
    mock_rl_instance.exit_stream = AsyncMock()
    mock_rl_instance.exit_inflight = AsyncMock()
    
    mock_stream_gauge = MagicMock()
    
    mock_agent = MagicMock()
    async def fake_stream(_):
        yield ChatResponse(answer="chunk")
    mock_agent.process_stream = fake_stream
    
    with patch("app.core.rate_limit.rate_limiter", new=mock_rl_instance), \
         patch("app.api.routes.chat.get_agent", return_value=mock_agent), \
         patch("app.api.routes.chat.STREAMS_ACTIVE", new=mock_stream_gauge):
        
        # Act
        gen = chat_stream_gen(payload, request, db)
        async for _ in gen:
            pass
            
        # Assert
        assert mock_stream_gauge.inc.called
        assert mock_stream_gauge.dec.called

def test_metrics_exposed():
    from app.api.routes.metrics import metrics
    resp = metrics()
    content = resp.body.decode()
    assert "govai_chat_requests_total" in content
