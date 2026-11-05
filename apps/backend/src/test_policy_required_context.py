import pytest
from app.agents.contract import AgentPolicy, TrustedContext
from app.core.policy.manager import PolicyManager
from app.core.policy.errors import MissingContextError
from unittest.mock import MagicMock

# Create dummy agents for testing purposes
class MockAgent:
    def __init__(self, agent_id, policy):
        self.agent_id = agent_id
        self.policy = policy

@pytest.fixture
def setup_mock_policies(monkeypatch):
    """
    Mock AGENT_POLICIES in manager to include our test agents.
    """
    test_policies = {
        "test_geo_agent": AgentPolicy(required_context_fields=["geo_code"]),
        "test_dept_agent": AgentPolicy(required_context_fields=["department_id"]),
        "test_strict_agent": AgentPolicy(required_context_fields=["geo_code", "department_id"]),
        "test_open_agent": AgentPolicy(required_context_fields=[])
    }
    
    # We need to patch the AGENT_POLICIES dictionary where PolicyManager imports it
    # note: PolicyManager imports AGENT_POLICIES from app.core.policy.config
    monkeypatch.setattr("app.core.policy.manager.AGENT_POLICIES", test_policies) 
    return test_policies

def test_policy_enforcement_missing_geo(setup_mock_policies):
    # Case: Missing geo_code
    ctx = TrustedContext(tenant_id="t1", user_id="u1", geo_code=None)
    
    with pytest.raises(MissingContextError) as exc:
        PolicyManager.enforce_context("test_geo_agent", ctx)
    
    assert "required_context_fields" in str(exc.value)
    assert "geo_code" in str(exc.value)

def test_policy_enforcement_valid_geo(setup_mock_policies):
    # Case: Valid geo_code
    ctx = TrustedContext(tenant_id="t1", user_id="u1", geo_code="VN-HN")
    # Should not raise
    PolicyManager.enforce_context("test_geo_agent", ctx)

def test_policy_enforcement_missing_dept(setup_mock_policies):
    # Case: Empty department_id (empty string considered missing)
    ctx = TrustedContext(tenant_id="t1", user_id="u1", department_id="")
    
    with pytest.raises(MissingContextError) as exc:
        PolicyManager.enforce_context("test_dept_agent", ctx)
    assert "department_id" in str(exc.value)

def test_policy_enforcement_multiple_missing(setup_mock_policies):
    # Case: Multiple missing
    ctx = TrustedContext(tenant_id="t1", user_id="u1")
    
    with pytest.raises(MissingContextError) as exc:
        PolicyManager.enforce_context("test_strict_agent", ctx)
    
    msg = str(exc.value)
    assert "geo_code" in msg
    assert "department_id" in msg

def test_policy_enforcement_open_agent(setup_mock_policies):
    # Case: No requirements
    ctx = TrustedContext(tenant_id="t1", user_id="u1")
    PolicyManager.enforce_context("test_open_agent", ctx)
