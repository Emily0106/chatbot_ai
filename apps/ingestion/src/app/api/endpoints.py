from __future__ import annotations

import os
import shutil
import logging
from pathlib import Path
from uuid import uuid4, UUID

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends

from app.core.config import settings
from app.core.taxonomy import DocType, Scope, SecurityLevel, IngestionError, TenantId
from app.core.auth_context import get_trusted_context, TrustedContext
from app.preproc.utils.ids import sha256_file
from app.core.metrics import INGEST_JOBS_TOTAL, INGEST_FILES_SIZE_BYTES

from app.preproc.stores.postgres_repo import PostgresRepo, PostgresRepoConfig
from app.workers.worker_main import celery_app  # celery client


router = APIRouter()
logger = logging.getLogger(__name__)


def _pg() -> PostgresRepo:
    # Use pydantic settings which handles .env and defaults
    db_url = str(settings.DATABASE_URL)
    try:
        return PostgresRepo(PostgresRepoConfig(conninfo=db_url, use_pool=True))
    except TypeError:
        return PostgresRepo(PostgresRepoConfig(conninfo=db_url))


from app.core.filename import sanitize_filename

def _raise_err(status: int, code: str, msg: str, **kwargs):
    detail = {"code": code, "message": msg}
    detail.update(kwargs)
    logger.error(f"Ingest Error {status}: {detail}")
    raise HTTPException(status_code=status, detail=detail)

def _create_ingest_job(
    pg: PostgresRepo,
    ctx: TrustedContext,
    doc_type: DocType,
    scope: Scope,
    security_level: SecurityLevel,
    domain: str | None,
    source_uri: str,
    mime_type: str,
    checksum: str,
    title: str,
) -> UUID:
    """
    Standardized Job Creation with Strict Context Bridge.
    """
    job_id = uuid4()
    
    # SSoT Bridge: JSONB Payload for Worker
    meta_payload = {
        "tenant_id": ctx.tenant_id,
        "department_id": ctx.department_id,
        "geo_code": ctx.geo_code,
        "doc_type": doc_type.value,
        "scope": scope.value,
        "security_level": security_level.value,
        "domain": domain,
        # We can add more context like uploaded_by here if available
    }

    try:
        pg.create_job(
            job_id=job_id,
            job_type="ingest",
            scope=scope.value,
            commune_id=ctx.geo_code, # Legacy mapping
            source_uri=source_uri,
            mime_type=mime_type,
            checksum=checksum,
            title=title,
            pipeline_version="v2",
            doc_category_hint=doc_type.value, # Legacy mapping
            meta=meta_payload, # <-- NEW JSONB BRIDGE
        )
    except TypeError:
        # Fallback for old PostgresRepo (no meta arg) - Should be removed after migration
        logger.warning("PostgresRepo.create_job missing 'meta'. Context lost.")
        pg.create_job(
            job_id=job_id,
            job_type="ingest",
            scope=scope.value,
            commune_id=ctx.geo_code,
            source_uri=source_uri,
            mime_type=mime_type,
            checksum=checksum,
            title=title,
            pipeline_version="v2",
            doc_category_hint=doc_type.value,
        )
    
    return job_id

