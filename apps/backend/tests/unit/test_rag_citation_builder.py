from __future__ import annotations

from app.core.rag.pipeline import _build_citations_safe


def test_build_citations_sets_document_id_for_rag_hits():
    chunks = [
        {
            "chunk_id": "c1",
            "document_id": "doc-1",
            "chunk_text": "Noi dung test",
            "page_start": 2,
            "score": 0.42,
        }
    ]
    doc_map = {"doc-1": {"title": "Doc One", "file_url": "s3://private/doc1.pdf"}}

    out = _build_citations_safe(chunks, doc_map)

    assert len(out) == 1
    assert out[0].document_id == "doc-1"
    assert out[0].chunk_id == "c1"
