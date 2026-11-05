import pytest
import sys
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Set dummy env vars to satisfy Settings validation
os.environ["POSTGRES_USER"] = "test"
os.environ["POSTGRES_PASSWORD"] = "test"
os.environ["POSTGRES_DB"] = "test"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["QDRANT_URL"] = "http://localhost:6333"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["DB_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test"
os.environ["OPENAI_API_KEY"] = "sk-test"

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../apps/backend/src")))

from app.agents.meeting.meeting_agent import MeetingAgent
from app.schemas.chat import ChatRequest, ChatResponse, Citation
from app.core.rag.pipeline import RagPipelineResult

@pytest.mark.asyncio
async def test_meeting_agent_process_success():
    # Mock CoreService
    mock_core_service = AsyncMock()
    mock_rag_result = RagPipelineResult(
        context="Meeting content about project X.",
        citations=[Citation(chunk_id="1", file_url="doc1")],
        meta={}
    )
    mock_core_response = MagicMock()
    mock_core_response.ok = True
    mock_core_response.data = mock_rag_result
    mock_core_service.search.return_value = mock_core_response

    # Mock achat
    mock_achat = AsyncMock(return_value="Answer based on meeting.")

    # Mock get_async_db
    mock_db = AsyncMock()
    async def mock_get_db():
        yield mock_db

    with patch("app.agents.meeting.meeting_agent.get_core_service", return_value=mock_core_service), \
         patch("app.agents.meeting.meeting_agent.achat", mock_achat), \
         patch("app.agents.meeting.meeting_agent.get_async_db", mock_get_db):
        
        agent = MeetingAgent()
        # Ensure core is the mock (though patch should handle it if called in __init__? 
        # No, __init__ calls get_core_service(). Patch needs to be active during __init__ or we overwrite.)
        agent.core = mock_core_service

        req = ChatRequest(agent_id="meeting_assistant", message="What about project X?", tenant_id="t1", trace_id="tr1")
        resp = await agent.process(req)

        # Assertions
        assert resp.answer == "Answer based on meeting."
        assert len(resp.citations) == 1
        assert resp.citations[0].chunk_id == "1"
        
        # Verify CoreService called with correct params
        mock_core_service.search.assert_called_once()
        call_args = mock_core_service.search.call_args
        assert call_args.kwargs["tenant_id"] == "t1"
        assert call_args.kwargs["filters"].doc_type == "meeting_transcript"

@pytest.mark.asyncio
async def test_meeting_agent_no_evidence():
    mock_core_service = AsyncMock()
    # Return empty context
    mock_rag_result = RagPipelineResult(context="", citations=[], meta={})
    mock_core_response = MagicMock()
    mock_core_response.ok = True
    mock_core_response.data = mock_rag_result
    mock_core_service.search.return_value = mock_core_response

    async def mock_get_db():
        yield AsyncMock()

    with patch("app.agents.meeting.meeting_agent.get_core_service", return_value=mock_core_service), \
         patch("app.agents.meeting.meeting_agent.get_async_db", mock_get_db):
        
        agent = MeetingAgent()
        agent.core = mock_core_service

        req = ChatRequest(agent_id="meeting_assistant", message="Unknown?", tenant_id="t1")
        resp = await agent.process(req)

        assert "không tìm thấy thông tin" in resp.answer

if __name__ == "__main__":
    # Allow running directly
    import asyncio
    async def run():
        print("Running test_meeting_agent_process_success...")
        await test_meeting_agent_process_success()
        print("PASS")
        print("Running test_meeting_agent_no_evidence...")
        await test_meeting_agent_no_evidence()
        print("PASS")
    asyncio.run(run())
