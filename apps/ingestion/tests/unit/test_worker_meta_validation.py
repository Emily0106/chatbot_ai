import pytest
from app.preproc.pipeline.interfaces import IngestMeta
from app.core.canonical_models import Scope
from app.workers.worker_main import _validate_meta_by_scope
from datetime import date

class TestMetadataValidationByScope:
    """Test fail-closed metadata validation based on scope"""
    
    def test_public_missing_dept_geo_ok(self):
        """PUBLIC scope allows missing department_id and geo_code"""
        meta = IngestMeta(
            tenant_id="t1",
            doc_type="law",
            scope=Scope.PUBLIC,
            security_level=1,
            source_uri="test.pdf",
            checksum="abc123",
            mime_type="application/pdf",
            title="Test",
            pipeline_version="v1",
            department_id=None,
            geo_code=None
        )
        # Should not raise
        _validate_meta_by_scope(meta)
    
    def test_internal_with_department_ok(self):
        """INTERNAL scope with valid department_id is OK"""
        meta = IngestMeta(
            tenant_id="t1",
            doc_type="law",
            scope=Scope.INTERNAL,
            security_level=2,
            source_uri="test.pdf",
            checksum="abc123",
            mime_type="application/pdf",
            title="Test",
            pipeline_version="v1",
            department_id="dept1",
            geo_code=None
        )
        # Should not raise
        _validate_meta_by_scope(meta)
    
    def test_internal_missing_department_fails(self):
        """INTERNAL scope without department_id raises RuntimeError"""
        meta = IngestMeta(
            tenant_id="t1",
            doc_type="law",
            scope=Scope.INTERNAL,
            security_level=2,
            source_uri="test.pdf",
            checksum="abc123",
            mime_type="application/pdf",
            title="Test",
            pipeline_version="v1",
            department_id=None,
            geo_code="HN"
        )
        with pytest.raises(RuntimeError, match="INTERNAL scope requires non-empty department_id"):
            _validate_meta_by_scope(meta)
    
    def test_internal_empty_department_fails(self):
        """INTERNAL scope with empty/whitespace department_id raises RuntimeError"""
        meta = IngestMeta(
            tenant_id="t1",
            doc_type="law",
            scope=Scope.INTERNAL,
            security_level=2,
            source_uri="test.pdf",
            checksum="abc123",
            mime_type="application/pdf",
            title="Test",
            pipeline_version="v1",
            department_id="  ",  # Whitespace only
            geo_code=None
        )
        with pytest.raises(RuntimeError, match="INTERNAL scope requires non-empty department_id"):
            _validate_meta_by_scope(meta)
    
    def test_restricted_low_security_level_fails(self):
        """RESTRICTED scope with security_level < 3 raises RuntimeError"""
        meta = IngestMeta(
            tenant_id="t1",
            doc_type="law",
            scope=Scope.RESTRICTED,
            security_level=2,  # Too low
            source_uri="test.pdf",
            checksum="abc123",
            mime_type="application/pdf",
            title="Test",
            pipeline_version="v1",
            department_id="dept1",
            geo_code="HN"
        )
        with pytest.raises(RuntimeError, match="RESTRICTED scope requires security_level >= 3"):
            _validate_meta_by_scope(meta)
    
    def test_restricted_missing_scoping_fails(self):
        """RESTRICTED scope without department_id or geo_code raises RuntimeError"""
        meta = IngestMeta(
            tenant_id="t1",
            doc_type="law",
            scope=Scope.RESTRICTED,
            security_level=5,
            source_uri="test.pdf",
            checksum="abc123",
            mime_type="application/pdf",
            title="Test",
            pipeline_version="v1",
            department_id=None,
            geo_code=None  # Both missing
        )
        with pytest.raises(RuntimeError, match="RESTRICTED scope requires department_id OR geo_code"):
            _validate_meta_by_scope(meta)
    
    def test_restricted_with_department_ok(self):
        """RESTRICTED scope with security_level >= 3 and department_id is OK"""
        meta = IngestMeta(
            tenant_id="t1",
            doc_type="law",
            scope=Scope.RESTRICTED,
            security_level=5,
            source_uri="test.pdf",
            checksum="abc123",
            mime_type="application/pdf",
            title="Test",
            pipeline_version="v1",
            department_id="dept1",
            geo_code=None
        )
        # Should not raise
        _validate_meta_by_scope(meta)
    
    def test_restricted_with_geo_code_ok(self):
        """RESTRICTED scope with security_level >= 3 and geo_code is OK"""
        meta = IngestMeta(
            tenant_id="t1",
            doc_type="law",
            scope=Scope.RESTRICTED,
            security_level=3,  # Minimum acceptable
            source_uri="test.pdf",
            checksum="abc123",
            mime_type="application/pdf",
            title="Test",
            pipeline_version="v1",
            department_id=None,
            geo_code="HN"
        )
        # Should not raise
        _validate_meta_by_scope(meta)
