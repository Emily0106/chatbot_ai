from pathlib import Path
from typing import Union

from app.preproc.pipeline.interfaces import Extractor, IngestMeta
from app.core.canonical_models import ExtractedDoc, ExtractedBlock, ExtractedBlockKind

class TextExtractor(Extractor):
    """
    Simple extractor for .txt files.
    Reads content as UTF-8 string and returns single text block.
    """
    def extract(self, file_path: str, meta: IngestMeta) -> ExtractedDoc:
        p = Path(file_path)
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Fallback for common encodings if needed, or strict fail
            text = p.read_text(encoding="latin-1")

        block = ExtractedBlock(
            kind=ExtractedBlockKind.text,
            text=text,
            order_index=0
        )

        return ExtractedDoc(
            mime_type=meta.mime_type or "text/plain",
            blocks=[block],
            has_text_layer=True,
            has_tables=False
        )
