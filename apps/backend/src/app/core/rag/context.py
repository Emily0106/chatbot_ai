# app/core/rag/context.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

# P1 Security: Prompt injection hardening
from app.core.rag.safety import detect_prompt_injection, sanitize_context, frame_untrusted_context

_WS_RE = re.compile(r"\s+")


def _clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    t = s.strip().replace("\u00a0", " ")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = _WS_RE.sub(" ", t)
    return t.strip()


def _truncate_chars(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "…"


def _safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def _get_best_score(chunk: Dict[str, Any]) -> Optional[float]:
    """
    Prefer rerank_score if present; else fallback to score.
    """
    s = chunk.get("rerank_score")
    if s is None:
        s = chunk.get("score")
    try:
        return float(s) if s is not None else None
    except Exception:
        return None


def _meta(ch: Dict[str, Any], key: str) -> Any:
    """
    Support meta stored either at top-level or inside payload dict.
    """
    if key in ch:
        return ch.get(key)
    p = ch.get("payload") or {}
    if isinstance(p, dict) and key in p:
        return p.get(key)
    return None


def _score_kind(ch: Dict[str, Any]) -> str:
    """
    Identify score scale/type:
      - "cosine"/"vector"
      - "rrf"
      - "lexical"
      - "unknown"
    """
    v = _meta(ch, "_score_kind")
    return str(v).lower() if v is not None else "unknown"


def _build_source_header(
    idx: int,
    chunk: Dict[str, Any],
    doc_meta: Dict[str, Any],
    *,
    include_scores_in_prompt: bool,
) -> str:
    title = (doc_meta.get("title") or "").strip() or "Tai lieu he thong"
    file_url = (doc_meta.get("file_url") or "").strip()
    document_id = str(chunk.get("document_id") or "")

    section = (chunk.get("section") or "").strip()
    heading = (chunk.get("heading_path") or "").strip()

    p1 = _safe_int(chunk.get("page_start"))
    p2 = _safe_int(chunk.get("page_end"))

    bits: List[str] = [f"[SOURCE {idx}] {title}"]

    # Traceability
    if document_id:
        bits.append(f"DocID: {document_id}")
    if file_url:
        bits.append(f"URL: {file_url}")

    if section:
        bits.append(f"Section: {section}")
    elif heading:
        bits.append(f"Heading: {heading}")

    if p1 is not None:
        if p2 is None or p2 == p1:
            bits.append(f"Page: {p1}")
        else:
            bits.append(f"Pages: {p1}-{p2}")

    # Default OFF to avoid LLM anchoring on score
    if include_scores_in_prompt:
        score = _get_best_score(chunk)
        if score is not None:
            bits.append(f"Score: {score:.3f}")

    return " | ".join(bits)


def _fingerprint(chunk: Dict[str, Any]) -> str:
    """
    Dedup fingerprint logic (Corrected):
      1) parent_id: Highest priority (group multiple child chunks of same parent)
      2) chunk_id: If no parent exists
      3) fallback: document_id + heading + prefix(chunk_text)
    """
    pid = chunk.get("parent_id")
    if pid:
        return f"pid:{pid}"

    cid = chunk.get("chunk_id")
    if cid:
        return f"cid:{cid}"

    did = chunk.get("document_id") or ""
    heading = (chunk.get("heading_path") or "").strip().lower()
    txt = _clean_text(chunk.get("chunk_text") or "")
    prefix = txt[:180].lower()
    return f"did:{did}|h:{heading}|p:{prefix}"


def dedup_chunks(
    chunks: Sequence[Dict[str, Any]],
    *,
    max_per_document: int = 6,
    max_total: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Remove duplicates and cap per-document chunks to improve diversity.
    """
    seen_fp: set[str] = set()
    per_doc_count: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []

    for ch in chunks:
        fp = _fingerprint(ch)
        if fp in seen_fp:
            continue
        seen_fp.add(fp)

        did = str(ch.get("document_id") or "")
        c = per_doc_count.get(did, 0)
        if did and c >= max_per_document:
            continue

        out.append(ch)
        if did:
            per_doc_count[did] = c + 1

        if max_total is not None and len(out) >= max_total:
            break

    return out


@dataclass(frozen=True)
class ContextBuildResult:
    """Result from building LLM context"""
    context: str
    used_chunks: List[Dict[str, Any]]
    stats: Dict[str, Any]
    injection_detected: bool = False  # P1 Security: Prompt injection flag


def build_context(
    chunks: Sequence[Dict[str, Any]],
    doc_map: Dict[str, Dict[str, Any]],
    *,
    max_total_chars: int = 9000,
    max_chunk_chars: int = 1400,
    dedup: bool = True,
    max_per_document: int = 6,
    max_chunks: int = 12,
    include_scores: bool = True,
    include_scores_in_prompt: bool = False,  # IMPORTANT: default OFF
    prefer_parent_text: bool = True,
) -> ContextBuildResult:
    """
    Build LLM context from retrieved chunks + document metadata.

    Hybrid/Lexical safety:
      - Do NOT blindly re-sort by raw `score` when score scales are mixed
        (cosine vs rrf vs lexical). If mixed, keep fused order from retrieve.
      - Sorting is safe if rerank_score exists (same logit scale),
        or all chunks share the same _score_kind.
    """
    if max_total_chars <= 0:
        return ContextBuildResult(context="", used_chunks=[], stats={"reason": "max_total_chars<=0"})

    items = list(chunks)

    # Sort by score ONLY when safe
    if include_scores:
        has_rerank = any(ch.get("rerank_score") is not None for ch in items)
        kinds = {_score_kind(ch) for ch in items if _get_best_score(ch) is not None}

        if has_rerank or len(kinds) <= 1:
            def _score(ch: Dict[str, Any]) -> float:
                s = _get_best_score(ch)
                return s if s is not None else -1e9
            items.sort(key=_score, reverse=True)
        # else: mixed score scales -> keep fused order (do not re-sort)

    # Dedup + cap
    if dedup:
        items = dedup_chunks(items, max_per_document=max_per_document, max_total=max_chunks)
    else:
        items = items[:max_chunks]

    parts: List[str] = []
    used: List[Dict[str, Any]] = []
    used_chars = 0

    for idx, ch in enumerate(items, start=1):
        # Clean prefer_parent_text logic
        raw = None
        if prefer_parent_text:
            raw = ch.get("parent_text")
        if not raw:
            raw = ch.get("chunk_text") or ch.get("parent_text")

        raw_text = _clean_text(raw or "")
        if not raw_text:
            continue

        text = _truncate_chars(raw_text, max_chunk_chars)

        did = str(ch.get("document_id") or "")
        doc_meta = doc_map.get(did, {}) if did else {}

        header = _build_source_header(idx, ch, doc_meta, include_scores_in_prompt=include_scores_in_prompt)
        block = f"{header}\n{text}"

        projected = used_chars + len(block) + (2 if parts else 0)
        if projected > max_total_chars:
            # Ensure we include at least 1 source block
            if not parts:
                remaining = max_total_chars - len(header) - 1
                if remaining > 20:
                    block = f"{header}\n{_truncate_chars(text, remaining)}"
                    parts.append(block)
                    used.append(ch)
                    used_chars = len(block)
            break

        parts.append(block)
        used.append(ch)
        used_chars = projected

    context = "\n\n".join(parts)
    
    # P1 Security: Prompt Injection Hardening
    injection_result = detect_prompt_injection(context)
    injection_detected = injection_result["detected"]
    
    if injection_detected:
        # Sanitize detected injection patterns
        context = sanitize_context(context)
    
    # Always frame context as untrusted evidence
    context = frame_untrusted_context(context)
    
    stats = {
        "chunks_in": len(chunks),
        "chunks_used": len(used),
        "chars_used": len(context),
        "max_total_chars": max_total_chars,
        "max_chunk_chars": max_chunk_chars,
        "dedup": dedup,
        "max_per_document": max_per_document,
        "max_chunks": max_chunks,
        "prefer_parent_text": prefer_parent_text,
        "include_scores": include_scores,
        "include_scores_in_prompt": include_scores_in_prompt,
        "score_kinds": sorted({_score_kind(ch) for ch in items if _get_best_score(ch) is not None}),
        "injection_detected": injection_detected,  # P1 Security: Add to stats
        "injection_patterns": injection_result.get("hits", []),  # Pattern IDs
    }
    return ContextBuildResult(
        context=context, 
        used_chunks=used, 
        stats=stats,
        injection_detected=injection_detected
    )
