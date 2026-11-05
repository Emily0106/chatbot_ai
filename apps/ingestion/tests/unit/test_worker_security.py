import pytest
from app.workers.worker_main import _parse_scope
from app.core.canonical_models import Scope

class TestScopeParsing:
    def test_valid_meta_scope(self):
        """Should parse valid scope from meta_json"""
        assert _parse_scope({"scope": "public"}, {}) == Scope.PUBLIC
        assert _parse_scope({"scope": "internal"}, {}) == Scope.INTERNAL
        assert _parse_scope({"scope": "restricted"}, {}) == Scope.RESTRICTED

    def test_invalid_meta_scope_raises(self):
        """Should RAISE error for invalid meta scope (Fail-Closed)"""
        with pytest.raises(RuntimeError) as exc:
            _parse_scope({"scope": "INVALID_SCOPE"}, {})
        assert "Job rejected" in str(exc.value)
        assert "INVALID_SCOPE" in str(exc.value)

    def test_valid_job_scope_legacy(self):
        """Should parse valid scope from job (legacy path)"""
        assert _parse_scope({}, {"scope": "public"}) == Scope.PUBLIC

    def test_legacy_aliases(self):
        """Should support specific legacy aliases"""
        assert _parse_scope({}, {"scope": "local_gov"}) == Scope.INTERNAL
        assert _parse_scope({}, {"scope": "global_law"}) == Scope.PUBLIC

    def test_invalid_job_scope_raises(self):
        """Should RAISE error for invalid legacy scope (Fail-Closed)"""
        with pytest.raises(RuntimeError) as exc:
            _parse_scope({}, {"scope": "HACKER_SCOPE"})
        assert "Job rejected" in str(exc.value)
        assert "HACKER_SCOPE" in str(exc.value)

    def test_missing_scope_raises(self):
        """Should RAISE error if scope is missing entirely"""
        with pytest.raises(RuntimeError) as exc:
            _parse_scope({}, {})
        assert "Missing scope" in str(exc.value)

    def test_meta_prioritized_over_job(self):
        """Meta scope should take precedence over job scope"""
        assert _parse_scope({"scope": "restricted"}, {"scope": "public"}) == Scope.RESTRICTED
