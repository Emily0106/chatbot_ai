from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RouteModeDecision:
    mode: str  # "llm_only" | "rag_vector" | "rag_lexical" | "sql_candidate"
    reason: str
    sql_candidate: bool = False
    prefer_lexical: bool = False
    is_smalltalk: bool = False
    is_agent_intro: bool = False
    is_how_to: bool = False
    is_evidence_required: bool = False
    is_general_explain: bool = False


_SMALLTALK_EXACT = {
    "xin chao",
    "xin chào",
    "chao",
    "chào",
    "hello",
    "alo",
    "cam on",
    "cảm ơn",
    "thanks",
    "thank you",
    "tam biet",
    "tạm biệt",
    "bye",
    "good morning",
    "good afternoon",
    "good evening",
}

_SMALLTALK_RE = re.compile(
    r"^(xin chào|xin chao|chào|chao|hello|alo|cảm ơn|cam on|thanks?|thank you|tạm biệt|tam biet|bye|good morning|good afternoon|good evening)[\s!,.?]*$",
    re.IGNORECASE,
)

_AGENT_INTRO_HINTS = {
    "bạn là ai",
    "ban la ai",
    "bạn là agent gì",
    "ban la agent gi",
    "bạn là trợ lý gì",
    "ban la tro ly gi",
    "giới thiệu về bạn",
    "gioi thieu ve ban",
    "bạn làm được gì",
    "ban lam duoc gi",
    "who are you",
    "what can you do",
}

_EVIDENCE_REQUIRED_HINTS = {
    "mới nhất",
    "moi nhat",
    "điều",
    "khoản",
    "trích dẫn",
    "trich dan",
    "theo văn bản",
    "theo van ban",
    "file",
    "tài liệu",
    "tai lieu",
    "căn cứ",
    "can cu",
    "nguồn",
    "nguon",
    "citation",
    "quy định",
    "quy dinh",
}

_EVIDENCE_HINTS = {
    *_EVIDENCE_REQUIRED_HINTS,
    "nghị định",
    "thông tư",
    "luật",
    "quy định",
    "chính sách",
    "văn bản",
    "trích",
    "dẫn chứng",
    "theo tài liệu",
}

_GENERAL_EXPLAIN_HINTS = {
    "giải thích",
    "giai thich",
    "khái niệm",
    "khai niem",
    "định nghĩa",
    "dinh nghia",
    "là gì",
    "la gi",
    "what is",
    "explain",
    "tổng quan",
    "tong quan",
}

_HOW_TO_HINTS = {
    "hướng dẫn",
    "huong dan",
    "cách",
    "cach",
    "làm sao",
    "lam sao",
    "how to",
    "help",
    "ingest",
    "nạp tài liệu",
    "nap tai lieu",
}

_EVIDENCE_REQUIRED_STRICT_HINTS = {
    "mới nhất",
    "moi nhat",
    "điều",
    "khoản",
    "trích dẫn",
    "trich dan",
    "theo văn bản",
    "theo van ban",
    "nguồn",
    "nguon",
    "citation",
    "căn cứ",
    "can cu",
}

_SQL_HINTS = {
    "bao nhiêu",
    "thống kê",
    "tổng hợp",
    "đếm",
    "count",
    "liệt kê",
    "danh sách",
}

_LITERAL_HINTS = {
    "điều",
    "khoản",
    "mục",
    "chương",
    "nghị định",
    "thông tư",
    "quyết định",
    "luật",
    "số",
    "trích",
    "cụm",
}

_LITERAL_RE = re.compile(
    r"(?ix)("
    r"\b\d{1,4}/\d{2,4}\b|"
    r"\bđiều\s*\d+(\s*khoản\s*\d+)?\b|"
    r"\bkhoản\s*\d+\b|"
    r"\b[A-Z]{1,8}[-_/]\d{1,8}\b"
    r")"
)


