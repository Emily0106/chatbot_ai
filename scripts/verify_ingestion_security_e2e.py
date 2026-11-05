#!/usr/bin/env python3
"""Ingestion Security E2E Tests"""
import os
import sys

# --- env BEFORE imports ---
os.environ.setdefault("APP_MODE", "offline")
os.environ.setdefault("CI_MODE", "true")
os.environ.setdefault("ENV_MODE", "dev")

# --- ensure ingestion app/ resolves from apps/ingestion/src ---
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ING_SRC = os.path.join(REPO_ROOT, "apps", "ingestion", "src")
sys.path.insert(0, ING_SRC)

def main() -> int:
    print("== Ingestion Security E2E ==")

    # Imports AFTER sys.path + env
    from app.workers import worker_main
    from app.preproc.utils.pii import detect_pii
    from app.preproc.pipeline.interfaces import IngestMeta
    from app.core.canonical_models import Scope

    # ---- A) Scope fail-closed ----
    try:
        # Test invalid scope string
        parse_scope = getattr(worker_main, "_parse_scope", None)
        assert parse_scope is not None, "Missing helper _parse_scope in worker_main.py"
        parse_scope({"scope": "INVALID_SCOPE"}, {})
        raise AssertionError("Expected RuntimeError for invalid scope but no error raised")
    except RuntimeError as e:
        if "CRITICAL" in str(e) and "Invalid" in str(e):
            print("✅ Ingestion rejects invalid scope (fail-closed)")
        else:
            raise

    # ---- B) Metadata validation by scope ----
    validate_meta = getattr(worker_main, "_validate_meta_by_scope", None)
    assert validate_meta is not None, "Missing helper _validate_meta_by_scope in worker_main.py"

    # INTERNAL missing department_id => reject
    try:
        meta = IngestMeta(
            tenant_id="t1",
            doc_type="law",
            scope=Scope.INTERNAL,
            security_level=1,
            source_uri="test.pdf",
            checksum="abc",
            mime_type="application/pdf",
            title="Test",
            pipeline_version="v1",
            department_id=None,  # INVALID
            geo_code=None
        )
        validate_meta(meta)
        raise AssertionError("Expected RuntimeError for INTERNAL missing department_id")
    except RuntimeError as e:
        if "INTERNAL scope requires" in str(e):
            print("✅ INTERNAL requires department_id (fail-closed)")
        else:
            raise

    # RESTRICTED security_level < 3 => reject
    try:
        meta = IngestMeta(
            tenant_id="t1",
            doc_type="law",
            scope=Scope.RESTRICTED,
            security_level=1,  # TOO LOW
            source_uri="test.pdf",
            checksum="abc",
            mime_type="application/pdf",
            title="Test",
            pipeline_version="v1",
            department_id="d1",
            geo_code=None
        )
        validate_meta(meta)
        raise AssertionError("Expected RuntimeError for RESTRICTED security_level < 3")
    except RuntimeError as e:
        if "security_level >= 3" in str(e):
            print("✅ RESTRICTED requires security_level >= 3 (fail-closed)")
        else:
            raise

    # PUBLIC should pass
    meta = IngestMeta(
        tenant_id="t1",
        doc_type="law",
        scope=Scope.PUBLIC,
        security_level=1,
        source_uri="test.pdf",
        checksum="abc",
        mime_type="application/pdf",
        title="Test",
        pipeline_version="v1",
        department_id=None,
        geo_code=None
    )
    validate_meta(meta)
    print("✅ PUBLIC metadata accepted")

    # ---- C) PII detection ----
    samples = {
        "cccd": "038090000123",
        "phone": "0912345678",
        "email": "a@b.com",
    }
    for label, text in samples.items():
        contains, types = detect_pii(text)
        assert contains is True, f"Expected contains_pii=True for {label}"
        print(f"✅ PII detected: {label}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
