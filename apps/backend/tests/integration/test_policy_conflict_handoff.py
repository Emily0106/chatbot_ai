import pytest

pytestmark = pytest.mark.integration

from app.core.rag.router import HandoffRouter


def test_policy_conflict_triggers_handoff():
    """
    Current orchestration uses router-level handoff.
    Ambiguous legal query in non-legal lane should route to legal agent.
    """
    routed = HandoffRouter.route("Hỏi về luật nhưng intent detection failed nên vào search", "meeting_agent")
    assert routed == "legal_agent"
