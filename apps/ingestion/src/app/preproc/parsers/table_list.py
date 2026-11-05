# preproc/parsers/table_list.py
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.canonical_models import (
    CanonicalChunk,
    CanonicalStructuredRow,
    DocCategory,
    ExtractedBlock,
    ExtractedBlockKind,
)
from app.preproc.pipeline.interfaces import BlockParser, ClassificationResult, IngestMeta, ParseError
from app.preproc.utils.citations import CitationContext, citation_for_csv_row, citation_for_sheet_row
from app.preproc.utils.ids import make_row_id
from app.preproc.normalizers.vi_search_norm import vi_norm


# -----------------------------
# Utilities: sheet name parsing
# -----------------------------

_SHEET_PATTERNS = [
    re.compile(r"sheet\s*[:=]\s*(.+)$", re.IGNORECASE),
    re.compile(r"worksheet\s*[:=]\s*(.+)$", re.IGNORECASE),
]


def _extract_sheet_name(anchor: Optional[str]) -> Optional[str]:
    if not anchor:
        return None
    a = anchor.strip()
    for pat in _SHEET_PATTERNS:
        m = pat.search(a)
        if m:
            name = m.group(1).strip()
            return name or None
    # common format: "sheet:Sheet1|table:0"
    if "sheet:" in a.lower():
        try:
            idx = a.lower().index("sheet:")
            tail = a[idx + len("sheet:") :]
            name = tail.split("|", 1)[0].strip()
            return name or None
        except Exception:
            return None
    return None


def _is_csv_anchor(anchor: Optional[str]) -> bool:
    if not anchor:
        return False
    return "__csv__" in anchor.lower()


# -----------------------------
# Header normalization helpers
# -----------------------------

def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def _norm_cell(x: Any) -> str:
    if x is None:
        return ""
    # keep numbers as string but preserve value
    s = str(x).strip()
    # normalize whitespace
    s = " ".join(s.split())
    return s


