from __future__ import annotations

from app.api.routes.chat import _sanitize_citations_for_client
from app.schemas.chat import Citation


def test_citation_doc_id_maps_to_safe_docs_endpoint():
    c = Citation(chunk_id="c1", document_id="doc-123", file_url="s3://private-bucket/internal.pdf")
    out = _sanitize_citations_for_client([c])
    assert out[0].file_url == "/api/docs/doc-123"


def test_citation_without_doc_id_drops_unsafe_path():
    c = Citation(chunk_id="c1", file_url="/var/data/private.pdf")
    out = _sanitize_citations_for_client([c])
    assert out[0].file_url is None


def test_citation_without_doc_id_keeps_safe_http_url():
    c = Citation(chunk_id="c1", file_url="https://example.org/public.pdf")
    out = _sanitize_citations_for_client([c])
    assert out[0].file_url == "https://example.org/public.pdf"
