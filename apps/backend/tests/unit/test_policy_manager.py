import pytest
from app.core.policy.manager import PolicyManager
from app.core.policy.types import UserContext
from app.core.policy.config import AgentPolicy, AGENT_POLICIES
from app.core.taxonomy import DataScope, DocType

# Mock Policy with default scope
TEST_AGENT_ID = "test_agent"
TEST_POLICY = AgentPolicy(
    agent_id=TEST_AGENT_ID,
    allowed_doc_types={DocType.LAW},
    allowed_scopes={DataScope.PUBLIC, DataScope.INTERNAL},
    isolation_level="none",
    default_scope=DataScope.INTERNAL # Default
)

@pytest.fixture(autouse=True)
def mock_agent_policies(monkeypatch):
    """Inject test policy."""
    policies = AGENT_POLICIES.copy()
    policies[TEST_AGENT_ID] = TEST_POLICY
    monkeypatch.setattr("app.core.policy.manager.AGENT_POLICIES", policies)

def test_scope_injection_from_user_context():
    """Verify UserContext.scope takes precedence."""
    ctx = UserContext(
        tenant_id="t1", 
        scope="PUBLIC" # User explicitly asks for Public (or comes from public endpoint)
    )
    res = PolicyManager.enforce_filters(TEST_AGENT_ID, ctx)
    assert res["filters"]["scope"] == "PUBLIC"

def test_scope_injection_default_fallback():
    """Verify fallbacks to Agent Default if Context missing."""
    ctx = UserContext(tenant_id="t1", scope=None)
    res = PolicyManager.enforce_filters(TEST_AGENT_ID, ctx)
    assert res["filters"]["scope"] == "INTERNAL" # From Default

def test_scope_injection_invalid_scope():
    """Verify invalid scope falls back to default if available."""
    ctx = UserContext(tenant_id="t1", scope="RESTRICTED") # Not allowed for this agent (allows PUBLIC, INTERNAL)
    res = PolicyManager.enforce_filters(TEST_AGENT_ID, ctx)
    
    # Should fallback to Default (INTERNAL)
    assert res["filters"]["scope"] == "INTERNAL"
    # Optionally check logs if possible, but assert outcome is key.

def test_enforce_context_legacy_support():
    """Verify enforce_context works with dict-based policies (mocked) and doesn't crash."""
    # Mock a dict policy in policies
    dict_policy = {
        "agent_id": "legacy_agent",
        "required_context_fields": ["department_id"]
    }
    
    # We need to Monkeypatch get_policy to return this dict, 
    # because AGENT_POLICIES types is Dict[str, AgentPolicy]. 
    # But runtime might have dict if loaded from JSON/YAML in future?
    # Actually code handles: `if isinstance(policy, dict)`
    
    # Let's force put a dict in the map (ignoring type hint)
    with pytest.MonkeyPatch.context() as m:
        policies = AGENT_POLICIES.copy()
        policies["legacy_agent"] = dict_policy # type: ignore
        m.setattr("app.core.policy.manager.AGENT_POLICIES", policies)
        
        # Test: Logic should check required fields
        ctx_missing = UserContext(tenant_id="t1")
        # Should raise error about department_id
        from app.core.policy.errors import MissingContextError
        with pytest.raises(MissingContextError):
            PolicyManager.enforce_context("legacy_agent", ctx_missing)
            
        # Test: Valid context
        ctx_ok = UserContext(tenant_id="t1", department_id="D1")
        # Should not raise
        PolicyManager.enforce_context("legacy_agent", ctx_ok)

