import pytest

pytestmark = pytest.mark.integration

from app.core.rag.router import HandoffRouter


def test_proactive_handoff_legal_intent():
    routed = HandoffRouter.route("Luật xử phạt vi phạm hành chính mới nhất", "meeting_agent")
    assert routed == "legal_agent"


def test_passive_handoff_policy_conflict():
    routed = HandoffRouter.route("Biên bản cuộc họp tuần trước", "legal_agent")
    assert routed == "meeting_agent"
