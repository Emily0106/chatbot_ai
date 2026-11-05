import pytest
from uuid import uuid4
from uuid import uuid4
from app.core.canonical_models import CanonicalChunk, Scope, DocCategory, ChunkKind, Citation, SourceLocator
from app.core.taxonomy import SecurityLevel

def test_canonical_chunk_payload_contract():
    """Verify CanonicalChunk.qdrant_payload() returns strict keys."""
    
    doc_id = uuid4()
    chunk_id = uuid4()
    
    chunk = CanonicalChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        
        tenant_id="tenant_123",
        doc_type="law",
        scope=Scope.INTERNAL,
        security_level=3,
        department_id="dept_legal",
        geo_code="VN.HCM",
        domain="civil_law",
        
        commune_id="VN.HCM",
        doc_category=DocCategory.legal,
        chunk_kind=ChunkKind.law_clause,
        order_index=1,
        
        display_text="Test clause",
        citation=Citation(
            locator=SourceLocator(
                source_uri="s3://test.pdf",
                checksum="abc",
                mime_type="application/pdf",
                page_start=1
            )
        )
    )
    
    payload = chunk.qdrant_payload()
    
    # Assert Strict Keys
    assert payload["tenant_id"] == "tenant_123"
    assert payload["doc_type"] == "law"
    assert payload["scope"] == "internal"
    assert payload["security_level"] == 3
    assert payload["department_id"] == "dept_legal"
    assert payload["geo_code"] == "VN.HCM"
    assert payload["domain"] == "civil_law"
    
    # Assert legacy keys Absent (Strict Contract)
    assert "doc_category" not in payload
    assert "commune_id" not in payload


def test_canonical_chunk_public_payload():
    """Verify Public Payload (optional fields None)."""
    
    chunk = CanonicalChunk(
        chunk_id=uuid4(),
        doc_id=uuid4(),
        
        tenant_id="tenant_public",
        doc_type="report",
        scope=Scope.PUBLIC,
        security_level=1,
        # department_id/geo_code/domain implicitly None
        
        doc_category=DocCategory.report,
        chunk_kind=ChunkKind.paragraph,
        
        display_text="Public text",
        citation=Citation(
            locator=SourceLocator(source_uri="x", checksum="y", mime_type="z")
        )
    )
    
    payload = chunk.qdrant_payload()
    
    assert payload["tenant_id"] == "tenant_public"
    assert payload["scope"] == "public"
    assert payload.get("department_id") is None
    assert payload.get("geo_code") is None
