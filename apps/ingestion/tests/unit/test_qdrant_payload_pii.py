import pytest
from unittest.mock import MagicMock, Mock
from uuid import uuid4
from app.preproc.stores.qdrant_repo import QdrantRepo, QdrantRepoConfig
from app.core.canonical_models import (
    CanonicalChunk, ChunkKind, Citation, SourceLocator, Scope, DocCategory
)

class TestQdrantPayloadPII:
    def test_chunk_with_pii_stamped_correctly(self):
        """Should stamp contains_pii=True when chunk contains PII"""
        # Create chunk with PII
        chunk = CanonicalChunk(
            chunk_id=uuid4(),
            doc_id=uuid4(),
            tenant_id="t1",
            doc_type="law",
            scope=Scope.PUBLIC,
            security_level=0,
            commune_id="HN",
            doc_category=DocCategory.legal,
            chunk_kind=ChunkKind.paragraph,
            order_index=0,
            display_text="Contact: 0912345678, Email: user@example.com",  # Contains PII
            citation=Citation(
                locator=SourceLocator(
                    source_uri="test.pdf",
                    checksum="abc123",
                    page_start=1
                )
            )
        )
        
        # Mock repo to avoid Qdrant connection
        cfg = QdrantRepoConfig(url="http://localhost:6333", collection_name="test", embedding_model_id="test-model")
        repo = QdrantRepo.__new__(QdrantRepo)  # Create instance without calling __init__
        repo.cfg = cfg
        
        # Build payload directly
        chunk_dict = chunk.model_dump()
        payload = repo._build_payload_from_chunk(chunk_dict)
        
        # Verify PII flags
        assert payload["contains_pii"] is True
        assert "phone" in payload["pii_types"]
        assert "email" in payload["pii_types"]
    
    def test_chunk_without_pii_stamped_correctly(self):
        """Should stamp contains_pii=False when chunk has no PII"""
        chunk = CanonicalChunk(
            chunk_id=uuid4(),
            doc_id=uuid4(),
            tenant_id="t1",
            doc_type="law",
            scope=Scope.PUBLIC,
            security_level=0,
            commune_id="HN",
            doc_category=DocCategory.legal,
            chunk_kind=ChunkKind.paragraph,
            order_index=0,
            display_text="This is a clean legal document about land regulations.",  # No PII
            citation=Citation(
                locator=SourceLocator(
                    source_uri="test.pdf",
                    checksum="abc123",
                    page_start=1
                )
            )
        )
        
        cfg = QdrantRepoConfig(url="http://localhost:6333", collection_name="test", embedding_model_id="test-model")
        repo = QdrantRepo.__new__(QdrantRepo)
        repo.cfg = cfg
        
        chunk_dict = chunk.model_dump()
        payload = repo._build_payload_from_chunk(chunk_dict)
        
        assert payload["contains_pii"] is False
        assert payload["pii_types"] == []

    def test_build_points_backfills_contains_pii_for_canonical_payload(self):
        """CanonicalChunk.qdrant_payload may omit contains_pii; repo must backfill it."""
        chunk = CanonicalChunk(
            chunk_id=uuid4(),
            doc_id=uuid4(),
            tenant_id="t1",
            doc_type="law",
            scope=Scope.PUBLIC,
            security_level=0,
            commune_id="HN",
            doc_category=DocCategory.legal,
            chunk_kind=ChunkKind.paragraph,
            order_index=0,
            display_text="Public legal note without personal identifiers.",
            citation=Citation(
                locator=SourceLocator(
                    source_uri="test.pdf",
                    checksum="abc123",
                    page_start=1
                )
            )
        )

        cfg = QdrantRepoConfig(url="http://localhost:6333", collection_name="test", embedding_model_id="test-model")
        repo = QdrantRepo.__new__(QdrantRepo)
        repo.cfg = cfg

        points = repo._build_points([chunk], [[0.1, 0.2]])
        payload = points[0].payload

        assert "contains_pii" in payload
        assert payload["contains_pii"] is False
        assert payload["pii_types"] == []
