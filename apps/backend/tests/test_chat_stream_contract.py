
# apps/backend/tests/test_chat_stream_contract.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.api.routes.chat import chat_stream_gen
from app.schemas.chat import ChatRequest, ChatResponse, Citation, Handoff

@pytest.mark.asyncio
async def test_stream_meeting_delegate_flow():
    # Setup
    payload = ChatRequest(
        agent_id="meeting_assistant",
        message="Họp về gì?",
        stream=True,
        tenant_id="test_tenant"
    )
    request = MagicMock()
    request.headers.get.return_value = "trace_123"
    request.is_disconnected = AsyncMock(return_value=False)
    db = AsyncMock()
    
    # Mock RateLimiter
    with patch("app.core.rate_limit.rate_limiter") as mock_rl:
        mock_rl.enter_inflight = AsyncMock(return_value=MagicMock(allowed=True))
        mock_rl.exit_inflight = AsyncMock()
        mock_rl.enter_stream = AsyncMock(return_value=MagicMock(allowed=True))
        mock_rl.exit_stream = AsyncMock()
        
        # Mock Metric
        with patch("app.core.metrics.INFLIGHT_ACTIVE"), \
             patch("app.core.metrics.STREAMS_ACTIVE"):
            
            # Mock Agent Registry & Agent
            mock_agent = MagicMock()
            mock_agent.process_stream = MagicMock()
            
            async def fake_process_stream(req):
                # 1. Handoff check (none)
                # 2. Yield chunk 1 (Citation + empty answer)
                yield ChatResponse(
                    answer="",
                    citations=[Citation(chunk_id="c1", snippet="snip")]
                )
                # 3. Yield chunk 2 (Token 1)
                yield ChatResponse(answer="Cuộc ")
                # 4. Yield chunk 3 (Token 2)
                yield ChatResponse(answer="họp.")
                
            mock_agent.process_stream.side_effect = fake_process_stream
            
            with patch("app.api.routes.chat.get_agent", return_value=mock_agent):
                
                # Execute
                gen = chat_stream_gen(payload, request, db)
                items = []
                async for item in gen:
                    items.append(item)
                    
                # Verify SSE Format
                print(items)
                
                # 1. Meta
                assert items[0].startswith("event: meta")
                assert "test_tenant" not in items[0] # check trace
                
                # 2. Citation
                # process_stream yields citation in first chunk
                # logic: if citations -> emit event: citation
                # logic: if answer -> emit event: token
                
                # First chunk has citations AND answer="". 
                # answer="" is falsy, so token event NOT emitted.
                # Just citation.
                assert "event: citation" in items[1]
                assert "snip" in items[1]
                
                # 3. Token "Cuộc "
                assert "event: token" in items[2]
                assert "Cuộc " in items[2]
                
                # 4. Token "họp."
                assert "event: token" in items[3]
                
                # 5. Done
                assert "event: done" in items[-1]

@pytest.mark.asyncio
async def test_stream_generic_fallback():
    # Setup
    payload = ChatRequest(
        agent_id="generic_agent", # NOT delegated
        message="Hello",
        stream=True
    )
    request = MagicMock()
    request.headers.get.return_value = "trace_456"
    request.is_disconnected = AsyncMock(return_value=False)
    db = AsyncMock()
    
    with patch("app.core.rate_limit.rate_limiter") as mock_rl, \
         patch("app.core.metrics.INFLIGHT_ACTIVE"), \
         patch("app.core.metrics.STREAMS_ACTIVE"), \
         patch("app.api.routes.chat.get_agent"), \
         patch("app.api.routes.chat._chat_endpoint_impl") as mock_impl:
             
        mock_rl.enter_inflight = AsyncMock(return_value=MagicMock(allowed=True))
        mock_rl.exit_inflight = AsyncMock()
        mock_rl.enter_stream = AsyncMock(return_value=MagicMock(allowed=True))
        mock_rl.exit_stream = AsyncMock()
        
        # Mock blocking response
        mock_impl.return_value = ChatResponse(answer="Full Response", citations=[])
        
        gen = chat_stream_gen(payload, request, db)
        items = [i async for i in gen]
        
        # Expect: meta -> token (full) -> done
        assert "event: meta" in items[0]
        assert "event: token" in items[1]
        assert "Full Response" in items[1]
        assert "event: citation" not in items[2] # No citations
        assert "event: done" in items[-1]
