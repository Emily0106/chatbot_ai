# apps/ingestion/src/app/utils/pdf_sniffer.py
import os
import time
import re
from typing import Dict, Any, List

import pypdf

def _count_alnum_vi(text: str) -> int:
    if not text:
        return 0
    return len(re.sub(r"[^0-9A-Za-zÀ-ỹ]+", "", text))

def _pick_pages(n: int, sample_pages: int) -> List[int]:
    if n <= 0:
        return []
    if n == 1:
        return [0]
    if sample_pages <= 1:
        return [0]
    # lấy trang đầu + trang giữa + trang cuối (tối đa 3)
    pages = {0, n // 2, n - 1}
    return sorted(list(pages))[:sample_pages]

def sniff_pdf(file_path: str, sample_pages: int = 2, min_chars_has_text: int = 50, time_budget_sec: float = 0.2) -> Dict[str, Any]:
    start = time.time()
    result = {
        "ok": False,
        "error": None,
        "is_encrypted": False,
        "page_count": 0,
        "has_text_layer": False,
        "text_density": 0.0,   # avg alnum chars per sampled page
        "sniff_ms": 0,
        "file_size_bytes": os.path.getsize(file_path) if os.path.exists(file_path) else None,
    }

    try:
        reader = pypdf.PdfReader(file_path, strict=False)
        if getattr(reader, "is_encrypted", False):
            result["is_encrypted"] = True
            result["ok"] = True
            return result

        n_pages = len(reader.pages)
        result["page_count"] = n_pages

        check_pages = _pick_pages(n_pages, sample_pages)
        total_alnum = 0
        counted = 0

        for p_idx in check_pages:
            # time budget guard
            if (time.time() - start) > time_budget_sec:
                break
            try:
                text = reader.pages[p_idx].extract_text() or ""
                # Use alnum count instead of raw length to align with Docling
                chars = _count_alnum_vi(text)
                total_alnum += chars
                counted += 1
            except Exception:
                continue

        avg_chars = (total_alnum / counted) if counted > 0 else 0.0
        result["text_density"] = avg_chars
        # Use config-based threshold (default 50)
        result["has_text_layer"] = avg_chars >= float(min_chars_has_text)
        result["ok"] = True
        
        # Debug info
        result["sampled_pages"] = check_pages
        result["counted_pages"] = counted
        result["time_budget_hit"] = ((time.time() - start) > time_budget_sec)
        
        return result

    except Exception as e:
        result["error"] = str(e)
        return result

    finally:
        result["sniff_ms"] = int((time.time() - start) * 1000)
