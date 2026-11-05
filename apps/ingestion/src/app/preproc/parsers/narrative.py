# preproc/parsers/narrative.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from app.core.canonical_models import (
    CanonicalChunk,
    CanonicalDocument,
    CanonicalStructuredRow,
    ChunkKind,
    ExtractedBlock,
    ExtractedBlockKind,
)
from app.preproc.pipeline.interfaces import BlockParser, ClassificationResult, IngestMeta, ParseError
from app.preproc.utils.citations import CitationContext, citation_for_page_block
from app.preproc.utils.ids import make_chunk_id


_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

# [NEW] add missing whitespace after punctuation: "ChuongI.Quy..." -> "ChuongI. Quy..."
_PUNCT_GLUE_RE = re.compile(r"(?<=[\.\,\;\:\!\?])(?=[^\s\n])")

# [NEW] normalize bullet points to markdown "* "
_BULLET_LINE_RE = re.compile(r"^\s*(?:[•‣◦▪●–—]|-\s+)\s*", re.MULTILINE)


def _clean_text(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n")

    # [NEW] Fix glued punctuation (best-effort)
    # insert a space after punctuation if next char is not whitespace/newline
    t = _PUNCT_GLUE_RE.sub(" ", t)

    # [NEW] Normalize bullets to markdown list markers
    # convert leading bullets/dashes to "* "
    t = _BULLET_LINE_RE.sub("* ", t)

    # Reduce excessive blank lines
    t = _MULTI_BLANK_RE.sub("\n\n", t)
    return t.strip()


def _split_paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _mk_breadcrumb(stack: List[Tuple[int, str]]) -> str:
    return " > ".join(title for _, title in stack) if stack else ""


@dataclass
class NarrativeParser(BlockParser):
    """
    Markdown-first narrative parsing with parent-child chunking.
    """

    max_child_chars: int = 1200
    min_child_chars: int = 40
    parent_max_chars: int = 4200
    parent_overlap_chars: int = 200

    def parse(
        self,
        extracted: ExtractedDoc,
        meta: IngestMeta,
        classification: ClassificationResult,
        doc: CanonicalDocument,
    ) -> Tuple[List[CanonicalChunk], List[CanonicalStructuredRow]]:
        chunks: List[CanonicalChunk] = []
        rows: List[CanonicalStructuredRow] = []
        for b in extracted.iter_blocks():
            c, r = self.parse_block(b, meta, classification, doc)
            chunks.extend(c)
            rows.extend(r)
        return chunks, rows

    def parse_block(
        self,
        block: ExtractedBlock,
        meta: IngestMeta,
        classification: ClassificationResult,
        doc: CanonicalDocument,
    ) -> Tuple[List[CanonicalChunk], List[CanonicalStructuredRow]]:
        try:
            if block.kind != ExtractedBlockKind.text:
                return [], []
            if not block.text or not block.text.strip():
                return [], []

            raw = _clean_text(block.text)
            if len(raw) < self.min_child_chars:
                return [], []

            ctx = CitationContext(source_uri=meta.source_uri, checksum=meta.checksum, mime_type=meta.mime_type)
            sections = self._split_markdown_sections(raw)

            all_chunks: List[CanonicalChunk] = []
            global_order_base = max(0, int(block.order_index)) * 10000
            local_order = 0

            for sec_idx, sec in enumerate(sections):
                breadcrumb = sec["breadcrumb"]
                heading_line = sec["heading_line"]
                body = sec["body"]

                paragraphs = _split_paragraphs(body) if body else []
                if not paragraphs and heading_line:
                    paragraphs = [heading_line.strip()]

                parent_groups = self._group_paragraphs_for_parent(heading_line, paragraphs)

                for parent_idx, group in enumerate(parent_groups):
                    parent_text = group["text"]
                    child_paras = group["paras"]

                    if not parent_text.strip():
                        continue

                    parent_anchor = self._anchor(block.anchor, f"sec{sec_idx}", f"parent{parent_idx}")
                    parent_cit = citation_for_page_block(
                        ctx=ctx,
                        page_index=block.page_index,
                        anchor=parent_anchor,
                        page_end=block.page_index,
                    )
                    parent_id = make_chunk_id(
                        doc_id=doc.doc_id,
                        chunk_kind=ChunkKind.paragraph,
                        order_index=global_order_base + local_order,
                        page_start=block.page_index,
                        page_end=block.page_index,
                        anchor=parent_anchor,
                        parent_chunk_id=None,
                    )

                    parent_display = parent_text
                    parent_embed = f"[{breadcrumb}] {parent_text}" if breadcrumb else parent_text

                    all_chunks.append(
                        CanonicalChunk(
                            chunk_id=parent_id,
                            doc_id=doc.doc_id,
                            tenant_id=doc.tenant_id,
                            doc_type=doc.doc_type,
                            scope=doc.scope,
                            security_level=doc.security_level,
                            department_id=doc.department_id,
                            geo_code=doc.geo_code,
                            domain=doc.domain,
                            commune_id=doc.commune_id,
                            doc_category=doc.doc_category,
                            chunk_kind=ChunkKind.paragraph,
                            order_index=global_order_base + local_order,
                            display_text=parent_display,
                            embed_text=parent_embed,
                            citation=parent_cit,
                            parent_chunk_id=None,
                            law_ref=None,
                            section_path=breadcrumb or None,
                        )
                    )
                    local_order += 1

                    for child_idx, para in enumerate(child_paras):
                        para = para.strip()
                        if len(para) < self.min_child_chars and len(child_paras) > 1:
                            continue

                        child_slices = self._slice_text(para, self.max_child_chars)
                        for slice_idx, child_text in enumerate(child_slices):
                            child_anchor = self._anchor(
                                block.anchor,
                                f"sec{sec_idx}",
                                f"parent{parent_idx}",
                                f"child{child_idx}",
                                f"part{slice_idx}",
                            )
                            child_cit = citation_for_page_block(
                                ctx=ctx,
                                page_index=block.page_index,
                                anchor=child_anchor,
                                page_end=block.page_index,
                            )

                            child_id = make_chunk_id(
                                doc_id=doc.doc_id,
                                chunk_kind=ChunkKind.paragraph,
                                order_index=global_order_base + local_order,
                                page_start=block.page_index,
                                page_end=block.page_index,
                                anchor=child_anchor,
                                parent_chunk_id=parent_id,
                            )

                            child_embed = f"[{breadcrumb}] {child_text}" if breadcrumb else child_text

                            all_chunks.append(
                                CanonicalChunk(
                                    chunk_id=child_id,
                                    doc_id=doc.doc_id,
                                    tenant_id=doc.tenant_id,
                                    doc_type=doc.doc_type,
                                    scope=doc.scope,
                                    security_level=doc.security_level,
                                    department_id=doc.department_id,
                                    geo_code=doc.geo_code,
                                    domain=doc.domain,
                                    commune_id=doc.commune_id,
                                    doc_category=doc.doc_category,
                                    chunk_kind=ChunkKind.paragraph,
                                    order_index=global_order_base + local_order,
                                    display_text=child_text,
                                    embed_text=child_embed,
                                    citation=child_cit,
                                    parent_chunk_id=parent_id,
                                    law_ref=None,
                                    section_path=breadcrumb or None,
                                )
                            )
                            local_order += 1

            return all_chunks, []

        except Exception as e:
            raise ParseError(f"NarrativeParser failed: {type(e).__name__}: {e}") from e

    def _split_markdown_sections(self, text: str) -> List[dict]:
        lines = text.split("\n")
        sections: List[dict] = []

        stack: List[Tuple[int, str]] = []
        cur_heading_line = ""
        cur_body: List[str] = []

        def flush():
            if not cur_heading_line and not any(x.strip() for x in cur_body):
                return
            breadcrumb = _mk_breadcrumb(stack)
            body = "\n".join(cur_body).strip()
            sections.append({"breadcrumb": breadcrumb, "heading_line": cur_heading_line.strip(), "body": body})

        for ln in lines:
            m = _MD_HEADING_RE.match(ln)
            if m:
                flush()
                level = len(m.group(1))
                title = m.group(2).strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                cur_heading_line = ln.strip()
                cur_body = []
            else:
                cur_body.append(ln)

        flush()
        if not sections:
            sections = [{"breadcrumb": "", "heading_line": "", "body": text.strip()}]
        return sections

    def _group_paragraphs_for_parent(self, heading_line: str, paragraphs: List[str]) -> List[dict]:
        groups: List[dict] = []
        if not paragraphs:
            text = heading_line.strip()
            return [{"text": text, "paras": [text] if text else []}]

        i = 0
        while i < len(paragraphs):
            buf: List[str] = []
            paras: List[str] = []
            total = 0

            if heading_line:
                buf.append(heading_line)
                total += len(heading_line) + 1

            while i < len(paragraphs):
                p = paragraphs[i].strip()
                if not p:
                    i += 1
                    continue
                add_len = len(p) + 2
                if total > 0 and total + add_len > self.parent_max_chars and paras:
                    break
                buf.append(p)
                paras.append(p)
                total += add_len
                i += 1

            parent_text = "\n\n".join(buf).strip()
            groups.append({"text": parent_text, "paras": paras})

            if self.parent_overlap_chars > 0 and i < len(paragraphs) and paras:
                if len(paras[-1]) >= self.parent_overlap_chars:
                    i -= 1

        return groups

    def _slice_text(self, text: str, max_chars: int) -> List[str]:
        t = text.strip()
        if len(t) <= max_chars:
            return [t]

        out: List[str] = []
        start = 0
        while start < len(t):
            end = min(len(t), start + max_chars)
            window = t[start:end]

            m = re.search(r"([\.!\?]\s+|\n)\s*$", window)
            if m and end != len(t):
                cut = start + m.end()
            else:
                ws = window.rfind(" ")
                cut = start + ws if ws > int(0.6 * max_chars) else end

            chunk = t[start:cut].strip()
            if chunk:
                out.append(chunk)
            start = max(cut, start + 1)

        return out

    @staticmethod
    def _anchor(base: Optional[str], *parts: str) -> str:
        b = (base or "block").strip()
        tail = "|".join(p for p in parts if p)
        return f"{b}|{tail}" if tail else b
