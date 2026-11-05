# app/tools/citations.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.schemas.chat import Citation


def make_snippet(text: Optional[str], max_len: int = 280) -> str:
    """
    Cat ngan van ban de lam preview.
    - Xu ly None/rong
    - Cat dung tu (khong cat giua tu)
    - Them dau … (ellipsis)
    """
    if not text:
        return ""

    t = " ".join(text.strip().split())  # gom nhieu whitespace + newline ve 1 space
    if len(t) <= max_len:
        return t

    snippet = t[:max_len]
    # cat ve cuoi tu gan nhat
    if " " in snippet:
        snippet = snippet.rsplit(" ", 1)[0].rstrip()

    return snippet + "…"


def build_citation(
    *,
    source_id: str,
    content: Optional[str] = None,
    title: Optional[str] = None,
    url: Optional[str] = None,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
    section: Optional[str] = None,
    score: Optional[float] = None,
    default_title: str = "Tai lieu he thong",
    snippet_max_len: int = 280,
) -> Citation:
    """
    Factory tao Citation chuan tu bat ky nguon nao.
    source_id: chunk_id / row_id / file_id...
    """
    # MVP: neu chi co 1 page -> page_end = page_start
    if page_end is None and page_start is not None:
        page_end = page_start

    return Citation(
        chunk_id=str(source_id),
        title=title or default_title,
        file_url=url,
        section=section,
        page_start=page_start,
        page_end=page_end,
        score=score,
        snippet=make_snippet(content, max_len=snippet_max_len),
    )


def citations_from_rag_chunks(
    chunks: List[Dict[str, Any]],
    doc_map: Dict[str, Dict[str, Any]],
    *,
    default_title: str = "Tai lieu he thong",
) -> List[Citation]:
    """
    Dung cho RAG retrieve-then-enrich.
    chunks: dict co keys (chunk_id, document_id, chunk_text, page_start, page_end, section, score)
    doc_map: document_id -> {title, file_url}
    """
    citations: List[Citation] = []
    for ch in chunks:
        doc_id = str(ch.get("document_id") or "")
        doc = doc_map.get(doc_id, {})

        citations.append(
            build_citation(
                source_id=str(ch.get("chunk_id") or "unknown"),
                content=ch.get("chunk_text"),
                title=doc.get("title"),
                url=doc.get("file_url"),
                page_start=ch.get("page_start"),
                page_end=ch.get("page_end"),
                section=ch.get("section"),
                score=ch.get("score"),
                default_title=default_title,
            )
        )
    return citations


def citations_from_sql_rows(
    rows: List[Dict[str, Any]],
    *,
    title: str = "Du lieu SQL",
    url: Optional[str] = None,
    id_field: str = "id",
    content_field: Optional[str] = None,
    page_field: Optional[str] = None,
) -> List[Citation]:
    """
    Dung cho Agent SQL (Text-to-SQL):
    - rows: list dict tra ve tu Postgres
    - id_field: field nao dung lam source_id (vd: 'id', 'row_id')
    - content_field: neu co 1 truong mo ta de lam snippet (vd: 'note', 'name')
    - page_field: neu rows co so trang (report/page) thi map vao citation
    """
    citations: List[Citation] = []
    for r in rows:
        source_id = r.get(id_field) or "row"
        content = r.get(content_field) if content_field else None
        page = r.get(page_field) if page_field else None

        citations.append(
            build_citation(
                source_id=str(source_id),
                content=str(content) if content is not None else None,
                title=title,
                url=url,
                page_start=int(page) if isinstance(page, (int, str)) and str(page).isdigit() else None,
                page_end=None,
                section=None,
                score=None,
            )
        )
    return citations
