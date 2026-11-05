# preproc/classifiers/heuristic.py
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.core.canonical_models import DocCategory, ExtractedBlock, ExtractedBlockKind, ExtractedDoc
from app.preproc.pipeline.interfaces import (
    ClassificationError,
    ClassificationResult,
    Classifier,
    IngestMeta,
    block_key,
)

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Keyword / pattern sets (Vietnamese-centric)
# -----------------------------------------------------------------------------

SCHEDULE_KEYWORDS = {
    "lịch công tác",
    "lịch làm việc",
    "lịch tuần",
    "lịch tháng",
    "chương trình công tác",
    "thời gian",
    "địa điểm",
    "thành phần",
    "nội dung",
    "chủ trì",
    "tham dự",
    "phòng họp",
}

LIST_KEYWORDS = {
    "danh sách",
    "stt",
    "họ và tên",
    "họ tên",
    "ngày sinh",
    "địa chỉ",
    "số điện thoại",
    "cccd",
    "cmnd",
    "đối tượng",
    "hộ nghèo",
    "hộ cận nghèo",
    "trợ cấp",
    "ký nhận",
    "mức hưởng",
    "số tiền",
}

PROCEDURE_KEYWORDS = {
    "thủ tục",
    "quy trình",
    "hướng dẫn",
    "hồ sơ",
    "thành phần hồ sơ",
    "trình tự thực hiện",
    "thời hạn giải quyết",
    "cơ quan thực hiện",
    "lệ phí",
    "căn cứ pháp lý",
}

NOTICE_KEYWORDS = {
    "thông báo",
    "kính gửi",
    "đề nghị",
    "yêu cầu",
    "triển khai",
    "thực hiện",
    "nơi nhận",
}

REPORT_KEYWORDS = {
    "báo cáo",
    "tổng kết",
    "đánh giá",
    "kết quả",
    "tình hình",
    "phương hướng",
    "nhiệm vụ",
}

LEGAL_KEYWORDS = {
    "điều",
    "khoản",
    "mục",
    "chương",
    "luật",
    "nghị định",
    "thông tư",
    "quyết định",
    "căn cứ",
}

# Day-of-week cues in schedules
DOW_PATTERN = re.compile(
    r"\b(thứ\s*(hai|ba|tư|năm|sáu|bảy)|chủ\s*nhật|cn)\b",
    flags=re.IGNORECASE,
)

# Time cues
TIME_PATTERN = re.compile(
    r"\b(\d{1,2}\s*[:h]\s*\d{0,2}|\d{1,2}\s*giờ|sáng|chiều|tối)\b",
    flags=re.IGNORECASE,
)

# List/table header cues
# [UPDATED] Support "Họ & tên" by adding họ\s*[&và]\s*tên
TABLE_HEADER_PATTERN = re.compile(
    r"\b("
    r"stt|"
    r"họ\s*và\s*tên|"
    r"họ\s*[&và]\s*tên|"
    r"họ\s*tên|"
    r"ngày\s*sinh|"
    r"địa\s*chỉ|"
    r"cccd|cmnd|"
    r"chức\s*vụ|đơn\s*vị|"
    r"số\s*tiền|mức\s*hưởng"
    r")\b",
    flags=re.IGNORECASE,
)

# -----------------------------------------------------------------------------
# Feature computation
# -----------------------------------------------------------------------------

@dataclass
class DocFeatures:
    blocks_total: int
    text_blocks: int
    table_blocks: int
    figure_blocks: int

    text_chars: int
    table_cells: int

    schedule_score: float
    list_score: float
    procedure_score: float
    notice_score: float
    report_score: float
    legal_score: float

    table_ratio: float
    text_density: float


def _safe_len_text(s: Optional[str]) -> int:
    return len(s) if s else 0


def _count_table_cells(block: ExtractedBlock) -> int:
    if block.table is None:
        return 0
    cells = 0
    for row in block.table:
        if row is None:
            continue
        cells += len(row)
    return cells


def _normalize_text(s: str) -> str:
    return " ".join(s.lower().strip().split())


def _kw_hits(text: str, keywords: set[str]) -> int:
    t = _normalize_text(text)
    hits = 0
    for kw in keywords:
        if kw in t:
            hits += 1
    return hits


def _pattern_hits(text: str, pattern: re.Pattern) -> int:
    if not text:
        return 0
    return len(pattern.findall(text))


