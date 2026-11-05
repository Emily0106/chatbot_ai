# preproc/pipeline/registry.py
from __future__ import annotations

import importlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Union, Any

from app.core.canonical_models import DocCategory
from app.preproc.pipeline.interfaces import Extractor, Classifier


class UnsupportedFileFormatError(ValueError):
    pass


def _lazy_class(module_path: str, class_name: str):
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def _norm_mime(m: str) -> str:
    return (m or "").split(";")[0].strip().lower()


def _ext(file_path: Union[str, Path]) -> str:
    return Path(file_path).suffix.lower().lstrip(".")


def _guess_mime(file_path: Union[str, Path]) -> str:
    mt, _ = mimetypes.guess_type(str(file_path))
    return mt or "application/octet-stream"


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return default


@dataclass(frozen=True)
class RegistryConfig:
    allow_octetstream_fallback: bool = True
    # Nếu sau này có pdf_fast_extractor, bạn có thể dùng cờ này để ưu tiên
    prefer_pdf_fast: bool = False


class ToolRegistry:
    """
    Plugin-based registry:
      - mime/ext -> extractor factory
      - doc_category -> parser factories (doc-level / block-level)

    Lazy import để tránh lỗi thiếu dependency (docling/openpyxl...) khi boot.
    """

    def __init__(
        self,
        *,
        config: Optional[RegistryConfig] = None,
        classifier: Optional[Classifier] = None,
    ) -> None:
        self.cfg = config or RegistryConfig()
        self.classifier = classifier

        self._extractor_factories_by_mime: Dict[str, Callable[[], Extractor]] = {}
        self._extractor_factories_by_ext: Dict[str, Callable[[], Extractor]] = {}

        # Doc-level parser factories (narrative/mixed/etc)
        self._doc_parser_factories: Dict[DocCategory, Callable[[], Any]] = {}
        # Block-level parser factories (table_list/schedule/etc)
        self._block_parser_factories: Dict[DocCategory, Callable[[], Any]] = {}

        self._register_defaults()

    # -------------------------
    # Registration APIs
    # -------------------------

    def register_extractor_for_mime(self, mime_type: str, factory: Callable[[], Extractor]) -> None:
        self._extractor_factories_by_mime[_norm_mime(mime_type)] = factory

    def register_extractor_for_ext(self, ext: str, factory: Callable[[], Extractor]) -> None:
        self._extractor_factories_by_ext[ext.lower().lstrip(".")] = factory

    def register_doc_parser(self, category: DocCategory, factory: Callable[[], Any]) -> None:
        self._doc_parser_factories[category] = factory

    def register_block_parser(self, category: DocCategory, factory: Callable[[], Any]) -> None:
        self._block_parser_factories[category] = factory

    # -------------------------
    # Defaults
    # -------------------------

    def _register_defaults(self) -> None:
        # ---- Extractors (lazy) ----
        def docling_factory() -> Extractor:
            cls = _lazy_class("app.preproc.extractors.docling_extractor", "DoclingExtractor")
            return cls()

        def fast_pdf_factory() -> Extractor:
            cls = _lazy_class("app.preproc.extractors.fast_pdf_extractor", "FastPdfExtractor")
            return cls()

        def xlsx_factory() -> Extractor:
            cls = _lazy_class("app.preproc.extractors.xlsx_extractor", "XlsxExtractor")
            return cls()

        def csv_factory() -> Extractor:
            cls = _lazy_class("app.preproc.extractors.csv_extractor", "CsvExtractor")
            return cls()

        def image_factory() -> Extractor:
            # Nếu có ImageExtractor riêng thì dùng, nếu không fallback Docling
            try:
                cls = _lazy_class("app.preproc.extractors.image_extractor", "ImageExtractor")
                return cls()
            except Exception:
                return docling_factory()

        # MIME mappings
        def text_factory() -> Extractor:
            cls = _lazy_class("app.preproc.extractors.text_extractor", "TextExtractor")
            return cls()

        # MIME mappings
        self.register_extractor_for_mime("application/pdf", docling_factory)
        self.register_extractor_for_mime(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document", docling_factory
        )
        self.register_extractor_for_mime(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation", docling_factory
        )
        self.register_extractor_for_mime("text/html", docling_factory)
        self.register_extractor_for_mime("text/markdown", docling_factory)
        self.register_extractor_for_mime("text/plain", text_factory)

        self.register_extractor_for_mime(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", xlsx_factory
        )
        self.register_extractor_for_mime("text/csv", csv_factory)

        for im in ("image/png", "image/jpeg", "image/jpg", "image/webp", "image/tiff", "image/bmp"):
            self.register_extractor_for_mime(im, image_factory)

        # Extension mappings (fallback)
        for e in ("pdf", "docx", "pptx", "html", "htm", "md"):
            self.register_extractor_for_ext(e, docling_factory)
        self.register_extractor_for_ext("xlsx", xlsx_factory)
        self.register_extractor_for_ext("csv", csv_factory)
        self.register_extractor_for_ext("txt", text_factory)
        for e in ("png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp"):
            self.register_extractor_for_ext(e, image_factory)

        # ---- Parsers (lazy) ----
        def narrative_parser_factory():
            cls = _lazy_class("app.preproc.parsers.narrative", "NarrativeParser")
            return cls()

        def mixed_parser_factory():
            cls = _lazy_class("app.preproc.parsers.mixed", "MixedParser")
            return cls()

        def table_list_parser_factory():
            cls = _lazy_class("app.preproc.parsers.table_list", "TableListParser")
            return cls()

        def schedule_parser_factory():
            cls = _lazy_class("app.preproc.parsers.schedule", "ScheduleParser")
            return cls()

        # Doc-level: narrative-like categories
        for cat in (
            DocCategory.notice,
            DocCategory.report,
            DocCategory.procedure,
            DocCategory.faq,
            DocCategory.legal,
        ):
            self.register_doc_parser(cat, narrative_parser_factory)

        self.register_doc_parser(DocCategory.mixed, mixed_parser_factory)

        # Block-level: tables & schedules
        self.register_block_parser(DocCategory.list, table_list_parser_factory)
        self.register_block_parser(DocCategory.table, table_list_parser_factory)
        self.register_block_parser(DocCategory.schedule, schedule_parser_factory)

    # -------------------------
    # Selection APIs
    # -------------------------

    def get_extractor(self, file_path: Union[str, Path], meta: Any) -> Extractor:
        """
        meta is treated as duck-typed object:
          - mime_type may exist or not
        """
        mime = _norm_mime(_get_attr(meta, "mime_type", "") or "")
        if not mime or mime == "application/octet-stream":
            # guess by path
            mime = _norm_mime(_guess_mime(file_path))

        # 1) by mime
        fac = self._extractor_factories_by_mime.get(mime)
        if fac:
            # Special handling for PDF fast lane
            if mime == "application/pdf":
                lane = _get_attr(meta, "ingest_lane", "auto")
                if lane == "fast":
                    # We know fast_pdf_factory is what we want, but it's not directly exposed in this scope easily
                    # without refactoring.
                    # A cleaner way: check if we have a specific factory for this lane?
                    # Or just instantiate it here if we can access the factory function.
                    # Since factories are local to _register_defaults, we can't access them here easily.
                    # Let's use _lazy_class directly here for simplicity or refactor _register_defaults.
                    # Refactoring _register_defaults is better but invasive.
                    # Let's try to register it as a separate mime type? No.
                    # Let's just do a direct check for now.
                    cls = _lazy_class("app.preproc.extractors.fast_pdf_extractor", "FastPdfExtractor")
                    return cls()
            return fac()

        # 2) fallback by extension
        if self.cfg.allow_octetstream_fallback:
            ext = _ext(file_path)
            
            # Special handling for PDF fast lane in fallback
            if ext == "pdf":
                lane = _get_attr(meta, "ingest_lane", "auto")
                if lane == "fast":
                    cls = _lazy_class("app.preproc.extractors.fast_pdf_extractor", "FastPdfExtractor")
                    return cls()

            fac2 = self._extractor_factories_by_ext.get(ext)
            if fac2:
                return fac2()

        raise UnsupportedFileFormatError(f"No extractor for mime={mime} ext={_ext(file_path)}")

    def get_doc_parser(self, category: DocCategory) -> Optional[Any]:
        fac = self._doc_parser_factories.get(category)
        return fac() if fac else None

    def get_block_parser(self, category: DocCategory) -> Optional[Any]:
        fac = self._block_parser_factories.get(category)
        return fac() if fac else None
