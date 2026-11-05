import pytest

pytestmark = pytest.mark.integration

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.contract import TrustedContext
from app.agents.meeting_agent import MeetingAgent
from app.core.rag.router import HandoffRouter


@pytest.mark.asyncio
async def test_meeting_intent_legal_handoff():
    """Legal keywords should route from meeting lane to legal lane in router."""
    routed = HandoffRouter.route("Luật xử phạt vi phạm hành chính về đất đai", "meeting_agent")
    assert routed == "legal_agent"


@pytest.mark.asyncio
async def test_meeting_intent_normal():
    """Meeting agent keeps fail-closed behavior when retrieval has no context."""
    agent = MeetingAgent()
    ctx = TrustedContext(
        tenant_id="test",
        user_id="u_test",
        department_id="dept_a",
        security_level=2,
        request_payload={},
    )

    async def _fake_db_gen():
        yield AsyncMock()

    fake_rag = SimpleNamespace(context="", citations=[], meta={})
    with patch("app.core.db_sql.get_async_db", _fake_db_gen), patch(
        "app.core.rag.pipeline.rag_retrieve", new=AsyncMock(return_value=fake_rag)
    ):
        resp = await agent.process(ctx, "Kết luận cuộc họp tuần trước")

    refusal = getattr(resp.meta, "refusal", {}) or {}
    assert "NO_EVIDENCE" in str(refusal.get("code", ""))
    assert resp.citations == []
