from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import pypdf

from app.core.canonical_models import ExtractedBlock, ExtractedBlockKind, ExtractedDoc
from app.preproc.pipeline.interfaces import ExtractionError, Extractor, IngestMeta

logger = logging.getLogger(__name__)

def _count_alnum_vi(text: str) -> int:
    # copy logic tương tự docling để thresholds nhất quán
    import re
    if not text:
        return 0
    return len(re.sub(r"[^0-9A-Za-zÀ-ỹ]+", "", text))

class FastPdfExtractor(Extractor):
    """
    Fast lane PDF extractor:
    - No OCR
    - Text-only per page using pypdf
    - Output matches ExtractedDoc/ExtractedBlock schema used by DoclingExtractor
    """

    def extract(self, file_path: str, meta: IngestMeta) -> ExtractedDoc:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise ExtractionError(f"File not found: {path}")

        try:
            reader = pypdf.PdfReader(str(path), strict=False)
        except Exception as e:
            raise ExtractionError(f"PyPDF open failed: {type(e).__name__}: {e}") from e

        if getattr(reader, "is_encrypted", False):
            raise ExtractionError("Encrypted PDF is not supported in fast lane")

        page_count = len(reader.pages)
        blocks: List[ExtractedBlock] = []
        order = 0

        page_alnum: List[int] = []
        total_alnum = 0

        for p in range(page_count):
            try:
                txt = (reader.pages[p].extract_text() or "").strip()
            except Exception:
                txt = ""
            if not txt:
                page_alnum.append(0)
                continue

            a = _count_alnum_vi(txt)
            page_alnum.append(a)
            total_alnum += a

            # giữ “text block per page” giống docling
            blocks.append(
                ExtractedBlock(
                    kind=ExtractedBlockKind.text,
                    page_index=p,  # 0-based
                    order_index=order,
                    text=txt,
                    table=None,
                    table_header_rows=None,
                    anchor=f"p{p+1}",  # 1-based anchor
                    meta={"format": "text", "source": "pypdf", "mode": "fast"},
                )
            )
            order += 1

        # Fast lane không trích bảng cấu trúc
        has_tables = False

        # has_text_layer: dùng tiêu chí tương tự docling (best-effort)
        # (đặt ngưỡng đơn giản; tune bằng GovConfig sau)
        has_text_layer = total_alnum >= 250 or (page_count == 1 and total_alnum >= 50)

        return ExtractedDoc(
            mime_type=(getattr(meta, "mime_type", None) or "application/pdf"),
            blocks=blocks,
            page_count=page_count if page_count > 0 else None,
            has_text_layer=has_text_layer,
            has_tables=has_tables,
            meta={
                "extractor": "fast_pdf",
                "mode": "fast",
                "page_count": page_count,
                "page_alnum_chars": page_alnum,
                "doc_alnum_chars": total_alnum,
            },
        )
