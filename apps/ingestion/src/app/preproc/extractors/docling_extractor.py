# preproc/extractors/docling_extractor.py
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


from app.core.canonical_models import ExtractedBlock, ExtractedBlockKind, ExtractedDoc
from app.preproc.pipeline.interfaces import ExtractionError, Extractor, IngestMeta


logger = logging.getLogger(__name__)


# -----------------------------
# Helpers: markdown/table cleanup
# -----------------------------

_MD_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _count_alnum_vi(text: str) -> int:
    # Count letters/digits including Vietnamese ranges (best-effort)
    if not text:
        return 0
    return len(re.sub(r"[^0-9A-Za-zÀ-ỹ]+", "", text))


def _strip_markdown_tables(md: str) -> str:
    """
    Best-effort removal of markdown tables from markdown text to avoid duplication
    when we also emit structured table blocks.

    Removes blocks like:
      | A | B |
      |---|---|
      | 1 | 2 |
    """
    if not md:
        return md

    lines = md.splitlines()
    out: List[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        # Detect table start: header row with pipes + a separator row next
        if "|" in line and i + 1 < n and _MD_TABLE_SEP_RE.match(lines[i + 1] or ""):
            # Skip header + separator
            i += 2
            # Skip body rows until blank line or non-table-ish
            while i < n and ("|" in lines[i]) and lines[i].strip():
                i += 1
            # Also skip a single trailing blank line if present
            if i < n and not lines[i].strip():
                i += 1
            continue

        out.append(line)
        i += 1

    # Compress excessive blanks
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


# -----------------------------
# Config
# -----------------------------

@dataclass(frozen=True)
class DoclingExtractorConfig:
    """
    Production, local-first Docling extractor config.

    Key goals:
    - Security: no remote services, no external plugins
    - Performance: optimistic fast pass; rerun OCR only when needed
    - Robustness: handle mixed-content PDFs (text pages + scanned annex pages)

    OCR modes:
      - TEXT_ONLY: do_ocr=False
      - HYBRID_LAZY: do_ocr=True, force_full_page_ocr=False (OCR only bitmap regions)
      - FULL_OCR: do_ocr=True, force_full_page_ocr=True (OCR entire pages)
    """
    artifacts_path: Optional[str] = None
    require_artifacts_path: bool = True

    # Fast pass mode:
    #   "text_only"  -> fastest, no OCR model loaded
    #   "hybrid_lazy"-> safer for mixed-content, but loads OCR engine/model
    first_pass_mode: str = "text_only"  # "text_only" | "hybrid_lazy"

    # Mixed-content detection thresholds
    # Per-page: if a page has too few alnum chars, suspect it's a scanned/bitmap page.
    min_page_alnum_chars: int = 12

    # Whole-doc scan detection (fallback)
    min_doc_alnum_chars: int = 250

    # Short 1-page docs are common (giấy mời, biên lai...)
    # If page_count==1 and chars >= this, treat as digital even if < min_doc_alnum_chars
    single_page_digital_min_chars: int = 50

    # Rerun strategy:
    # - If mixed pages suspected: rerun HYBRID_LAZY first (cheaper than FULL_OCR)
    # - If still low: rerun FULL_OCR
    enable_rerun: bool = True
    allow_full_ocr_rerun: bool = True

    # OCR engine settings (local)
    ocr_engine: str = "tesseract_cli"  # "auto" | "tesseract_cli" | "tesseract" | "easyocr" | "rapidocr"
    ocr_lang: Optional[List[str]] = None  # None -> defaults per engine

    # Table extraction
    do_table_structure: bool = True
    exclude_tables_from_text: bool = True  # prefer structured table blocks

    # Safety: huge tables can explode memory downstream
    max_table_rows: int = 20000
    max_table_cells: int = 200000

    # Export shaping
    export_markdown_per_page: bool = True
    include_full_markdown_block: bool = False

    # Caching converters
    cache_ocr_converter: bool = True  # if RAM tight, set False to avoid keeping OCR model loaded


# -----------------------------
# Extractor
# -----------------------------

class DoclingExtractor(Extractor):
    """
    Docling extractor mapping to your canonical ExtractedDoc/ExtractedBlock:

    Produces:
      - Text blocks: markdown per page (page_index=1..N) when possible
      - Table blocks: structured grid List[List[str]] with page_index if available

    OCR routing (Production-friendly):
      - First pass: TEXT_ONLY or HYBRID_LAZY (configurable)
      - Evaluate per-page alnum density:
          * If any page looks "empty" but document overall has text -> mixed-content suspected
            => rerun HYBRID_LAZY (if first pass was TEXT_ONLY)
            => if still empty pages, rerun FULL_OCR (optional)
          * If whole doc is scan-like -> rerun FULL_OCR
      - Special case: 1-page short digital docs should NOT trigger OCR rerun unnecessarily.
    """

    def __init__(self, config: Optional[DoclingExtractorConfig] = None) -> None:
        self.cfg = config or DoclingExtractorConfig()
        self._converter_text_only = None
        self._converter_hybrid_lazy = None
        self._converter_full_ocr = None

    # -------------------------
    # Public API
    # -------------------------

    def extract(self, file_path: str, meta: IngestMeta) -> ExtractedDoc:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise ExtractionError(f"File not found: {path}")

        self._ensure_artifacts_policy()

        # Decide first pass mode
        first_mode = (self.cfg.first_pass_mode or "text_only").strip().lower()
        if first_mode not in ("text_only", "hybrid_lazy"):
            first_mode = "text_only"

        # Pass 1
        doc = self._convert(path, mode=first_mode)
        page_count = self._page_count(doc)
        tables = self._tables(doc)

        # Export text per page for density checking & blocks
        page_markdown = self._export_pages_markdown(doc, page_count)
        page_chars = [(_count_alnum_vi(m) if m else 0) for m in page_markdown]
        doc_chars = sum(page_chars) if page_chars else _count_alnum_vi(self._export_full_markdown(doc))

        # Decide reruns (mixed-content + scan)
        used_mode = first_mode
        reruns: List[str] = []

        if self.cfg.enable_rerun:
            # Short 1-page docs: avoid expensive OCR rerun
            if page_count == 1 and doc_chars >= self.cfg.single_page_digital_min_chars:
                # treat as digital enough
                pass
            else:
                suspect_scan_whole = (doc_chars < self.cfg.min_doc_alnum_chars)
                suspect_mixed = (page_count > 1 and any(c < self.cfg.min_page_alnum_chars for c in page_chars) and doc_chars >= self.cfg.min_doc_alnum_chars)

                # If first pass was TEXT_ONLY and mixed is suspected: rerun HYBRID_LAZY
                if suspect_mixed and used_mode == "text_only":
                    doc = self._convert(path, mode="hybrid_lazy")
                    used_mode = "hybrid_lazy"
                    reruns.append("hybrid_lazy")

                    page_count = self._page_count(doc)
                    tables = self._tables(doc)
                    page_markdown = self._export_pages_markdown(doc, page_count)
                    page_chars = [(_count_alnum_vi(m) if m else 0) for m in page_markdown]
                    doc_chars = sum(page_chars) if page_chars else _count_alnum_vi(self._export_full_markdown(doc))

                # If still scan-like or still has empty pages: rerun FULL_OCR (optional)
                still_has_empty_pages = (page_count > 0 and any(c < self.cfg.min_page_alnum_chars for c in page_chars))
                if self.cfg.allow_full_ocr_rerun and (suspect_scan_whole or still_has_empty_pages) and used_mode != "full_ocr":
                    doc = self._convert(path, mode="full_ocr")
                    used_mode = "full_ocr"
                    reruns.append("full_ocr")

                    page_count = self._page_count(doc)
                    tables = self._tables(doc)
                    page_markdown = self._export_pages_markdown(doc, page_count)
                    page_chars = [(_count_alnum_vi(m) if m else 0) for m in page_markdown]
                    doc_chars = sum(page_chars) if page_chars else _count_alnum_vi(self._export_full_markdown(doc))

        # Build blocks
        blocks: List[ExtractedBlock] = []
        order = 0

        # Text blocks
        if self.cfg.export_markdown_per_page and page_count > 0:
            for p in range(1, page_count + 1):
                md = (page_markdown[p - 1] or "").strip()
                if not md:
                    continue
                if self.cfg.exclude_tables_from_text:
                    md = _strip_markdown_tables(md)
                if not md:
                    continue

                blocks.append(
                    ExtractedBlock(
                        kind=ExtractedBlockKind.text,
                        page_index=p - 1,  # 0-based
                        order_index=order,
                        text=md,
                        table=None,
                        table_header_rows=None,
                        anchor=f"p{p}",  # 1-based anchor
                        meta={"format": "markdown", "source": "docling", "mode": used_mode},
                    )
                )
                order += 1
        else:
            md_all = self._export_full_markdown(doc).strip()
            if self.cfg.exclude_tables_from_text:
                md_all = _strip_markdown_tables(md_all)
            if md_all:
                blocks.append(
                    ExtractedBlock(
                        kind=ExtractedBlockKind.text,
                        page_index=None,
                        order_index=order,
                        text=md_all,
                        table=None,
                        table_header_rows=None,
                        anchor="doc",
                        meta={"format": "markdown", "source": "docling", "mode": used_mode},
                    )
                )
                order += 1

        if self.cfg.include_full_markdown_block:
            md_dbg = self._export_full_markdown(doc).strip()
            if md_dbg:
                blocks.append(
                    ExtractedBlock(
                        kind=ExtractedBlockKind.text,
                        page_index=None,
                        order_index=order,
                        text=md_dbg,
                        table=None,
                        table_header_rows=None,
                        anchor="doc_full",
                        meta={"format": "markdown", "source": "docling", "mode": used_mode, "includes_tables": True},
                    )
                )
                order += 1

        # Table blocks
        for idx, t in enumerate(tables):
            grid, truncated = self._table_to_grid(doc, t)
            if not grid:
                continue

            page_no = self._table_page_no(t)
            page_idx = (page_no - 1) if page_no is not None else None
            anchor = (f"p{page_no}|table:{idx}" if page_no is not None else f"table:{idx}")
            blocks.append(
                ExtractedBlock(
                    kind=ExtractedBlockKind.table,
                    page_index=page_idx,  # 0-based
                    order_index=order,
                    text=None,
                    table=grid,
                    table_header_rows=None,  # let TableListParser decide/guess
                    anchor=anchor,
                    meta={
                        "source": "docling",
                        "mode": used_mode,
                        "table_index": idx,
                        "truncated": truncated,
                        "n_rows": len(grid),
                        "n_cols": max((len(r) for r in grid), default=0),
                    },
                )
            )
            order += 1

        # Sort: by page then stable order_index (keeps text before tables on same page)
        blocks.sort(key=lambda b: (b.page_index if b.page_index is not None else 10**9, b.order_index))

        has_tables = len(tables) > 0
        has_text_layer = doc_chars >= self.cfg.single_page_digital_min_chars if page_count == 1 else doc_chars >= self.cfg.min_doc_alnum_chars

        return ExtractedDoc(
            mime_type=meta.mime_type,
            blocks=blocks,
            page_count=page_count if page_count > 0 else None,
            has_text_layer=has_text_layer,
            has_tables=has_tables,
            meta={
                "extractor": "docling",
                "mode": used_mode,
                "reruns": reruns,
                "page_count": page_count,
                "page_alnum_chars": page_chars,
                "doc_alnum_chars": doc_chars,
                "table_count": len(tables),
                "do_table_structure": self.cfg.do_table_structure,
                "exclude_tables_from_text": self.cfg.exclude_tables_from_text,
                "secure_defaults": {"enable_remote_services": False, "allow_external_plugins": False},
                "artifacts_path": self._resolved_artifacts_path(),
                "ocr_engine": self.cfg.ocr_engine,
            },
        )

    # -------------------------
    # Docling plumbing
    # -------------------------

    def _resolved_artifacts_path(self) -> Optional[str]:
        return self.cfg.artifacts_path or os.getenv("DOCLING_ARTIFACTS_PATH")

    def _ensure_artifacts_policy(self) -> None:
        if not self.cfg.require_artifacts_path:
            return
        if not self._resolved_artifacts_path():
            raise ExtractionError(
                "DoclingExtractor requires local artifacts cache in production.\n"
                "Set DoclingExtractorConfig(artifacts_path=...) or env DOCLING_ARTIFACTS_PATH.\n"
                "Tip: prefetch models/weights into that directory for air-gapped deployments."
            )

    def _convert(self, path: Path, mode: str):
        mode = (mode or "text_only").strip().lower()
        converter = self._get_converter(mode)
        try:
            res = converter.convert(path)
            return res.document
        except Exception as e:
            raise ExtractionError(f"Docling convert failed ({mode}) for {path.name}: {type(e).__name__}: {e}") from e

    def _get_converter(self, mode: str):
        """
        Cache converters to avoid re-loading heavy OCR resources.
        If RAM is tight, you can set cache_ocr_converter=False to rebuild OCR converter each time.
        """
        mode = (mode or "text_only").strip().lower()

        if mode == "text_only":
            if self._converter_text_only is None:
                self._converter_text_only = self._build_converter(do_ocr=False, force_full_page_ocr=False)
            return self._converter_text_only

        if mode == "hybrid_lazy":
            if (self._converter_hybrid_lazy is None) or (not self.cfg.cache_ocr_converter):
                conv = self._build_converter(do_ocr=True, force_full_page_ocr=False)
                if self.cfg.cache_ocr_converter:
                    self._converter_hybrid_lazy = conv
                return conv
            return self._converter_hybrid_lazy

        # full_ocr
        if (self._converter_full_ocr is None) or (not self.cfg.cache_ocr_converter):
            conv = self._build_converter(do_ocr=True, force_full_page_ocr=True)
            if self.cfg.cache_ocr_converter:
                self._converter_full_ocr = conv
            return conv
        return self._converter_full_ocr

    def _build_converter(self, do_ocr: bool, force_full_page_ocr: bool):
        """
        Build Docling DocumentConverter with strict local-first settings.
        """
        try:
            from docling.document_converter import DocumentConverter
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import PdfFormatOption
        except Exception as e:
            raise ExtractionError(
                "Docling import failed. Ensure `docling` is installed and compatible with your environment."
            ) from e

        artifacts = self._resolved_artifacts_path()

        pdf_opts = PdfPipelineOptions(artifacts_path=artifacts)
        # Security hardening
        pdf_opts.enable_remote_services = False
        pdf_opts.allow_external_plugins = False

        # Keep enrichment OFF for speed & safety
        pdf_opts.do_picture_classification = False
        pdf_opts.do_picture_description = False
        pdf_opts.do_code_enrichment = False
        pdf_opts.do_formula_enrichment = False

        # Table structure
        pdf_opts.do_table_structure = bool(self.cfg.do_table_structure)

        # OCR options
        pdf_opts.do_ocr = bool(do_ocr)
        if do_ocr:
            self._configure_ocr_options(pdf_opts, force_full_page_ocr)

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts),
                # Other formats: docling defaults; still local-first because remote services are off in PDF pipeline
            }
        )
        return converter

    def _configure_ocr_options(self, pdf_opts: Any, force_full_page_ocr: bool) -> None:
        """
        Configure OCR engine + languages with best-effort compatibility across docling versions.
        """
        engine = (self.cfg.ocr_engine or "auto").strip().lower()
        lang = self.cfg.ocr_lang

        # Default languages per engine
        if lang is None:
            if engine in ("tesseract", "tesseract_cli"):
                lang = ["vie", "eng"]
            elif engine == "easyocr":
                lang = ["vi", "en"]
            else:
                lang = []

        # Try set engine enum if available
        try:
            from docling.datamodel.pipeline_options import OcrEngine

            if engine == "easyocr":
                pdf_opts.ocr_engine = OcrEngine.EASYOCR
            elif engine == "rapidocr":
                pdf_opts.ocr_engine = OcrEngine.RAPIDOCR
            elif engine == "tesseract":
                pdf_opts.ocr_engine = OcrEngine.TESSERACT
            elif engine == "tesseract_cli":
                pdf_opts.ocr_engine = OcrEngine.TESSERACT_CLI
            else:
                pdf_opts.ocr_engine = OcrEngine.AUTO
        except Exception:
            # compatibility: ignore if enum not present
            pass

        # Try OcrOptions
        try:
            from docling.datamodel.pipeline_options import OcrOptions

            pdf_opts.ocr_options = OcrOptions(
                lang=list(lang),
                force_full_page_ocr=bool(force_full_page_ocr),
            )
            return
        except Exception:
            pass

        # Fallback: set attributes directly if present
        try:
            if getattr(pdf_opts, "ocr_options", None) is None:
                class _Tmp:  # minimal container
                    pass
                pdf_opts.ocr_options = _Tmp()
            setattr(pdf_opts.ocr_options, "lang", list(lang))
            setattr(pdf_opts.ocr_options, "force_full_page_ocr", bool(force_full_page_ocr))
        except Exception:
            pass

    # -------------------------
    # Docling document accessors
    # -------------------------

    def _page_count(self, doc: Any) -> int:
        # best-effort across versions
        try:
            v = getattr(doc, "num_pages", None)
            if callable(v):
                return int(v())
            if isinstance(v, int):
                return int(v)
        except Exception:
            pass
        try:
            pages = getattr(doc, "pages", None)
            if pages is not None:
                return int(len(pages))
        except Exception:
            pass
        return 0

    def _tables(self, doc: Any) -> List[Any]:
        try:
            t = getattr(doc, "tables", None)
            if t is None:
                return []
            return list(t)
        except Exception:
            return []

    def _export_pages_markdown(self, doc: Any, page_count: int) -> List[str]:
        if page_count <= 0:
            md = self._export_full_markdown(doc)
            return [md] if md else []

        out: List[str] = []
        for p in range(1, page_count + 1):
            out.append(self._export_page_markdown(doc, p))
        return out

    def _export_page_markdown(self, doc: Any, page_no: int) -> str:
        # Try modern signature: export_to_markdown(page_no=..., labels=...)
        labels = self._text_labels() if self.cfg.exclude_tables_from_text else None
        try:
            if labels is not None:
                return doc.export_to_markdown(page_no=page_no, labels=labels) or ""
            return doc.export_to_markdown(page_no=page_no) or ""
        except TypeError:
            # Older signature
            try:
                return doc.export_to_markdown(page_no=page_no) or ""
            except Exception:
                return ""
        except Exception:
            return ""

    def _export_full_markdown(self, doc: Any) -> str:
        labels = self._text_labels() if self.cfg.exclude_tables_from_text else None
        try:
            if labels is not None:
                return doc.export_to_markdown(labels=labels) or ""
            return doc.export_to_markdown() or ""
        except TypeError:
            try:
                return doc.export_to_markdown() or ""
            except Exception:
                return ""
        except Exception:
            return ""

    def _text_labels(self) -> Optional[set]:
        """
        Return a label set that prefers text elements only, if available in this docling version.
        If unavailable, caller will fallback to markdown table stripping.
        """
        try:
            from docling.datamodel.docling_document import DocItemLabel

            # These labels exist in many versions; if missing, exception is thrown.
            return {
                DocItemLabel.TITLE,
                DocItemLabel.SECTION_HEADER,
                DocItemLabel.PARAGRAPH,
                DocItemLabel.TEXT,
                DocItemLabel.LIST_ITEM,
            }
        except Exception:
            return None

    def _table_page_no(self, table_obj: Any) -> Optional[int]:
        """
        Best-effort: extract page_no from provenance if available.
        """
        for attr in ("prov", "provenance", "prov_items"):
            prov = getattr(table_obj, attr, None)
            if not prov:
                continue
            try:
                first = prov[0] if isinstance(prov, (list, tuple)) else prov
                page_no = getattr(first, "page_no", None)
                if page_no is not None:
                    return int(page_no)
            except Exception:
                continue
        return None

    def _table_to_grid(self, doc: Any, table_obj: Any) -> Tuple[List[List[str]], bool]:
        """
        Convert docling table to grid.
        Preference order:
          1) export_to_dataframe (best)
          2) export_to_markdown -> parse
        """
        grid: List[List[str]] = []
        truncated = False

        # 1) DataFrame path
        try:
            df = table_obj.export_to_dataframe(doc=doc)
            grid = self._df_to_grid(df)
            grid, truncated = self._truncate_grid(grid)
            return grid, truncated
        except Exception:
            pass

        # 2) Markdown path
        try:
            md = table_obj.export_to_markdown(doc=doc)
        except Exception:
            try:
                md = table_obj.export_to_markdown()
            except Exception:
                return [], False

        grid = self._parse_markdown_table(md)
        grid, truncated = self._truncate_grid(grid)
        return grid, truncated

    def _df_to_grid(self, df: Any) -> List[List[str]]:
        cols = [str(c) for c in getattr(df, "columns", [])]
        grid: List[List[str]] = [cols] if cols else []
        values = getattr(df, "values", None)
        if values is None:
            return grid
        try:
            rows = values.tolist()
        except Exception:
            rows = list(values)
        for r in rows:
            grid.append([("" if v is None else str(v)) for v in r])
        return grid

    def _parse_markdown_table(self, md: str) -> List[List[str]]:
        lines = [ln.strip() for ln in (md or "").splitlines() if ln.strip()]
        if len(lines) < 2:
            return []

        sep_idx = -1
        for i, ln in enumerate(lines[:10]):
            if _MD_TABLE_SEP_RE.match(ln) and "|" in ln:
                sep_idx = i
                break

        def split_row(ln: str) -> List[str]:
            ln = ln.strip().strip("|")
            return [p.strip() for p in ln.split("|")]

        if sep_idx <= 0:
            # fallback: try split all pipe lines
            return [split_row(ln) for ln in lines if "|" in ln]

        header = split_row(lines[sep_idx - 1])
        body = [split_row(ln) for ln in lines[sep_idx + 1 :]]
        return [header] + body

    def _truncate_grid(self, grid: List[List[str]]) -> Tuple[List[List[str]], bool]:
        if not grid:
            return grid, False

        n_rows = len(grid)
        n_cols = max((len(r) for r in grid), default=0)
        if n_cols == 0:
            return grid, False

        truncated = False

        if n_rows > self.cfg.max_table_rows:
            grid = grid[: self.cfg.max_table_rows]
            truncated = True
            n_rows = len(grid)

        cells = n_rows * n_cols
        if cells > self.cfg.max_table_cells:
            max_rows = max(2, self.cfg.max_table_cells // n_cols)  # keep header + >=1 row
            if n_rows > max_rows:
                grid = grid[:max_rows]
                truncated = True

        return grid, truncated
