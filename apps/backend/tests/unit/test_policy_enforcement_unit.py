
# apps/backend/tests/test_policy_enforcement.py
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import asdict

from app.core.policy.manager import PolicyManager, AGENT_POLICIES
from app.core.policy.types import UserContext
from app.core.taxonomy import DocType, DataScope, normalize_doctype
from app.schemas.chat import RetrievalFilters

def test_unknown_agent_denied():
    ctx = UserContext(tenant_id="test")
    with pytest.raises(ValueError, match="Unknown agent_id"):
        PolicyManager.enforce_filters("unknown_agent_999", ctx, None)

def test_meeting_agent_cannot_query_law():
    """
    Meeting Agent allowed: MEETING_TRANSCRIPT.
    Request tries: LAW.
    Intersection should be empty -> Conflict detected.
    """
    ctx = UserContext(tenant_id="test", department_id="DEPT_A")
    
    # User tries to bypass
    req = RetrievalFilters(doc_type="law")
    
    res = PolicyManager.enforce_filters("meeting_assistant", ctx, req)
    
    assert res["policy_meta"]["conflict"] is True
    assert res["filters"]["doc_type"] == "__DENIED_BY_POLICY__"

def test_meeting_agent_default_scope_enforced():
    """
    If Meeting Agent doesn't specify doc_type, Policy enforce allowed types.
    """
    ctx = UserContext(tenant_id="test", department_id="DEPT_A")
    res = PolicyManager.enforce_filters("meeting_assistant", ctx, None)
    
    # Must contain allowed types
    allowed = AGENT_POLICIES["meeting_assistant"].allowed_doc_types
    # Depending on how manager maps it:
    # If len > 1: doc_types list
    # If len == 1: doc_type string
    
    if len(allowed) == 1:
        assert res["filters"]["doc_type"] == list(allowed)[0].value
    else:
        # Check intersection
        out_types = res["filters"].get("doc_types", [])
        assert set(out_types) == {t.value for t in allowed}

def test_legal_agent_allow_public_law():
    ctx = UserContext(tenant_id="test")
    req = RetrievalFilters(doc_type="law")
    
    res = PolicyManager.enforce_filters("legal", ctx, req)
    
    assert res["policy_meta"]["conflict"] is False
    assert res["filters"]["doc_type"] == "law"

def test_department_isolation_applied():
    """
    Meeting Agent requires department isolation. Using dept_id from context.
    """
    ctx = UserContext(tenant_id="test", department_id="dept_ABC")
    res = PolicyManager.enforce_filters("meeting_assistant", ctx, None)
    
    assert res["filters"]["department_id"] == "dept_ABC"

def test_department_isolation_fail_closed():
    """
    Meeting Agent requires isolation but context missing dept_id.
    """
    from app.core.policy.errors import MissingContextError
    ctx = UserContext(tenant_id="test", department_id=None)
    
    with pytest.raises(MissingContextError):
        PolicyManager.enforce_filters("meeting_assistant", ctx, None)

def test_citizen_qa_geo_isolation():
    ctx = UserContext(tenant_id="test", geo_code="HANOI")
    res = PolicyManager.enforce_filters("citizen", ctx, None)
    
    assert res["filters"]["geo_code"] == "HANOI"

def test_intersection_preserves_allowed_keys():
    """
    User filters like 'year' should be preserved (ANDed).
    """
    ctx = UserContext(tenant_id="test", department_id="DEPT_A")
    # RetrievalFilters doesn't have 'year' schema field yet, need to mock or enable extra?
    # Actually RetrievalFilters has extra="forbid".
    # But PolicyManager accepts pydantic model.
    # We must use allowed fields in schema. 'from_date' is allowed.
    req = RetrievalFilters(from_date="2024-01-01")
    
    res = PolicyManager.enforce_filters("meeting_assistant", ctx, req)
    
    assert res["filters"]["from_date"] == "2024-01-01"
