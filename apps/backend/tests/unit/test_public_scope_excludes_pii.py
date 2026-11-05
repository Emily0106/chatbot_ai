import pytest
from app.core.rag.qdrant_filter_builder import QdrantStrictFilterBuilder, PermissionError
from app.core.policy.types import UserContext
from app.core.taxonomy import Scope

class TestPublicScopeExcludesPII:
    def test_public_scope_excludes_pii(self):
        """Public scope should add must_not condition for contains_pii"""
        builder = QdrantStrictFilterBuilder()
        user_ctx = UserContext(tenant_id="t1", department_id=None, geo_code=None)
        
        filters = {"scope": Scope.PUBLIC}
        result = builder.build(user_ctx, filters)
        
        # Verify must conditions: tenant_id + scope + contains_pii (Fail-Closed)
        assert len(result.must) >= 3 

        scope_conditions = [c for c in result.must if c.key == "scope"]
        assert len(scope_conditions) == 1
        scope_match = scope_conditions[0].match
        if hasattr(scope_match, "any"):
            assert "PUBLIC" in scope_match.any
            assert "public" in scope_match.any

        pii_conditions = [c for c in result.must if c.key == "contains_pii"]
        assert len(pii_conditions) == 1
        assert pii_conditions[0].match.value is False

        # Verify must_not is empty
        assert result.must_not == []
    
    def test_internal_scope_no_pii_filter(self):
        """Internal scope should NOT add must_not for PII"""
        builder = QdrantStrictFilterBuilder()
        user_ctx = UserContext(tenant_id="t1", department_id="dept1", geo_code=None)
        
        filters = {"scope": Scope.INTERNAL}
        result = builder.build(user_ctx, filters)
        
        # Verify must_not is empty (or None)
        assert result.must_not == [] or result.must_not is None
    
    def test_restricted_scope_no_pii_filter(self):
        """Restricted scope should NOT add must_not for PII"""
        builder = QdrantStrictFilterBuilder()
        user_ctx = UserContext(tenant_id="t1", department_id="dept1", geo_code=None, security_level=5)
        
        filters = {"scope": Scope.RESTRICTED}
        result = builder.build(user_ctx, filters)
        
        # Verify must_not is empty
        assert result.must_not == [] or result.must_not is None
    
    def test_no_scope_no_pii_filter(self):
        """No scope specified should not add PII filter"""
        builder = QdrantStrictFilterBuilder()
        user_ctx = UserContext(tenant_id="t1", department_id=None, geo_code=None)
        
        filters = {}
        result = builder.build(user_ctx, filters)
        
        # Only tenant_id in must, no must_not
        assert len(result.must) == 1
        assert result.must_not == [] or result.must_not is None

    def test_public_scope_lowercase_still_excludes_pii(self):
        builder = QdrantStrictFilterBuilder()
        user_ctx = UserContext(tenant_id="t1", department_id=None, geo_code=None)

        result = builder.build(user_ctx, {"scope": "public"})

        pii_conditions = [c for c in result.must if c.key == "contains_pii"]
        assert len(pii_conditions) == 1
        assert pii_conditions[0].match.value is False
