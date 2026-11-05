"""
Gov-Grade Query Expansion - Preprocess Layer (PR-02).
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Dict, Any, Tuple
from pydantic import BaseModel, ConfigDict


class PreprocessResult(BaseModel):
    """Result of preprocessing a user query."""

    model_config = ConfigDict(extra="forbid")

    original_query: str
    normalized_query: str
    normalized_no_diacritic: str
    redacted_query: str

    flags: Dict[str, Any]
    must_keep_tokens: List[str]


# Pattern for Vietnamese legal documents (VBQPPL) like 123/2024/NĐ-CP
VBQPPL_PATTERN = re.compile(r"(?i)\b\d{1,5}/\d{4}/[A-ZĐa-zđ0-9\-]+\b")

# PII Patterns (Fallback conservative regex)
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_PATTERN = re.compile(r"\b(?:0[35789])\d{8}\b")
NATIONAL_ID_PATTERN = re.compile(r"\b(?:\d{9}|\d{12})\b")


def _collapse_whitespace(text: str) -> str:
    """Collapse all whitespace (spaces, tabs, newlines) into a single space and strip."""
    return " ".join(text.split())


def _remove_diacritics(text: str) -> str:
    """Remove Vietnamese diacritics and convert special characters like Đ."""
    s = text.replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def _redact_pii(text: str) -> Tuple[str, bool, List[str]]:
    """Detect and redact PII from the given text."""
    pii_types = []
    redacted = text
    
    # Check CC/CMND
    if NATIONAL_ID_PATTERN.search(redacted):
        pii_types.append("national_id")
        redacted = NATIONAL_ID_PATTERN.sub("[REDACTED_PII:NATIONAL_ID]", redacted)

    # Check Phone
    if PHONE_PATTERN.search(redacted):
        pii_types.append("phone")
        redacted = PHONE_PATTERN.sub("[REDACTED_PII:PHONE]", redacted)
        
    # Check Email
    if EMAIL_PATTERN.search(redacted):
        pii_types.append("email")
        redacted = EMAIL_PATTERN.sub("[REDACTED_PII:EMAIL]", redacted)
        
    return redacted, len(pii_types) > 0, pii_types


def preprocess_query(raw_query: str) -> PreprocessResult:
    """Preprocess the query safely (fail-closed validation)."""
    if not raw_query or not raw_query.strip():
        raise ValueError("Empty query")
    if len(raw_query) > 2000:
        raise ValueError("Query too long")

    # 1. NFKC Normalize + Collapse whitespace
    norm_str = unicodedata.normalize("NFKC", raw_query)
    normalized_query = _collapse_whitespace(norm_str)

    # 2. Lowercase + No diacritic + Collapse whitespace
    nom_diacritic = _remove_diacritics(normalized_query).lower()

    # 3. Extract must_keep_tokens
    must_keep = []
    for match in VBQPPL_PATTERN.finditer(normalized_query):
        token = match.group(0)
        # Deduplicate while preserving first-seen order
        if token not in must_keep:
            must_keep.append(token)

    # 4. PII Redaction
    redacted_query, contains_pii, pii_types = _redact_pii(normalized_query)

    # 5. Injection Detection
    try:
        from app.core.rag.safety import detect_prompt_injection
        inj_res = detect_prompt_injection(raw_query)
        injection_suspected = inj_res.get("detected", False)
    except ImportError:
        # Minimal heuristic fallback
        lowered = raw_query.lower()
        injection_suspected = (
            "ignore previous instructions" in lowered or 
            "system prompt" in lowered or 
            "you are chatgpt" in lowered
        )

    # Flags population
    flags = {
        "contains_pii": contains_pii,
        "pii_types": pii_types,
        "injection_suspected": injection_suspected
    }

    return PreprocessResult(
        original_query=raw_query,
        normalized_query=normalized_query,
        normalized_no_diacritic=nom_diacritic,
        redacted_query=redacted_query,
        flags=flags,
        must_keep_tokens=must_keep
    )
