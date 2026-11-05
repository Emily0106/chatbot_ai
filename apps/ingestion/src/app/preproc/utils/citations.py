# preproc/utils/citations.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.canonical_models import Citation, SourceLocator

@dataclass(frozen=True)
class CitationContext:
    """
    Context needed to build citation objects.
    passed down from Orchestrator -> Parser -> build functions.
    """
    source_uri: str
    checksum: str
    mime_type: Optional[str]


def citation_for_page_block(
    ctx: CitationContext,
    page_index: Optional[int],
    anchor: Optional[str],
    page_end: Optional[int] = None,
) -> Citation:
    """
    Build citation for a PDF/Doc/Image block.
    """
    if page_end is None:
        page_end = page_index

    loc = SourceLocator(
        source_uri=ctx.source_uri,
        checksum=ctx.checksum,
        mime_type=ctx.mime_type,
        page_start=page_index,
        page_end=page_end,
        anchor=anchor,
    )
    return Citation(locator=loc)


def citation_for_sheet_row(
    ctx: CitationContext,
    sheet_name: Optional[str],
    row_start: int,
    row_end: Optional[int],
    anchor: Optional[str] = None,
) -> Citation:
    """
    Build citation for Excel sheet row(s).
    """
    loc = SourceLocator(
        source_uri=ctx.source_uri,
        checksum=ctx.checksum,
        mime_type=ctx.mime_type,
        sheet_name=sheet_name,
        row_start=row_start,
        row_end=row_end,
        anchor=anchor,
    )
    return Citation(locator=loc)


def citation_for_csv_row(
    ctx: CitationContext,
    row_start: int,
    row_end: Optional[int],
    anchor: Optional[str] = None,
) -> Citation:
    """
    Build citation for CSV row(s).
    """
    loc = SourceLocator(
        source_uri=ctx.source_uri,
        checksum=ctx.checksum,
        mime_type=ctx.mime_type,
        sheet_name=None,  # CSV has no sheet
        row_start=row_start,
        row_end=row_end,
        anchor=anchor,
    )
    return Citation(locator=loc)