def _normalize(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _is_smalltalk(q: str) -> bool:
    if not q:
        return False
    if q in _SMALLTALK_EXACT:
        return True
    return bool(_SMALLTALK_RE.match(q))


def _is_agent_intro(q: str) -> bool:
    return any(h in q for h in _AGENT_INTRO_HINTS)


def _is_sql_candidate(q: str) -> bool:
    return any(k in q for k in _SQL_HINTS)


def _is_how_to(q: str) -> bool:
    return any(k in q for k in _HOW_TO_HINTS)


def _prefer_lexical(q: str) -> bool:
    if any(k in q for k in _LITERAL_HINTS):
        return True
    return bool(_LITERAL_RE.search(q))


def _is_evidence_required(q: str, *, is_how_to: bool) -> bool:
    if any(k in q for k in _EVIDENCE_REQUIRED_STRICT_HINTS):
        return True
    if is_how_to:
        # "How-to" prompts (for using the system) should not be forced into evidence-only mode.
        return False
    return any(k in q for k in _EVIDENCE_REQUIRED_HINTS)


def _is_general_explain(q: str, *, is_evidence_required: bool) -> bool:
    if is_evidence_required:
        return False
    return any(k in q for k in _GENERAL_EXPLAIN_HINTS)


def decide_route_mode(
    *,
    query: str,
    agent_id: str,
    security_level: int,
) -> RouteModeDecision:
    del agent_id
    q = _normalize(query)
    if not q:
        return RouteModeDecision(
            mode="rag_vector",
            reason="empty_query",
            is_smalltalk=False,
            is_agent_intro=False,
            is_how_to=False,
            is_evidence_required=False,
            is_general_explain=False,
        )

    is_smalltalk = _is_smalltalk(q)
    is_agent_intro = _is_agent_intro(q)
    is_how_to = _is_how_to(q)
    is_evidence_required = _is_evidence_required(q, is_how_to=is_how_to)
    is_general_explain = _is_general_explain(q, is_evidence_required=is_evidence_required)

    # Keep natural chat in llm-only.
    if is_smalltalk:
        return RouteModeDecision(
            mode="llm_only",
            reason="smalltalk",
            is_smalltalk=True,
            is_agent_intro=False,
            is_how_to=False,
            is_evidence_required=False,
            is_general_explain=False,
        )
    if is_agent_intro:
        return RouteModeDecision(
            mode="llm_only",
            reason="agent_intro",
            is_smalltalk=False,
            is_agent_intro=True,
            is_how_to=False,
            is_evidence_required=False,
            is_general_explain=False,
        )

    # Keep high-security interactions conservative.
    if int(security_level or 1) >= 3:
        return RouteModeDecision(
            mode="rag_vector",
            reason="security_level_high",
            sql_candidate=False,
            prefer_lexical=False,
            is_smalltalk=is_smalltalk,
            is_agent_intro=is_agent_intro,
            is_how_to=is_how_to,
            is_evidence_required=is_evidence_required,
            is_general_explain=is_general_explain,
        )

    if is_how_to:
        return RouteModeDecision(
            mode="llm_only",
            reason="how_to",
            is_smalltalk=False,
            is_agent_intro=False,
            is_how_to=True,
            is_evidence_required=False,
            is_general_explain=True,
        )

    sql_candidate = _is_sql_candidate(q)
    prefer_lexical = _prefer_lexical(q)

    if sql_candidate:
        return RouteModeDecision(
            mode="sql_candidate",
            reason="aggregate_intent",
            sql_candidate=True,
            prefer_lexical=False,
            is_smalltalk=is_smalltalk,
            is_agent_intro=is_agent_intro,
            is_how_to=is_how_to,
            is_evidence_required=is_evidence_required,
            is_general_explain=is_general_explain,
        )

    # Evidence/literal queries should favor lexical+hybrid retrieval.
    if prefer_lexical or any(k in q for k in _EVIDENCE_HINTS):
        return RouteModeDecision(
            mode="rag_lexical",
            reason="literal_or_evidence_hint",
            sql_candidate=False,
            prefer_lexical=True,
            is_smalltalk=is_smalltalk,
            is_agent_intro=is_agent_intro,
            is_how_to=is_how_to,
            is_evidence_required=is_evidence_required,
            is_general_explain=is_general_explain,
        )

    if is_general_explain:
        return RouteModeDecision(
            mode="rag_vector",
            reason="general_explain",
            sql_candidate=False,
            prefer_lexical=False,
            is_smalltalk=False,
            is_agent_intro=False,
            is_how_to=False,
            is_evidence_required=False,
            is_general_explain=True,
        )

    return RouteModeDecision(
        mode="rag_vector",
        reason="semantic_default",
        sql_candidate=False,
        prefer_lexical=False,
        is_smalltalk=is_smalltalk,
        is_agent_intro=is_agent_intro,
        is_how_to=is_how_to,
        is_evidence_required=is_evidence_required,
        is_general_explain=is_general_explain,
    )
