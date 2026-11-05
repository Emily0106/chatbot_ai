"""Centralized Query Expansion audit metadata helpers.

Ensures both blocking and streaming paths emit identical
QE fields in audit_event("rag.access") payloads.

Gov-grade rules:
  - NEVER include raw query, normalized query, or redacted query
  - Always return safe defaults when QE is disabled or meta is missing
"""
from __future__ import annotations
from typing import Any, Dict, Optional


_QE_SAFE_DEFAULTS: Dict[str, Any] = {
    "expansion_applied": False,
    "variants_count": 1,
    "variant_sources": {"ORIGINAL": 1},
    "llm_used": False,
    "llm_timeout": False,
    "lexicon_version": "0",
    "contains_pii": False,
    "injection_suspected": False,
    "is_code_query": False,
    "must_keep_tokens_count": 0,
}

# Keys that must NEVER appear in audit payload (PII / raw text)
_FORBIDDEN_KEYS = frozenset({
    "original_query",
    "normalized_query",
    "redacted_query",
    "raw_query",
    "query",
})


def qe_audit_defaults() -> Dict[str, Any]:
    """Return a fresh copy of safe QE audit defaults."""
    return dict(_QE_SAFE_DEFAULTS)


def qe_audit_from_meta(meta: Any) -> Dict[str, Any]:
    """Extract QE audit dict from response meta, with safe fallback.

    Args:
        meta: A response meta object (Pydantic model or dict) that may
              contain a ``query_expansion_audit`` attribute/key.

    Returns:
        Dict safe for spreading into ``audit_event("rag.access", ...)``.
        Guaranteed to never contain raw query keys.
    """
    qe_meta: Optional[Dict[str, Any]] = None

    if meta is None:
        return qe_audit_defaults()

    # Try attribute access (Pydantic model)
    if hasattr(meta, "query_expansion_audit"):
        qe_meta = getattr(meta, "query_expansion_audit", None)

    # Try dict access
    if qe_meta is None and isinstance(meta, dict):
        qe_meta = meta.get("query_expansion_audit")

    if not qe_meta or not isinstance(qe_meta, dict):
        return qe_audit_defaults()

    # Defensive: strip any forbidden keys that might have leaked
    result = {k: v for k, v in qe_meta.items() if k not in _FORBIDDEN_KEYS}

    # Ensure all expected keys exist (merge defaults for missing)
    for key, default_val in _QE_SAFE_DEFAULTS.items():
        result.setdefault(key, default_val)

    return result
