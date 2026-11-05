# preproc/extractors/xlsx_extractor.py
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, List, Optional

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.core.canonical_models import ExtractedBlock, ExtractedBlockKind, ExtractedDoc
from app.preproc.pipeline.interfaces import ExtractionError, Extractor, IngestMeta

logger = logging.getLogger(__name__)


def _is_cell_styled_as_header(cell) -> bool:
    try:
        if cell is None:
            return False
        if cell.font is not None and bool(cell.font.bold):
            return True
        if cell.fill is not None and getattr(cell.fill, "patternType", None):
            return True
        if cell.alignment is not None and (cell.alignment.horizontal in ("center", "distributed")):
            return True
    except Exception:
        return False
    return False


def _guess_header_rows_by_style(ws: Worksheet, max_rows: int = 3, max_cols: int = 40) -> int:
    max_rows = max(1, min(max_rows, ws.max_row or 1))
    max_cols = max(1, min(max_cols, ws.max_column or 1))

    def row_score(r: int) -> float:
        styled = 0
        non_empty = 0
        numeric_like = 0
        for c in range(1, max_cols + 1):
            cell = ws.cell(row=r, column=c)
            v = cell.value
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            non_empty += 1
            if isinstance(v, (int, float)):
                numeric_like += 1
            if _is_cell_styled_as_header(cell):
                styled += 1

        if non_empty == 0:
            return 0.0
        frac_styled = styled / non_empty
        frac_numeric = numeric_like / non_empty
        return 1.2 * frac_styled - 0.8 * frac_numeric

    scores = [row_score(r) for r in range(1, max_rows + 1)]

    header_rows = 1
    if max_rows >= 2 and scores[0] >= 0.15 and scores[1] >= 0.05:
        header_rows = 2
    if max_rows >= 3 and scores[0] >= 0.15 and scores[1] >= 0.05 and scores[2] >= 0.02:
        header_rows = 3
    return header_rows


def _trim_table(table: List[List[Any]]) -> List[List[Any]]:
    if not table:
        return table

    def row_empty(r: List[Any]) -> bool:
        for v in r:
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            return False
        return True

    end = len(table)
    while end > 0 and row_empty(table[end - 1]):
        end -= 1
    table = table[:end]
    if not table:
        return table

    max_cols = max(len(r) for r in table)
    last_col = max_cols
    while last_col > 0:
        col_idx = last_col - 1
        all_empty = True
        for r in table:
            if col_idx >= len(r):
                continue
            v = r[col_idx]
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            all_empty = False
            break
        if all_empty:
            last_col -= 1
        else:
            break

    if last_col < max_cols:
        table = [r[:last_col] for r in table]
    return table


@dataclass
class XlsxExtractor(Extractor):
    """
    XLSX extractor (local-only) using openpyxl.

    Memory optimization:
    - Always load workbook read_only=True for data.
    - Load a second workbook (read_only=False) ONLY if file size <= style_guess_max_mb.
    """
    max_rows: Optional[int] = None
    max_cols: Optional[int] = None
    style_guess_max_mb: int = 5  # [NEW] only load wb_style if file <= 5MB

    def extract(self, file_path: str, meta: IngestMeta) -> ExtractedDoc:
        try:
            wb_ro = load_workbook(file_path, read_only=True, data_only=True)
        except Exception as e:
            raise ExtractionError(f"Cannot open XLSX: {type(e).__name__}: {e}") from e

        wb_style = None
        try:
            try:
                size_mb = os.path.getsize(file_path) / (1024 * 1024)
            except Exception:
                size_mb = 0.0

            if size_mb <= float(self.style_guess_max_mb):
                try:
                    wb_style = load_workbook(file_path, read_only=False, data_only=True)
                except Exception:
                    wb_style = None
            else:
                logger.info(
                    "XLSX style-guess skipped due to file size %.2fMB > %dMB",
                    size_mb, self.style_guess_max_mb
                )

            blocks: List[ExtractedBlock] = []
            order = 0
            has_tables = False

            for sheet_name in wb_ro.sheetnames:
                ws_ro = wb_ro[sheet_name]
                ws_style = wb_style[sheet_name] if (wb_style is not None and sheet_name in wb_style.sheetnames) else None

                header_rows = 1
                if ws_style is not None:
                    header_rows = _guess_header_rows_by_style(ws_style, max_rows=3, max_cols=40)

                max_r = ws_ro.max_row or 0
                max_c = ws_ro.max_column or 0
                if max_r == 0 or max_c == 0:
                    continue

                if self.max_rows is not None:
                    max_r = min(max_r, int(self.max_rows))
                if self.max_cols is not None:
                    max_c = min(max_c, int(self.max_cols))

                table: List[List[Any]] = []
                for row in ws_ro.iter_rows(min_row=1, max_row=max_r, min_col=1, max_col=max_c, values_only=True):
                    table.append(list(row))

                table = _trim_table(table)
                if not table:
                    continue

                has_tables = True
                blocks.append(
                    ExtractedBlock(
                        kind=ExtractedBlockKind.table,
                        page_index=None,
                        order_index=order,
                        table=table,
                        table_header_rows=header_rows,
                        anchor=f"sheet:{sheet_name}|table:0",
                    )
                )
                order += 1

            return ExtractedDoc(
                mime_type=meta.mime_type,
                blocks=blocks,
                page_count=None,
                has_text_layer=None,
                has_tables=has_tables,
            )
        except Exception as e:
            raise ExtractionError(f"XLSX extraction failed: {type(e).__name__}: {e}") from e
        finally:
            try:
                wb_ro.close()
            except Exception:
                pass
            try:
                if wb_style is not None:
                    wb_style.close()
            except Exception:
                pass
