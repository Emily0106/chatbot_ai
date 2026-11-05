import pytest

pytestmark = pytest.mark.integration

from app.core.policy.errors import MissingContextError
from app.core.policy.manager import PolicyManager
from app.core.policy.types import UserContext
from app.core.rag.router import HandoffRouter
from app.schemas.chat import RetrievalFilters


def test_department_isolation_e2e():
    """
    meeting_assistant policy is department-isolated.
    Any request filter trying another department is ignored in favor of trusted context.
    """
    ctx = UserContext(tenant_id="test", department_id="DEPT_A", security_level=2)
    req = RetrievalFilters()
    res = PolicyManager.enforce_filters("meeting_assistant", ctx, req)
    assert res["filters"]["department_id"] == "DEPT_A"
    assert res["filters"]["scope"] == "INTERNAL"


def test_missing_department_context_403():
    ctx = UserContext(tenant_id="test", department_id=None, security_level=2)
    with pytest.raises(MissingContextError):
        PolicyManager.enforce_filters("meeting_assistant", ctx, RetrievalFilters())


def test_tenant_isolation_filter():
    """
    Policy manager always uses trusted context fields; tenant is external to request filters.
    """
    ctx = UserContext(tenant_id="TENANT_X", department_id="DEPT_X", security_level=2)
    res = PolicyManager.enforce_filters("meeting_assistant", ctx, RetrievalFilters())
    assert res["policy_meta"]["agent_id"] == "meeting_assistant"
    assert res["filters"]["department_id"] == "DEPT_X"


def test_request_override_blocked():
    """
    Requesting `doc_type=law` in meeting lane must be policy-conflicted.
    """
    ctx = UserContext(tenant_id="test", department_id="DEPT_A", security_level=2)
    res = PolicyManager.enforce_filters(
        "meeting_assistant",
        ctx,
        RetrievalFilters(doc_type="law"),
    )
    assert res["policy_meta"]["conflict"] is True
    assert res["filters"]["doc_type"] == "__DENIED_BY_POLICY__"


def test_meeting_legal_intent_handoff():
    routed = HandoffRouter.route("Luật đất đai quy định thế nào?", "meeting_agent")
    assert routed == "legal_agent"
