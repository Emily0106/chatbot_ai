from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List

from app.core.canonical_models import DocCategory, ExtractedBlock, ExtractedBlockKind, ExtractedDoc
from app.preproc.parsers.narrative import NarrativeParser
from app.preproc.pipeline.interfaces import ClassificationResult, IngestMeta
from app.preproc.pipeline.orchestrator import IngestionOrchestrator


@dataclass
class _Extractor:
    text: str

    def extract(self, _file_path: str, meta: Any = None) -> ExtractedDoc:
        return ExtractedDoc(
            mime_type="text/plain",
            blocks=[
                ExtractedBlock(
                    kind=ExtractedBlockKind.text,
                    page_index=0,
                    order_index=0,
                    text=self.text,
                    anchor="plain:0",
                )
            ],
            page_count=1,
            has_text_layer=True,
            has_tables=False,
        )


class _Registry:
    def __init__(self, extractor: _Extractor) -> None:
        self._extractor = extractor
        self._parser = NarrativeParser()

    def get_extractor(self, _file_path: str, _meta: IngestMeta):
        return self._extractor

    def get_doc_parser(self, _doc_category: DocCategory):
        return self._parser

    def get_block_parser(self, _doc_category: DocCategory):
        return None


class _Classifier:
    def classify(self, _extracted: ExtractedDoc, _meta: IngestMeta) -> ClassificationResult:
        return ClassificationResult(doc_category=DocCategory.notice, confidence=0.99)


class _Embedder:
    def embed(self, texts: List[str]):
        return [[0.1, 0.2] for _ in texts]


class _PgRepo:
    def __init__(self):
        self.docs = []
        self.chunks = []
        self.rows = []

    def upsert_document(self, doc):
        self.docs.append(doc)

    def upsert_chunks(self, chunks):
        self.chunks.extend(chunks)

    def upsert_rows(self, rows):
        self.rows.extend(rows)


class _QdrantRepo:
    def __init__(self):
        self.upserts = []

    def upsert_chunks(self, chunks, vectors):
        self.upserts.append((chunks, vectors))


def test_text_plain_ingestion_produces_chunks(tmp_path: Path) -> None:
    doc_path = tmp_path / "plain.txt"
    doc_path.write_text(
        "Heading\n\nThis plain text document should produce at least one canonical chunk for retrieval.",
        encoding="utf-8",
    )

    registry = _Registry(
        _Extractor(
            "Heading\n\nThis plain text document should produce at least one canonical chunk for retrieval."
        )
    )
    pg = _PgRepo()
    qd = _QdrantRepo()

    orch = IngestionOrchestrator(
        registry=registry,
        classifier=_Classifier(),
        embedder=_Embedder(),
        postgres_repo=pg,
        qdrant_repo=qd,
    )

    meta = IngestMeta(
        tenant_id="tenant-a",
        doc_type="other",
        scope="public",
        security_level=1,
        source_uri=str(doc_path),
        checksum="deadbeef",
        mime_type="text/plain",
        title="plain.txt",
        pipeline_version="v1",
    )

    result = orch.process(str(doc_path), meta)

    assert result["chunks"] > 0
    assert result["embedded_chunks"] > 0
    assert len(pg.chunks) > 0
    assert len(qd.upserts) == 1