def _extract_sample_text(extracted: ExtractedDoc, max_chars: int = 12000) -> str:
    """
    Collect a bounded amount of text for keyword scoring.
    If the document has no text blocks, returns "".
    """
    buf: List[str] = []
    total = 0
    for b in extracted.blocks:
        if b.kind != ExtractedBlockKind.text or not b.text:
            continue
        chunk = b.text
        if total + len(chunk) > max_chars:
            chunk = chunk[: max(0, max_chars - total)]
        buf.append(chunk)
        total += len(chunk)
        if total >= max_chars:
            break
    return "\n".join(buf)


# -----------------------------------------------------------------------------
# Heuristic classifier
# -----------------------------------------------------------------------------

class HeuristicClassifier(Classifier):
    """
    Score-based heuristic classifier optimized for commune/government docs.
    """

    def __init__(
        self,
        *,
        low_confidence_threshold: float = 0.6,
        table_ratio_list_threshold: float = 0.12,
        schedule_table_override_threshold: float = 3.0,  # [UPDATED] schedule-in-table override
        schedule_keyword_boost: float = 1.0,
    ):
        self.low_confidence_threshold = float(low_confidence_threshold)
        self.table_ratio_list_threshold = float(table_ratio_list_threshold)
        self.schedule_table_override_threshold = float(schedule_table_override_threshold)
        self.schedule_keyword_boost = float(schedule_keyword_boost)

    def classify(self, extracted: ExtractedDoc, meta: IngestMeta) -> ClassificationResult:
        try:
            feats, sample_text = self._compute_features(extracted)

            # [UPDATED] Debug warning for scan/no-text docs
            if not sample_text.strip():
                logger.warning(
                    "Classifier: No text content found (likely scan/image-only). "
                    "mime=%s source=%s blocks=%d tables=%d figures=%d",
                    meta.mime_type,
                    meta.source_uri,
                    feats.blocks_total,
                    feats.table_blocks,
                    feats.figure_blocks,
                )

            # If user provided hint, respect it but still compute confidence
            if meta.doc_category_hint is not None:
                hinted = meta.doc_category_hint
                conf = max(0.7, self._confidence_for_hint(hinted, feats))
                return ClassificationResult(
                    doc_category=hinted,
                    confidence=conf,
                    block_overrides=self._block_overrides(extracted),
                )

            doc_category, conf = self._decide(feats)
            return ClassificationResult(
                doc_category=doc_category,
                confidence=conf,
                block_overrides=self._block_overrides(extracted),
            )
        except Exception as e:
            raise ClassificationError(f"Heuristic classification failed: {type(e).__name__}: {e}") from e

    # -------------------------
    # internals
    # -------------------------

    def _compute_features(self, extracted: ExtractedDoc) -> Tuple[DocFeatures, str]:
        blocks_total = len(extracted.blocks)
        text_blocks = 0
        table_blocks = 0
        figure_blocks = 0

        text_chars = 0
        table_cells = 0

        for b in extracted.blocks:
            if b.kind == ExtractedBlockKind.text:
                text_blocks += 1
                text_chars += _safe_len_text(b.text)
            elif b.kind == ExtractedBlockKind.table:
                table_blocks += 1
                table_cells += _count_table_cells(b)
            elif b.kind == ExtractedBlockKind.figure:
                figure_blocks += 1

        sample_text = _extract_sample_text(extracted)

        schedule_kw = _kw_hits(sample_text, SCHEDULE_KEYWORDS)
        schedule_pat = _pattern_hits(sample_text, DOW_PATTERN) + _pattern_hits(sample_text, TIME_PATTERN)
        schedule_score = float(schedule_kw) * self.schedule_keyword_boost + 0.25 * float(schedule_pat)

        list_score = float(_kw_hits(sample_text, LIST_KEYWORDS)) + 0.15 * float(_pattern_hits(sample_text, TABLE_HEADER_PATTERN))
        procedure_score = float(_kw_hits(sample_text, PROCEDURE_KEYWORDS))
        notice_score = float(_kw_hits(sample_text, NOTICE_KEYWORDS))
        report_score = float(_kw_hits(sample_text, REPORT_KEYWORDS))
        legal_score = float(_kw_hits(sample_text, LEGAL_KEYWORDS))

        denom_blocks = max(1, blocks_total)
        table_ratio = table_blocks / denom_blocks
        text_density = (text_chars / max(1, text_blocks)) if text_blocks else 0.0

        feats = DocFeatures(
            blocks_total=blocks_total,
            text_blocks=text_blocks,
            table_blocks=table_blocks,
            figure_blocks=figure_blocks,
            text_chars=text_chars,
            table_cells=table_cells,
            schedule_score=schedule_score,
            list_score=list_score,
            procedure_score=procedure_score,
            notice_score=notice_score,
            report_score=report_score,
            legal_score=legal_score,
            table_ratio=table_ratio,
            text_density=text_density,
        )
        return feats, sample_text

    def _decide(self, feats: DocFeatures) -> Tuple[DocCategory, float]:
        """
        Decision rules ordered by hard signals first, then soft scores.
        """

        # Hard signal 1: tables exist -> list/schedule (Excel schedule is common)
        if feats.table_blocks >= 1:
            table_heavy = (feats.table_ratio >= self.table_ratio_list_threshold) or (feats.table_cells >= 200)

            # [UPDATED] If schedule_score is very strong, treat as schedule even if table-heavy
            if table_heavy and feats.schedule_score >= self.schedule_table_override_threshold:
                return DocCategory.schedule, self._confidence_structured(feats, primary="schedule")

            if table_heavy:
                return DocCategory.list, self._confidence_structured(feats, primary="list")

        # Hard signal 2: schedule patterns strong (even without tables)
        if feats.schedule_score >= 2.0:
            return DocCategory.schedule, self._confidence_textual(feats, primary="schedule")

        # Textual category scoring
        scores = {
            DocCategory.procedure: feats.procedure_score,
            DocCategory.notice: feats.notice_score,
            DocCategory.report: feats.report_score,
            DocCategory.legal: feats.legal_score,
        }

        # If almost no text and no tables: mixed (unknown)
        if feats.text_chars < 200 and feats.table_blocks == 0:
            return DocCategory.mixed, 0.35

        best_cat, best_score = max(scores.items(), key=lambda kv: kv[1])

        # Weak signals -> mixed/notice fallback
        if best_score <= 0.9:
            if feats.table_blocks > 0 and feats.text_blocks > 0:
                return DocCategory.mixed, 0.55
            return DocCategory.notice, 0.50

        # Tie-ish report vs notice: reports tend to be longer
        if best_cat in (DocCategory.notice, DocCategory.report) and abs(feats.report_score - feats.notice_score) < 0.6:
            if feats.text_chars > 6000:
                best_cat = DocCategory.report

        conf = self._confidence_textual(feats, primary=best_cat.value)
        return best_cat, conf

    def _block_overrides(self, extracted: ExtractedDoc) -> Dict[str, Dict[str, str]]:
        overrides: Dict[str, Dict[str, str]] = {}

        for b in extracted.blocks:
            k = block_key(b)
            if b.kind == ExtractedBlockKind.table:
                overrides[k] = {"route_kind": "table"}
            elif b.kind == ExtractedBlockKind.text and b.text:
                # OCR or poor extract sometimes emits table-looking text blocks
                if _pattern_hits(b.text, TABLE_HEADER_PATTERN) >= 2 and len(b.text) < 1500:
                    overrides[k] = {"route_kind": "table_like_text"}
            elif b.kind == ExtractedBlockKind.figure:
                overrides[k] = {"route_kind": "figure"}

        return overrides

    # -------------------------
    # Confidence helpers
    # -------------------------

    def _confidence_for_hint(self, hinted: DocCategory, feats: DocFeatures) -> float:
        if hinted == DocCategory.list and feats.table_blocks == 0:
            return 0.65
        if hinted == DocCategory.schedule and feats.schedule_score < 1.0:
            return 0.65
        return 0.85

    def _confidence_structured(self, feats: DocFeatures, primary: str) -> float:
        table_factor = min(1.0, feats.table_ratio / max(1e-6, self.table_ratio_list_threshold))
        cell_factor = min(1.0, feats.table_cells / 600.0)
        base = 0.62 + 0.18 * table_factor + 0.12 * cell_factor
        if primary == "schedule":
            base += min(0.10, feats.schedule_score / 12.0)
        return float(max(0.35, min(0.95, base)))

    def _confidence_textual(self, feats: DocFeatures, primary: str) -> float:
        text_factor = min(1.0, feats.text_chars / 12000.0)

        if primary == "schedule":
            score_strength = min(1.0, feats.schedule_score / 4.0)
        elif primary == "procedure":
            score_strength = min(1.0, feats.procedure_score / 4.0)
        elif primary == "report":
            score_strength = min(1.0, feats.report_score / 4.0)
        elif primary == "legal":
            score_strength = min(1.0, feats.legal_score / 4.0)
        else:
            score_strength = min(1.0, feats.notice_score / 4.0)

        base = 0.50 + 0.22 * score_strength + 0.15 * text_factor
        if feats.table_blocks > 0:
            base -= 0.08
        return float(max(0.35, min(0.92, base)))