def _header_tokenize(s: str) -> str:
    """
    Convert header cell to a stable key token:
    - lower
    - remove accents
    - replace & with "va"
    - non-alnum -> underscore
    """
    s = _norm_cell(s).lower()
    if not s:
        return ""
    s = s.replace("&", " va ")
    s = s.replace("/", " ")
    s = _strip_accents(s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _make_unique_keys(keys: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
    for k in keys:
        base = k or "col"
        n = seen.get(base, 0) + 1
        seen[base] = n
        out.append(base if n == 1 else f"{base}_{n}")
    return out


def _forward_fill_row(row: List[str]) -> List[str]:
    """
    Forward fill horizontally to handle merged-cell style headers:
    ["Thu nhập", "", ""] -> ["Thu nhập", "Thu nhập", "Thu nhập"]
    """
    out: List[str] = []
    last = ""
    for c in row:
        c = _norm_cell(c)
        if c:
            last = c
            out.append(c)
        else:
            out.append(last)
    return out


def _guess_header_row_count(table: List[List[Any]], max_rows: int = 3) -> int:
    """
    Heuristic:
    - look at first up to 3 rows
    - header rows tend to be short strings, not too numeric
    - if row contains "stt" / "ho ten" cues -> likely header
    """
    if not table:
        return 0
    n = min(max_rows, len(table))
    scores: List[float] = []

    def row_score(r: List[Any]) -> float:
        cells = [_norm_cell(x) for x in (r or [])]
        if not cells:
            return 0.0
        non_empty = [c for c in cells if c]
        if not non_empty:
            return 0.0

        # header cues
        cue = 0.0
        joined = " ".join(non_empty).lower()
        if "stt" in joined:
            cue += 1.0
        if re.search(r"\bho\b.*\bten\b", _strip_accents(joined)):
            cue += 1.0
        if "ngay sinh" in _strip_accents(joined):
            cue += 0.6

        # numeric penalty
        numeric_like = 0
        short_like = 0
        for c in non_empty:
            if re.fullmatch(r"[\d\.,]+", c):
                numeric_like += 1
            if len(c) <= 20:
                short_like += 1

        frac_numeric = numeric_like / max(1, len(non_empty))
        frac_short = short_like / max(1, len(non_empty))

        # score: cue + shortness - numeric
        return cue + 0.6 * frac_short - 0.8 * frac_numeric

    for i in range(n):
        scores.append(row_score(table[i]))

    # choose 2 or 3 header rows if earlier rows score high and next row drops
    # default 1 if unclear
    # threshold tuned for VN gov docs
    if n >= 3 and scores[0] >= 0.6 and scores[1] >= 0.5 and scores[2] >= 0.2:
        return 3
    if n >= 2 and scores[0] >= 0.6 and scores[1] >= 0.3:
        return 2
    return 1


def _flatten_header(table: List[List[Any]], header_rows: int) -> Tuple[List[str], int]:
    """
    Returns:
      (keys, data_start_index)
    """
    if not table:
        return ([], 0)

    header_rows = max(1, min(header_rows, len(table)))
    header_matrix: List[List[str]] = []
    max_cols = max(len(r or []) for r in table[:header_rows])

    # normalize & pad rows, forward-fill horizontally
    for i in range(header_rows):
        row = [_norm_cell(x) for x in (table[i] or [])]
        if len(row) < max_cols:
            row += [""] * (max_cols - len(row))
        row = _forward_fill_row(row)
        header_matrix.append(row)

    # build column keys by joining header parts vertically
    keys: List[str] = []
    for col in range(max_cols):
        parts: List[str] = []
        for r in range(header_rows):
            val = header_matrix[r][col].strip()
            if val:
                parts.append(val)
        # de-duplicate sequential identical parts
        collapsed: List[str] = []
        for p in parts:
            if not collapsed or collapsed[-1] != p:
                collapsed.append(p)

        raw = " - ".join(collapsed).strip()
        token = _header_tokenize(raw)
        if not token:
            token = f"col_{col+1}"
        keys.append(token)

    keys = _make_unique_keys(keys)
    return keys, header_rows


# -----------------------------
# Table-like text parsing
# -----------------------------

def _parse_table_from_text(text: str, max_lines: int = 2000) -> List[List[str]]:
    """
    Heuristic parser when extractor returns "table" as a text block (OCR or poor extractor).
    Supports:
      - pipe-separated: a|b|c
      - tab-separated
      - multi-space-separated (2+ spaces)
    """
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    lines = lines[:max_lines]

    pipe_hits = sum(1 for ln in lines[:50] if ln.count("|") >= 2)
    tab_hits = sum(1 for ln in lines[:50] if "\t" in ln)

    if pipe_hits >= 5:
        split_re = re.compile(r"\s*\|\s*")
        rows = [split_re.split(ln.strip("| ").strip()) for ln in lines]
        return rows

    if tab_hits >= 3:
        rows = [ln.split("\t") for ln in lines]
        return rows

    # fallback: 2+ spaces
    split_re = re.compile(r"\s{2,}")
    rows = [split_re.split(ln) for ln in lines]
    return rows


# -----------------------------
# Search text generation
# -----------------------------

def _build_search_text(data: Dict[str, Any], max_len: int = 4096) -> str:
    """
    FTS/trgm-friendly search text.
    Example: "ho_ten Nguyen Van A dia_chi ... cccd ..."
    """
    parts: List[str] = []
    for k, v in data.items():
        if v is None:
            continue
        s = _norm_cell(v)
        if not s:
            continue
        parts.append(f"{k} {s}")
        if sum(len(p) for p in parts) >= max_len:
            break
    out = " ".join(parts)
    return out[:max_len].strip()


# -----------------------------
# Parser implementation
# -----------------------------

@dataclass
class TableListParser(BlockParser):
    """
    Parse table/list blocks into StructuredRows (JSONB).
    Summary chunk is generated by Orchestrator post-processing.

    Notes:
    - Uses `block.anchor` to infer sheet_name (e.g. "sheet:Sheet1|table:0")
    - Uses 0-based row_index within produced rows (not original Excel row index)
    - Keeps deterministic row_id via make_row_id(doc_id, row_index, sheet_name)
    """

    # If True, attempt to parse table from text blocks when classifier hints table_like_text
    enable_table_like_text: bool = True

    def parse_block(
        self,
        block: ExtractedBlock,
        meta: IngestMeta,
        classification: ClassificationResult,
        doc,
    ) -> Tuple[List[CanonicalChunk], List[CanonicalStructuredRow]]:
        try:
            # Only handle table blocks here
            if block.kind == ExtractedBlockKind.table:
                table = block.table or []
            elif block.kind == ExtractedBlockKind.text and self.enable_table_like_text:
                # allow calling this parser manually on text blocks in the future
                table = _parse_table_from_text(block.text or "")
            else:
                return [], []

            if not table:
                return [], []

            # Determine sheet_name / csv
            sheet_name = _extract_sheet_name(block.anchor) or "__sheet__"
            is_csv = _is_csv_anchor(block.anchor) or meta.mime_type.lower() in ("text/csv", "application/csv")

            # Determine header rows
            header_rows = block.table_header_rows if block.table_header_rows else _guess_header_row_count(table)
            keys, data_start = _flatten_header(table, header_rows)

            # Build citation context
            ctx = CitationContext(source_uri=meta.source_uri, checksum=meta.checksum, mime_type=meta.mime_type)

            rows: List[CanonicalStructuredRow] = []
            out_index = 0

            for i in range(data_start, len(table)):
                raw_row = table[i] or []
                # pad/truncate to keys length
                cells = [_norm_cell(x) for x in raw_row]
                if len(cells) < len(keys):
                    cells += [""] * (len(keys) - len(cells))
                elif len(cells) > len(keys):
                    cells = cells[: len(keys)]

                # skip empty rows
                if not any(c.strip() for c in cells):
                    continue

                data_content: Dict[str, Any] = {keys[j]: cells[j].strip() for j in range(len(keys))}

                search_text = _build_search_text(data_content)
                search_text_norm = vi_norm(search_text)

                row_id = make_row_id(doc_id=doc.doc_id, row_index=out_index, sheet_name=None if is_csv else sheet_name)

                # Citation: row range is relative to produced row index.
                # If you need original Excel row later, encode it in anchor.
                if is_csv:
                    cit = citation_for_csv_row(
                        ctx=ctx,
                        row_start=out_index,
                        row_end=out_index,
                        anchor=f"block:o{block.order_index}|r{i}",
                    )
                else:
                    cit = citation_for_sheet_row(
                        ctx=ctx,
                        sheet_name=sheet_name,
                        row_start=out_index,
                        row_end=out_index,
                        anchor=f"block:o{block.order_index}|r{i}",
                    )

                rows.append(
                    CanonicalStructuredRow(
                        row_id=row_id,
                        doc_id=doc.doc_id,
                        commune_id=doc.commune_id,
                        doc_category=doc.doc_category,  # list or schedule (if schedule-in-table)
                        row_index=out_index,
                        data_content=data_content,
                        search_text=search_text,
                        search_text_norm=search_text_norm,
                        citation=cit,
                    )
                )
                out_index += 1

            return [], rows

        except Exception as e:
            raise ParseError(f"TableListParser failed: {type(e).__name__}: {e}") from e
