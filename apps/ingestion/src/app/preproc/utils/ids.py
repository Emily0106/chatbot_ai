# preproc/utils/ids.py
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional, Union
from uuid import UUID, uuid5

# -----------------------------------------------------------------------------
# Deterministic UUID5 namespaces
# IMPORTANT: Do NOT change these once deployed, or you'll break idempotency.
# Generate your own once (uuid4) and hardcode forever.
# -----------------------------------------------------------------------------

NS_DOCUMENT = UUID("1b7b4a3c-5c7d-4b3a-9f9d-3a6ef3c38a10")
NS_CHUNK    = UUID("0e7dc2d1-4f7b-4b5b-90d1-2bd0c2c8d72c")
NS_ROW      = UUID("9d2c9b36-36bd-4bdb-8d6d-4d9d2d4d7e1f")
NS_JOB      = UUID("0c7fae68-3c5e-4d72-9e89-8f2c8a66e7a1")

# -----------------------------------------------------------------------------
# Hash helpers (sha256)
# -----------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    """Return hex sha256 of bytes."""
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    """Return hex sha256 of file contents (streaming)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# -----------------------------------------------------------------------------
# Normalization utilities (to keep UUID5 input stable)
# -----------------------------------------------------------------------------

def _norm_str(x: Optional[str]) -> str:
    if x is None:
        return ""
    return " ".join(str(x).strip().split())


def _norm_scope(scope: Union[str, Any]) -> str:
    # Accept Enum or str
    s = getattr(scope, "value", scope)
    return _norm_str(str(s)).lower()


def _norm_commune_id(commune_id: Optional[str]) -> str:
    # Keep as uppercase to avoid duplicates due to casing
    return _norm_str(commune_id).upper()


def _jsonish(v: Any) -> str:
    """
    Convert values to a stable string representation for UUID5 input.
    - dict: keys sorted
    - set: sorted to deterministic order
    """
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return str(v)
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if hasattr(v, "value"):  # Enum
        return str(v.value)
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(_jsonish(x) for x in v) + "]"
    if isinstance(v, (set, frozenset)):
        return "{" + ",".join(_jsonish(x) for x in sorted(list(v), key=str)) + "}"
    if isinstance(v, dict):
        items = sorted((str(k), v[k]) for k in v.keys())
        return "{" + ",".join(f"{k}:{_jsonish(val)}" for k, val in items) + "}"
    return str(v)


def _uuid5(ns: UUID, *parts: Any) -> UUID:
    """
    Stable UUID5 generator from arbitrary parts.
    """
    name = "|".join(_jsonish(p) for p in parts)
    return uuid5(ns, name)


# -----------------------------------------------------------------------------
# Public ID generators (content-addressable + idempotent)
# -----------------------------------------------------------------------------

def make_doc_id(
    *,
    tenant_id: str,
    scope: Union[str, Any],
    doc_type: str,
    checksum: str,
    commune_id: Optional[str] = None,
    source_uri: Optional[str] = None, # Make optional to allow content-addressable only if desired
) -> UUID:
    """
    Deterministic doc_id based on Ownership + Content.
    
    Hash parts:
    - tenant_id (Isolation)
    - scope (Access level)
    - doc_type (Logical grouping)
    - checksum (Content)
    - commune_id (Optional location scoping)
    
    Note: source_uri is deliberately EXCLUDED by default to ensure
    re-uploading the same file (same checksum) yields the same doc_id (Idempotency),
    even if the filename changed or path moved.
    """
    if not checksum:
        raise ValueError("checksum must not be empty")
        
    parts = [
        str(tenant_id),
        _norm_scope(scope),
        _norm_str(doc_type).lower(),
        _norm_str(checksum).lower(),
        _norm_commune_id(commune_id) if commune_id else ""
    ]
    return _uuid5(NS_DOCUMENT, *parts)


def make_chunk_id(
    *,
    doc_id: UUID,
    chunk_kind: Union[str, Any],
    order_index: int,
    # Locator fields (stable relative to the document)
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
    sheet_name: Optional[str] = None,
    row_start: Optional[int] = None,
    row_end: Optional[int] = None,
    col_start: Optional[int] = None,
    col_end: Optional[int] = None,
    anchor: Optional[str] = None,
    parent_chunk_id: Optional[UUID] = None,
) -> UUID:
    """
    Deterministic chunk_id RELATIVE to doc_id.
    Does NOT depend on source_uri / checksum to avoid re-ingest path changes
    breaking idempotency.

    Inputs include:
    - doc_id
    - chunk_kind + order_index
    - locator info (page/sheet/row/anchor) to disambiguate chunks
    - parent_chunk_id optional for Small-to-Big retrieval graphs
    """
    ck = getattr(chunk_kind, "value", chunk_kind)
    ck = _norm_str(str(ck)).lower()

    return _uuid5(
        NS_CHUNK,
        doc_id,
        ck,
        int(order_index),
        page_start if page_start is not None else "",
        page_end if page_end is not None else "",
        _norm_str(sheet_name),
        row_start if row_start is not None else "",
        row_end if row_end is not None else "",
        col_start if col_start is not None else "",
        col_end if col_end is not None else "",
        _norm_str(anchor),
        parent_chunk_id if parent_chunk_id is not None else "",
    )


def make_row_id(
    *,
    doc_id: UUID,
    row_index: int,
    sheet_name: Optional[str] = None,
) -> UUID:
    """
    Deterministic row_id for structured rows/events.
    """
    return _uuid5(NS_ROW, doc_id, _norm_str(sheet_name), int(row_index))


def make_job_id(
    *,
    doc_id: UUID,
    pipeline_version: str,
    created_at_iso: Optional[str] = None,
) -> UUID:
    """
    Job IDs: you may want uniqueness per run.

    - If created_at_iso is provided (recommended), job_id is unique per submission.
    - If omitted, the same doc_id + pipeline_version yields the same job_id.
    """
    pv = _norm_str(pipeline_version)
    if not pv:
        raise ValueError("pipeline_version must not be empty")

    if created_at_iso:
        return _uuid5(NS_JOB, doc_id, pv, created_at_iso)
    return _uuid5(NS_JOB, doc_id, pv)


# -----------------------------------------------------------------------------
# Convenience: build IDs from locator dicts (e.g., locator.model_dump())
# -----------------------------------------------------------------------------

def make_chunk_id_from_locator_dict(
    *,
    doc_id: UUID,
    chunk_kind: Union[str, Any],
    order_index: int,
    locator: Dict[str, Any],
    parent_chunk_id: Optional[UUID] = None,
) -> UUID:
    """
    Helper when you have a locator dict.
    Expected keys: page_start/page_end, sheet_name, row_start/row_end, col_start/col_end, anchor
    """
    return make_chunk_id(
        doc_id=doc_id,
        chunk_kind=chunk_kind,
        order_index=order_index,
        page_start=locator.get("page_start"),
        page_end=locator.get("page_end"),
        sheet_name=locator.get("sheet_name"),
        row_start=locator.get("row_start"),
        row_end=locator.get("row_end"),
        col_start=locator.get("col_start"),
        col_end=locator.get("col_end"),
        anchor=locator.get("anchor"),
        parent_chunk_id=parent_chunk_id,
    )


# -----------------------------------------------------------------------------
# Optional: checksum from upload stream helpers
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ChecksumResult:
    checksum: str
    size_bytes: int


def sha256_file_with_size(path: str, chunk_size: int = 1024 * 1024) -> ChecksumResult:
    h = hashlib.sha256()
    total = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            total += len(b)
            h.update(b)
    return ChecksumResult(checksum=h.hexdigest(), size_bytes=total)


def safe_basename(path: str) -> str:
    """Utility for logging/UI only (not for IDs)."""
    return os.path.basename(path)
