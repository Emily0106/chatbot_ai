# preproc/extractors/csv_extractor.py
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from app.core.canonical_models import ExtractedBlock, ExtractedBlockKind, ExtractedDoc
from app.preproc.pipeline.interfaces import ExtractionError, Extractor, IngestMeta

logger = logging.getLogger(__name__)


def _score_delimiter(sample_lines: List[str], delim: str) -> Tuple[int, int]:
    """
    Score delimiter by consistency of column counts.
    Returns (best_consistency_score, inferred_cols)

    consistency_score: higher is better
      - count how many lines share the modal column count
      - penalize too small cols (<=1)
    """
    counts: List[int] = []
    for ln in sample_lines:
        if not ln.strip():
            continue
        # Use csv reader to respect quotes
        try:
            row = next(csv.reader([ln], delimiter=delim))
            counts.append(len(row))
        except Exception:
            continue

    if not counts:
        return (0, 0)

    # modal count
    freq = {}
    for c in counts:
        freq[c] = freq.get(c, 0) + 1
    modal_cols = max(freq.items(), key=lambda kv: kv[1])[0]
    modal_freq = freq[modal_cols]

    # penalize degenerate cases
    score = modal_freq
    if modal_cols <= 1:
        score -= 2
    return (score, modal_cols)


@dataclass
class CsvExtractor(Extractor):
    """
    CSV extractor (local-only).
    - sniff delimiter when possible
    - robust fallback: test candidate delimiters by column consistency
    - emits a single table block with anchor "sheet:__csv__|table:0"
    """
    encoding: str = "utf-8"
    max_rows: Optional[int] = None

    def extract(self, file_path: str, meta: IngestMeta) -> ExtractedDoc:
        try:
            with open(file_path, "r", encoding=self.encoding, newline="") as f:
                sample = f.read(8192)
                f.seek(0)

                delimiter = ","
                sniffed = False
                try:
                    dialect = csv.Sniffer().sniff(sample)
                    delimiter = dialect.delimiter
                    sniffed = True
                except Exception:
                    sniffed = False

                if not sniffed:
                    # Fallback: choose delimiter by consistency over first N lines
                    lines = [ln for ln in sample.splitlines()][:10]
                    candidates = [",", ";", "\t", "|"]
                    scored = []
                    for d in candidates:
                        score, cols = _score_delimiter(lines, d)
                        scored.append((score, cols, d))
                    scored.sort(reverse=True)
                    best = scored[0]
                    delimiter = best[2]

                reader = csv.reader(f, delimiter=delimiter)
                table: List[List[Any]] = []
                for i, row in enumerate(reader):
                    if self.max_rows is not None and i >= int(self.max_rows):
                        break
                    table.append([c for c in row])

            if not table:
                return ExtractedDoc(mime_type=meta.mime_type, blocks=[], has_tables=False)

            blocks = [
                ExtractedBlock(
                    kind=ExtractedBlockKind.table,
                    page_index=None,
                    order_index=0,
                    table=table,
                    table_header_rows=None,
                    anchor="sheet:__csv__|table:0|__csv__",
                )
            ]
            return ExtractedDoc(
                mime_type=meta.mime_type,
                blocks=blocks,
                page_count=None,
                has_text_layer=True,
                has_tables=True,
            )

        except UnicodeDecodeError as e:
            raise ExtractionError(
                f"CSV decode failed with encoding={self.encoding}: {e}. "
                f"Try encoding='utf-8-sig' or 'cp1258'."
            ) from e
        except Exception as e:
            raise ExtractionError(f"CSV extraction failed: {type(e).__name__}: {e}") from e
