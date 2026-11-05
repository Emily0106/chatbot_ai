# preproc/pipeline/orchestrator.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.canonical_models import (
    CanonicalDocument,
    CanonicalChunk,
    CanonicalStructuredRow,
    ChunkKind,
    DocCategory,
    Citation,
    SourceLocator,
    ExtractedDoc,
    ExtractedBlock,
    ExtractedBlockKind,
)
from app.preproc.pipeline.interfaces import IngestMeta, Classifier, Embedder
from app.preproc.pipeline.registry import ToolRegistry
from app.preproc.utils.ids import make_doc_id, make_chunk_id
from app.core.config import GovConfig
from app.utils.pdf_sniffer import sniff_pdf
from app.utils.route_pdf import decide_pdf_lane
from app.utils.meta_patch import with_meta_updates
import os

logger = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    pass


@dataclass(frozen=True)
class OrchestratorConfig:
    embed_batch_size: int = 64
    create_fallback_summary: bool = True
    max_summary_columns: int = 12
    max_summary_samples: int = 3


class IngestionOrchestrator:
    """
    End-to-end ingest:
      Extract -> Classify -> Parse (mixed routing) -> Store -> Embed(batch) -> Upsert vectors

    Properties:
      - Mixed-content safe: text & tables handled separately
      - Batch embedding: avoids OOM
      - Summary fallback: list/schedule/table must have summary chunk
      - Error isolation per block
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        classifier: Classifier,
        embedder: Embedder,
        postgres_repo: Any,
        qdrant_repo: Any,
        config: Optional[OrchestratorConfig] = None,
    ) -> None:
        self.registry = registry
        self.classifier = classifier
        self.embedder = embedder
        self.pg = postgres_repo
        self.qdrant = qdrant_repo
        self.qdrant_repo = qdrant_repo
        self.cfg = config or OrchestratorConfig()

    # -------------------------
    # Public
    # -------------------------

    def process(self, file_path: str, meta: IngestMeta) -> Dict[str, Any]:
        # 1) Deterministic doc_id (content + ownership)
        doc_id = make_doc_id(
            tenant_id=meta.tenant_id,
            scope=meta.scope,
            doc_type=meta.doc_type,
            commune_id=meta.commune_id,
            checksum=meta.checksum
        )

        # 1.5) Safety & Routing
        file_size = os.path.getsize(file_path)
        size_mb = file_size / (1024 * 1024)
        if size_mb > GovConfig.MAX_FILE_SIZE_MB:
            raise IngestionError(f"File too large: {size_mb:.2f}MB > {GovConfig.MAX_FILE_SIZE_MB}MB")

        # Smart Routing for PDF (robust check: mime OR extension)
        mime = (getattr(meta, "mime_type", "") or "").split(";")[0].strip().lower()
        is_pdf = (mime == "application/pdf") or str(file_path).lower().endswith(".pdf")
        
        if is_pdf:
            # Check if lane is forced via env
            forced_lane = GovConfig.INGEST_LANE
            if forced_lane in ("fast", "heavy"):
                lane, reason = forced_lane, f"forced_{forced_lane}"
                sniff_info = {"mode": "forced"}
            else:
                # Auto mode: sniff
                sniff_info = sniff_pdf(
                    file_path, 
                    sample_pages=GovConfig.SNIFF_SAMPLE_PAGES,
                    min_chars_has_text=GovConfig.SNIFF_MIN_CHARS_HAS_TEXT,
                    time_budget_sec=GovConfig.SNIFF_TIME_BUDGET_SEC
                )
                lane, reason = decide_pdf_lane(sniff_info)

            if lane == "reject":
                raise IngestionError(f"PDF rejected: {reason} (sniff={sniff_info})")
            
            # Inject lane into meta safely AND normalize mime if needed
            updates = {"ingest_lane": lane}
            if mime != "application/pdf":
                updates["mime_type"] = "application/pdf"
            
            meta = with_meta_updates(meta, updates)
            
            logger.info(
                "SmartRouter: doc_id=%s lane=%s reason=%s sniff=%s", 
                doc_id, lane, reason, sniff_info
            )

        # 2) Extract
        extractor = self.registry.get_extractor(file_path, meta)
        extracted = self._call_extractor(extractor, file_path, meta)

        # 3) Classify
        classification = self.classifier.classify(extracted, meta)
        doc_category: DocCategory = getattr(classification, "doc_category", DocCategory.mixed)

        # 4) Canonical Document
        doc = self._build_document(doc_id=doc_id, meta=meta, doc_category=doc_category)

        # 5) Parse with mixed routing
        chunks: List[CanonicalChunk] = []
        rows: List[CanonicalStructuredRow] = []

        text_blocks, table_blocks, other_blocks = self._split_blocks(extracted)

        # 5.1) Narrative doc-level parse (text blocks)
        if text_blocks:
            narrative_parser = self.registry.get_doc_parser(self._narrative_category(doc_category))
            if narrative_parser is not None:
                text_doc = ExtractedDoc(
                    mime_type=extracted.mime_type,
                    blocks=text_blocks,
                    page_count=getattr(extracted, "page_count", None),
                    has_text_layer=getattr(extracted, "has_text_layer", None),
                    has_tables=getattr(extracted, "has_tables", None),
                )
                try:
                    c1, r1 = self._call_doc_parser(narrative_parser, text_doc, meta, classification, doc)
                    if c1:
                        chunks.extend(c1)
                    if r1:
                        rows.extend(r1)
                except Exception as e:
                    logger.exception("Narrative parse failed (doc_id=%s)", doc_id)
                    raise IngestionError(f"Narrative parse failed (doc_id={doc_id}): {type(e).__name__}: {e}") from e

        # 5.2) Table block parse
        if table_blocks:
            for b in table_blocks:
                try:
                    block_cat = self._block_category_override(classification, b) or doc_category
                    table_parser = self.registry.get_block_parser(self._table_category(block_cat)) or self.registry.get_block_parser(
                        DocCategory.list
                    )
                    if table_parser is None:
                        continue

                    c2, r2 = self._call_block_parser(table_parser, b, meta, classification, doc)
                    if c2:
                        chunks.extend(c2)
                    if r2:
                        rows.extend(r2)
                except Exception as e:
                    logger.exception("Table block parse failed (doc_id=%s, anchor=%s)", doc_id, getattr(b, "anchor", None))
                    raise IngestionError(
                        f"Table block parse failed (doc_id={doc_id}, anchor={getattr(b, 'anchor', None)}): {type(e).__name__}: {e}"
                    ) from e

        if other_blocks:
            logger.debug("Ignoring %d non text/table blocks (doc_id=%s)", len(other_blocks), doc_id)

        # 6) Summary fallback
        if self.cfg.create_fallback_summary:
            self._ensure_summary_chunk(doc=doc, meta=meta, chunks=chunks, rows=rows)

        # 7) Store Postgres (idempotent upsert)
        self._store_postgres(doc, chunks, rows)

        # 8) Embed + upsert Qdrant (batch)
        embedded = self._embed_and_upsert(chunks)

        return {
            "doc_id": str(doc.doc_id),
            "doc_category": doc.doc_category.value,
            "blocks": len(getattr(extracted, "blocks", []) or []),
            "chunks": len(chunks),
            "rows": len(rows),
            "embedded_chunks": embedded,
        }

    # -------------------------
    # Extract / Parse callers (robust)
    # -------------------------

    def _call_extractor(self, extractor: Any, file_path: str, meta: IngestMeta) -> ExtractedDoc:
        # support extract(file_path, meta) or extract(file_path, meta=meta)
        try:
            return extractor.extract(file_path, meta=meta)
        except TypeError:
            return extractor.extract(file_path, meta)
        except Exception as e:
            raise IngestionError(f"Extraction failed: {type(e).__name__}: {e}") from e

    def _call_doc_parser(
        self,
        parser: Any,
        extracted: ExtractedDoc,
        meta: IngestMeta,
        classification: Any,
        doc: CanonicalDocument,
    ) -> Tuple[List[CanonicalChunk], List[CanonicalStructuredRow]]:
        """
        Try common signatures (for compatibility across your evolving parsers):
          - parse(extracted, meta_dict)
          - parse(extracted, meta)
          - parse(extracted, meta, classification, doc)
        """
        meta_dict = {
            "doc_id": doc.doc_id,
            "scope": doc.scope,
            "commune_id": doc.commune_id,
            "doc_category": doc.doc_category,
            "source_uri": meta.source_uri,
            "mime_type": meta.mime_type,
            "checksum": meta.checksum,
            "title": doc.title,
        }

        try:
            return parser.parse(extracted, meta_dict)
        except TypeError:
            pass

        try:
            return parser.parse(extracted, meta, classification, doc)
        except TypeError:
            pass

        return parser.parse(extracted, meta)

    def _call_block_parser(
        self,
        parser: Any,
        block: ExtractedBlock,
        meta: IngestMeta,
        classification: Any,
        doc: CanonicalDocument,
    ) -> Tuple[List[CanonicalChunk], List[CanonicalStructuredRow]]:
        # Standard signature: parse_block(block, meta, classification, doc)
        return parser.parse_block(block, meta, classification, doc)

    # -------------------------
    # Document / Blocks helpers
    # -------------------------

    def _build_document(self, *, doc_id: Any, meta: IngestMeta, doc_category: DocCategory) -> CanonicalDocument:
        title = (getattr(meta, "title", None) or "").strip()
        if not title:
            # fallback: file name from source uri
            title = Path(meta.source_uri).name

        return CanonicalDocument(
            doc_id=doc_id,
            tenant_id=meta.tenant_id,
            doc_type=meta.doc_type,
            scope=meta.scope,
            security_level=meta.security_level,
            department_id=meta.department_id,
            geo_code=meta.geo_code,
            domain=meta.domain,
            
            commune_id=meta.commune_id,
            doc_category=doc_category,
            source_uri=meta.source_uri,
            mime_type=meta.mime_type,
            checksum=meta.checksum,
            title=title,
            pipeline_version=getattr(meta, "pipeline_version", "v1"),
        )

    def _split_blocks(self, extracted: ExtractedDoc) -> Tuple[List[ExtractedBlock], List[ExtractedBlock], List[ExtractedBlock]]:
        text_blocks: List[ExtractedBlock] = []
        table_blocks: List[ExtractedBlock] = []
        other_blocks: List[ExtractedBlock] = []

        for b in (getattr(extracted, "blocks", None) or []):
            k = getattr(b, "kind", None)
            if k == ExtractedBlockKind.text:
                text_blocks.append(b)
            elif k == ExtractedBlockKind.table:
                table_blocks.append(b)
            else:
                other_blocks.append(b)

        def _sort_key(x: ExtractedBlock):
            p = getattr(x, "page_index", None)
            oi = getattr(x, "order_index", 0)
            return (p if p is not None else 10**9, oi)

        text_blocks.sort(key=_sort_key)
        table_blocks.sort(key=_sort_key)
        other_blocks.sort(key=_sort_key)
        return text_blocks, table_blocks, other_blocks

    def _narrative_category(self, doc_category: DocCategory) -> DocCategory:
        # Mixed/list/schedule still contain narrative parts
        if doc_category in (DocCategory.list, DocCategory.table, DocCategory.schedule, DocCategory.mixed):
            return DocCategory.notice
        return doc_category

    def _table_category(self, doc_category: DocCategory) -> DocCategory:
        if doc_category == DocCategory.schedule:
            return DocCategory.schedule
        return DocCategory.list

    def _block_category_override(self, classification: Any, block: ExtractedBlock) -> Optional[DocCategory]:
        overrides = getattr(classification, "block_overrides", None)
        if not overrides:
            return None

        anchor = getattr(block, "anchor", None)
        if anchor is not None and anchor in overrides:
            val = overrides[anchor]
            if isinstance(val, dict):
                cat = val.get("doc_category") or val.get("category")
                if cat:
                    try:
                        return DocCategory(cat)
                    except ValueError:
                        pass
            elif isinstance(val, (str, DocCategory)):
                 try:
                    return DocCategory(val)
                 except ValueError:
                    pass

        oi = getattr(block, "order_index", None)
        if oi is not None and oi in overrides:
            return overrides[oi]

        return None

    # -------------------------
    # Summary fallback (fixed make_chunk_id usage)
    # -------------------------

    def _ensure_summary_chunk(
        self,
        *,
        doc: CanonicalDocument,
        meta: IngestMeta,
        chunks: List[CanonicalChunk],
        rows: List[CanonicalStructuredRow],
    ) -> None:
        if doc.doc_category not in (DocCategory.list, DocCategory.table, DocCategory.schedule):
            return

        if any(getattr(c, "chunk_kind", None) == ChunkKind.summary for c in chunks):
            return

        sheet_name = None
        row_end = None

        if rows and getattr(rows[0], "citation", None) is not None:
            loc = rows[0].citation.locator
            sheet_name = getattr(loc, "sheet_name", None)
            row_end = len(rows)

        if not rows:
            summary_text = (
                f"Tài liệu bảng/danh sách: {doc.title}. "
                f"Danh mục: {doc.doc_category.value}. "
                f"(Không trích xuất được dòng dữ liệu; cần kiểm tra file nguồn.)"
            )
        else:
            sample_keys = list((rows[0].data_content or {}).keys())
            summary_text = (
                f"Bảng dữ liệu: {doc.title}. "
                f"Danh mục: {doc.doc_category.value}. "
                f"Tổng số dòng: {len(rows)}. "
                f"Các cột chính: {', '.join(sample_keys[: self.cfg.max_summary_columns])}."
            )

        # ---- FIX: make_chunk_id must receive chunk_kind ----
        try:
            chunk_id = make_chunk_id(
                doc_id=doc.doc_id,
                chunk_kind=ChunkKind.summary,
                order_index=0,
                sheet_name=sheet_name,
                anchor="summary",
            )
        except TypeError:
            # Compatibility fallback if your ids.py has simpler signature
            chunk_id = make_chunk_id(
                doc_id=doc.doc_id,
                chunk_kind=ChunkKind.summary,
                order_index=0,
            )

        citation = Citation(
            locator=SourceLocator(
                source_uri=meta.source_uri,
                checksum=meta.checksum,
                mime_type=meta.mime_type,
                sheet_name=sheet_name,
                row_start=0 if row_end is not None else None,
                row_end=row_end,
                anchor="summary",
            )
        )

        chunks.append(
            CanonicalChunk(
                chunk_id=chunk_id,
                doc_id=doc.doc_id,
                parent_chunk_id=None,
                
                tenant_id=doc.tenant_id,
                doc_type=doc.doc_type,
                scope=doc.scope,
                security_level=doc.security_level,
                department_id=doc.department_id,
                geo_code=doc.geo_code,
                domain=doc.domain,
                
                commune_id=doc.commune_id,
                doc_category=doc.doc_category,
                chunk_kind=ChunkKind.summary,
                order_index=0,
                display_text=summary_text,
                embed_text=summary_text,
                citation=citation,
                section_path=None,
                law_ref=None,
            )
        )

    # -------------------------
    # Storage + Vector
    # -------------------------

    def _store_postgres(
        self,
        doc: CanonicalDocument,
        chunks: List[CanonicalChunk],
        rows: List[CanonicalStructuredRow],
    ) -> None:
        try:
            self.pg.upsert_document(doc)
        except Exception as e:
            raise IngestionError(f"Postgres upsert_document failed: {e}") from e

        if rows:
            try:
                self.pg.upsert_rows(rows)
            except Exception:
                logger.exception("Postgres upsert_rows failed (doc_id=%s)", doc.doc_id)

        if chunks:
            try:
                self.pg.upsert_chunks(chunks)
            except Exception as e:
                raise IngestionError(f"Postgres upsert_chunks failed: {e}") from e

    def _embed_and_upsert(self, chunks: List[CanonicalChunk]) -> int:
        texts: List[str] = []
        chs: List[CanonicalChunk] = []

        for c in chunks:
            t = (getattr(c, "embed_text", None) or getattr(c, "display_text", None) or "").strip()
            if not t:
                continue
            chs.append(c)
            texts.append(t)

        if not texts:
            return 0

        bs = max(1, int(self.cfg.embed_batch_size))
        vectors: List[Any] = []

        for i in range(0, len(texts), bs):
            batch = texts[i : i + bs]
            vecs = self.embedder.embed(batch)
            if not isinstance(vecs, list) or len(vecs) != len(batch):
                raise IngestionError("Embedder returned invalid vectors length")
            vectors.extend(vecs)

        try:
            self.qdrant.upsert_chunks(chs, vectors)
        except Exception as e:
            # Ghost doc protection: if vector upsert fails, we should ideally rollback or mark doc as failed.
            # For now, we log error and raise IngestionError so the job can be retried or handled.
            # TODO: Implement pg.mark_document_status(doc_id, "FAILED_VECTOR") if available.
            logger.exception("Qdrant upsert failed (doc_id=%s). Potential ghost doc in Postgres.", chunks[0].doc_id if chunks else "unknown")
            raise IngestionError(f"Qdrant upsert failed: {e}") from e
        
        return len(chs)