@router.post("/ingest", status_code=202)
async def ingest_document(
    file: UploadFile = File(...),
    doc_type: DocType = Form(...),
    scope: Scope = Form(...),
    security_level: int = Form(...),
    domain: str = Form(None),
    
    # Trusted Context (Required)
    ctx: TrustedContext = Depends(get_trusted_context),
):
    """
    Ingest a document with strict security and policy checks.
    Fail-Closed:
    - Missing tenant_id -> 403 (via get_trusted_context)
    - Scope.INTERNAL missing department_id -> 403
    """
    
    # 1. Policy Validations (Fail-Closed)
    if scope == Scope.INTERNAL and not ctx.department_id:
        _raise_err(
            403,
            IngestionError.ERR_MISSING_DEPARTMENT_CONTEXT,
            "INTERNAL scope requires department_id in context"
        )
        
    MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50MB
    ALLOWED_MIMES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    }
    
    # MIME Check
    if file.content_type not in ALLOWED_MIMES:
        _raise_err(
            415,
            IngestionError.ERR_UNSUPPORTED_FILE_TYPE,
            f"Unsupported media type: {file.content_type}. Allowed: {sorted(list(ALLOWED_MIMES))}"
        )

    # Size Check
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    
    if file_size > MAX_SIZE_BYTES:
        _raise_err(
            413,
            IngestionError.ERR_FILE_TOO_LARGE,
            f"File too large ({file_size / 1024 / 1024:.2f}MB). Max: 50MB."
        )

    # Metric: File Size
    INGEST_FILES_SIZE_BYTES.labels(mime_type=file.content_type).observe(file_size)

    # TODO: Check SecurityLevel threshold if needed, for now just ensure provided
    try:
        # Pydantic/FastAPI handles basic int conversion, but here we validate range/enum
        # We allow passing raw int, but conceptually it maps to SecurityLevel
        sec_lvl = SecurityLevel(security_level)
    except ValueError:
        _raise_err(
            400,
            IngestionError.ERR_INVALID_SECURITY_LEVEL,
            "Invalid security_level",
            got=security_level
        )

    # Policy: RESTRICTED scope requires higher security clearance (Level >= 3)
    MIN_RESTRICTED_LEVEL = 3
    if scope == Scope.RESTRICTED and sec_lvl.value < MIN_RESTRICTED_LEVEL:
        _raise_err(
            403,
            IngestionError.ERR_SCOPE_SECURITY_VIOLATION,
            f"RESTRICTED scope requires security_level >= {MIN_RESTRICTED_LEVEL}",
            min_level=MIN_RESTRICTED_LEVEL, 
            got=sec_lvl.value
        )

    # 2. Save to Temp (Quarantine zone eventually)
    safe_name = sanitize_filename(file.filename or "upload.bin")
    
    # Storage isolation by tenant eventually? For now use commune/geo or default structure
    # We use tenant_id/geo_code structure if possible
    storage_root = Path(getattr(settings, "STORAGE_PATH", os.getenv("STORAGE_PATH", "./storage")))
    
    # Use geo_code or global
    # Fix: Ensure strict string types for paths
    tenant_id_str = str(ctx.tenant_id)
    geo_code_str = str(ctx.geo_code) if ctx.geo_code else None
    
    location_key = geo_code_str or "global"
    base_dir = storage_root / tenant_id_str / location_key
    base_dir.mkdir(parents=True, exist_ok=True)

    temp_path = base_dir / f"{uuid4().hex}_{safe_name}"
    try:
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    finally:
        file.file.close()

    # 3. Checksum
    checksum = sha256_file(str(temp_path))

    # 4. Content Addressing
    final_dir = base_dir / checksum
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / safe_name

    if not final_path.exists():
        temp_path.replace(final_path)
    else:
        try:
            temp_path.unlink()
        except Exception:
            pass

    # 6. Create Job (Postgres) - Always run (Idempotent Job Submission)
    # Refactored to _create_ingest_job
    try:
        pg = _pg()
        job_id = _create_ingest_job(
            pg=pg,
            ctx=ctx,
            doc_type=doc_type,
            scope=scope,
            security_level=sec_lvl,
            domain=domain,
            source_uri=str(final_path),
            mime_type=file.content_type or "application/octet-stream",
            checksum=checksum,
            title=safe_name,
        )
    except Exception as e:
        logger.exception("Failed to create job")
        # Metric: Job Failed (Submission)
        INGEST_JOBS_TOTAL.labels(status="failed_submit", doc_type=doc_type.value, scope=scope.value).inc()
        raise HTTPException(status_code=500, detail=f"Failed to create job: {e}")

    # 6. Enqueue
    try:
        celery_app.send_task("ingestion.run_job", args=[str(job_id)])
    except Exception as e:
        logger.exception("Failed to enqueue job")
        # Metric: Job Failed (Enqueue)
        INGEST_JOBS_TOTAL.labels(status="failed_enqueue", doc_type=doc_type.value, scope=scope.value).inc()
        # Should we fail the request? Yes, return 503 so client retries later.
        _raise_err(
            503, 
            IngestionError.ERR_ENQUEUE_FAILED,
            f"Failed to enqueue job: {e}"
        )
    
    # Metric: Job Queued
    INGEST_JOBS_TOTAL.labels(status="queued", doc_type=doc_type.value, scope=scope.value).inc()

    return {
        "status": "accepted",
        "job_id": str(job_id),
        "checksum": checksum,
        "filename": safe_name,
        "message": "Job queued."
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    pg = _pg()
    try:
        job = pg.get_job(UUID(job_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job_id")

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.get("source_uri"):
        job["source_uri"] = Path(str(job["source_uri"])).name
    return job


@router.post("/docs/{doc_id}/reindex", status_code=202)
def reindex_doc(doc_id: str, ctx: TrustedContext = Depends(get_trusted_context)):
    """
    Reindex requires ownership check.
    """
    pg = _pg()
    try:
        doc_uuid = UUID(doc_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid doc_id")

    if not hasattr(pg, "get_document_for_tenant"):
        raise HTTPException(status_code=500, detail="PostgresRepo missing get_document_for_tenant(doc_id, tenant_id)")

    doc = pg.get_document_for_tenant(doc_uuid, str(ctx.tenant_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found (security)")

    job_id = uuid4()
    meta_payload = {
        "tenant_id": str(ctx.tenant_id),
        "scope": doc["scope"],
        "doc_type": doc.get("doc_type") or doc.get("doc_category") or "other",
        "security_level": doc.get("security_level"),
        "department_id": doc.get("department_id"),
        "geo_code": doc.get("geo_code") or doc.get("commune_id"),
        "domain": doc.get("domain"),
    }
    pg.create_job(
        job_id=job_id,
        job_type="reindex",
        scope=doc["scope"],
        commune_id=doc.get("commune_id"),
        source_uri=doc["source_uri"],
        mime_type=doc["mime_type"],
        checksum=doc["checksum"],
        title=doc.get("title") or "reindex",
        pipeline_version=doc.get("pipeline_version") or "v1",
        doc_category_hint=None,
        meta=meta_payload,
    )
    pg.update_job(UUID(str(job_id)), doc_id=doc_uuid)
    celery_app.send_task("ingestion.run_job", args=[str(job_id)])
    return {"status": "accepted", "job_id": str(job_id), "doc_id": doc_id}


@router.delete("/docs/{doc_id}", status_code=202)
def delete_doc(doc_id: str, ctx: TrustedContext = Depends(get_trusted_context)):
    pg = _pg()
    try:
        doc_uuid = UUID(doc_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid doc_id")

    if not hasattr(pg, "get_document_for_tenant"):
        raise HTTPException(status_code=500, detail="PostgresRepo missing get_document_for_tenant(doc_id, tenant_id)")

    doc = pg.get_document_for_tenant(doc_uuid, str(ctx.tenant_id), include_deleted=True)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found (security)")

    if bool(doc.get("is_deleted")):
        return {
            "status": "accepted",
            "doc_id": doc_id,
            "already_deleted": True,
            "message": "Document already deleted",
        }

    job_id = uuid4()
    meta_payload = {
        "tenant_id": str(ctx.tenant_id),
        "scope": doc["scope"],
        "doc_type": doc.get("doc_type") or doc.get("doc_category") or "other",
        "security_level": doc.get("security_level"),
        "department_id": doc.get("department_id"),
        "geo_code": doc.get("geo_code") or doc.get("commune_id"),
        "domain": doc.get("domain"),
    }

    pg.create_job(
        job_id=job_id,
        job_type="delete",
        scope=doc["scope"],
        commune_id=doc.get("commune_id"),
        source_uri=doc["source_uri"],
        mime_type=doc["mime_type"],
        checksum=doc["checksum"],
        title=doc.get("title") or "(delete)",
        pipeline_version=doc.get("pipeline_version") or "v1",
        doc_category_hint=None,
        meta=meta_payload,
    )
    pg.update_job(UUID(str(job_id)), doc_id=doc_uuid)

    celery_app.send_task("ingestion.run_job", args=[str(job_id)])
    return {"status": "accepted", "job_id": str(job_id), "doc_id": doc_id}
