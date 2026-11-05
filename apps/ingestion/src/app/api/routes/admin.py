from __future__ import annotations

import logging
from uuid import UUID, uuid4
from typing import List, Dict, Any, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth_context import TrustedContext, get_trusted_context, UserRole
from app.core.canonical_models import IngestionProfile
from app.preproc.stores.postgres_repo import PostgresRepo, PostgresRepoConfig
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

def _pg() -> PostgresRepo:
    # Use pydantic settings which handles .env and defaults
    db_url = str(settings.DATABASE_URL)
    try:
        return PostgresRepo(PostgresRepoConfig(conninfo=db_url, use_pool=True))
    except TypeError:
        return PostgresRepo(PostgresRepoConfig(conninfo=db_url))

def _ensure_admin_access(ctx: TrustedContext):
    """
    Enforce Role-Based Access Control (RBAC).
    Only ADMIN and CHAIRMAN (and maybe OFFICER) can manage profiles.
    For now/Cockpit: ADMIN and OFFICER are allowed. CITIZEN is denied.
    """
    allowed = {UserRole.ADMIN, UserRole.OFFICER, UserRole.CHAIRMAN}
    if ctx.user_role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. Required roles: {allowed}. Got: {ctx.user_role}"
        )

@router.post("/profiles", status_code=status.HTTP_201_CREATED, response_model=IngestionProfile)
def create_profile(
    profile: IngestionProfile,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    """
    Create a new ingestion profile.
    Idempotent if profile_id is reused (but normally client sends new UUID).
    Name must be unique per tenant.
    """
    _ensure_admin_access(ctx)
    
    # Enforce tenant isolation logic
    if profile.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=400, detail="Profile tenant_id must match context tenant_id")

    pg = _pg()
    try:
        pg.create_profile(
            profile_id=profile.profile_id,
            tenant_id=profile.tenant_id,
            name=profile.name,
            description=profile.description,
            config=profile.config.model_dump(),
        )
    except Exception as e:
        logger.exception(f"Failed to create profile {profile.profile_id}")
        # Detect unique violation
        if "unique constraint" in str(e).lower():
            raise HTTPException(status_code=409, detail="Profile name already exists for this tenant.")
        raise HTTPException(status_code=500, detail=str(e))
    
    return profile

@router.get("/profiles", response_model=List[IngestionProfile])
def list_profiles(
    ctx: TrustedContext = Depends(get_trusted_context)
):
    _ensure_admin_access(ctx)
    pg = _pg()
    rows = pg.list_profiles(tenant_id=ctx.tenant_id)
    return [IngestionProfile(**r) for r in rows]

@router.get("/profiles/{profile_id}", response_model=IngestionProfile)
def get_profile(
    profile_id: UUID,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    _ensure_admin_access(ctx)
    pg = _pg()
    row = pg.get_profile(profile_id)
    
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    profile = IngestionProfile(**row)
    
    # Enforce tenant boundary
    if profile.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="Profile not found (security)")
        
    return profile

@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    profile_id: UUID,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    _ensure_admin_access(ctx)
    pg = _pg()
    
    # Check existence and ownership first
    row = pg.get_profile(profile_id)
    if not row:
        # Idempotent success
        return
        
    profile = IngestionProfile(**row)
    if profile.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="Profile not found (security)")
        
    pg.delete_profile(profile_id)


# =========================
# Phase 2: Presigned Upload & Workflow
# =========================

from pydantic import BaseModel, Field
from app.core.s3_storage import get_s3_signer
from app.api.endpoints import _create_ingest_job # Reuse logic if needed, but we used custom logic
# Actually, creating jobs via admin has different logic (profile-based)
# We need to implement the detailed logic here.

class PresignRequest(BaseModel):
    profile_id: UUID
    filename: str
    mime_type: str
    size_bytes: int

class PresignResponse(BaseModel):
    upload_url: str
    object_key: str
    expires_in: int

@router.post("/upload/presign", response_model=PresignResponse)
def presign_upload(
    req: PresignRequest,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    """
    Generate a presigned PUT URL for direct-to-S3 upload.
    Validates against Profile constraints (e.g. max size, mime type).
    """
    _ensure_admin_access(ctx)
    pg = _pg()
    
    # 1. Fetch Profile
    row = pg.get_profile(req.profile_id)
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = IngestionProfile(**row)
    
    # 2. RBAC/Tenant Check
    if profile.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=403, detail="Profile access denied")
        
    # 3. Validation (Future: Add allowed_mimes to Profile Config)
    # For now, we trust Admin/Officer but enforce basic sanity.
    MAX_SIZE = 100 * 1024 * 1024 # 100MB hard cap for now
    if req.size_bytes > MAX_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_SIZE} bytes")
        
    # 4. Generate Key
    # Format: raw/{tenant_id}/{date}/{uuid}_{filename}
    from datetime import datetime
    date_str = datetime.utcnow().strftime("%Y/%m/%d")
    safe_name = req.filename.replace(" ", "_").replace("/", "-") # Simple sanitize
    object_key = f"raw/{ctx.tenant_id}/{date_str}/{uuid4().hex}_{safe_name}"
    
    # 5. Sign
    signer = get_s3_signer()
    url = signer.generate_presigned_put(object_key, expires_in=3600, content_type=req.mime_type)
    
    return PresignResponse(
        upload_url=url,
        object_key=object_key,
        expires_in=3600
    )


class JobFile(BaseModel):
    object_key: str
    original_name: str
    mime_type: str
    size_bytes: int
    checksum: str # Client should calculate sha256 of local file before upload if possible, or we compute async? 
                 # Trusting client checksum for now implies we use it for dedupe. 
                 # Ideally valid pipeline re-checks it.

class JobSubmissionRequest(BaseModel):
    profile_id: UUID
    files: List[JobFile]
    note: str | None = None

class JobSubmissionResponse(BaseModel):
    jobs_created: int
    status: str # queued | pending_approval

@router.get("/jobs", response_model=List[Dict[str, Any]])
def list_jobs(
    limit: int = 100,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    _ensure_admin_access(ctx)
    pg = _pg()
    return pg.list_jobs(ctx.tenant_id, limit)


@router.get("/documents", response_model=List[Dict[str, Any]])
def list_documents(
    limit: int = Query(100, ge=1, le=500),
    scope: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    is_deleted: Optional[bool] = Query(None),
    ctx: TrustedContext = Depends(get_trusted_context),
):
    _ensure_admin_access(ctx)
    pg = _pg()
    if not hasattr(pg, "list_documents_for_tenant"):
        raise HTTPException(status_code=500, detail="PostgresRepo missing list_documents_for_tenant")
    return pg.list_documents_for_tenant(
        str(ctx.tenant_id),
        scope=scope,
        doc_type=doc_type,
        is_deleted=is_deleted,
        limit=limit,
    )

@router.post("/jobs", response_model=JobSubmissionResponse)
def submit_jobs(
    req: JobSubmissionRequest,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    """
    Submit batch ingestion jobs using proper Profile.
    """
    _ensure_admin_access(ctx)
    pg = _pg()
    
    # 1. Profile
    row = pg.get_profile(req.profile_id)
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = IngestionProfile(**row)
    
    if profile.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")
        
    # 2. Determine Status (Quarantine Logic)
    # If profile requires approval, set to pending_approval.
    # Currently config doesn't have explicit 'requires_approval' field yet in Pydantic model?
    # Checking IngestionProfileConfig: auto_approve: bool = False.
    # Logic: If auto_approve=True -> queued. Else -> pending_approval?
    # Actually usually 'auto_approve=True' means skip quarantine.
    # Let's assume default is 'pending_approval' if it's sensitive, or 'queued' if 'auto_approve' is set.
    # For now, let's treat everyone as 'queued' unless profile.config.auto_approve is False AND it's a sensitive doc?
    # Simple rule: If verified Admin/Officer, we default to Queued?
    # User Request: "If profile says requires_approval, job pauses."
    # Let's map `config.auto_approve` to "Is Approval NOT Required".
    requires_approval = not profile.config.auto_approve
    status_val = "pending_approval" if requires_approval else "queued"
    
    # Officers might trigger approval, Admins might bypass? 
    # Let's enforce Profile rule strictly for now.
    
    # 3. Create Jobs
    count = 0
    from app.core.taxonomy import Scope
    
    # Construct Meta Snapshot (Immutable)
    meta_snapshot = {
        "tenant_id": ctx.tenant_id,
        "department_id": ctx.department_id, # Or override from profile
        "geo_code": ctx.geo_code,
        "doc_type": profile.config.doc_type or "other",
        "scope": profile.config.scope or Scope.INTERNAL,
        "security_level": profile.config.security_level or 1,
        "profile_name": profile.name,
        "submitted_by": str(ctx.user_role), # Audit
        "note": req.note
    }
    
    for f in req.files:
        job_id = uuid4()
        # Create Job
        pg.create_job_with_profile(
            job_id=job_id,
            job_type="ingest",
            source_uri=f.object_key, # S3 Key
            mime_type=f.mime_type,
            checksum=f.checksum,
            title=f.original_name,
            profile_id=profile.profile_id,
            status=status_val,
            meta=meta_snapshot
        )
        count += 1
        
        # Trigger Worker only if Queued
        if status_val == "queued":
            from app.workers.worker_main import celery_app
            celery_app.send_task("ingestion.run_job", args=[str(job_id)])

    return JobSubmissionResponse(
        jobs_created=count,
        status=status_val
    )


@router.post("/jobs/{job_id}/approve", status_code=status.HTTP_200_OK)
def approve_job(
    job_id: UUID,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    """
    Approve a pending job. Triggers enrichment/ingestion.
    """
    _ensure_admin_access(ctx)
    pg = _pg()
    
    job = pg.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job["status"] != "pending_approval":
         # Idempotent: if already running/queued, just return generic success or info
         return {"status": job["status"], "message": "Job already processed or not pending"}
         
    # Update Status
    pg.update_job_approval(
        job_id=job_id,
        status="queued",
        approved_by=str(ctx.user_role), # Should be user ID in real system
        approver_role=str(ctx.user_role)
    )
    
    # Fire Worker
    from app.workers.worker_main import celery_app
    celery_app.send_task("ingestion.run_job", args=[str(job_id)])
    
    
    return {"status": "queued", "message": "Job approved and queued"}

# =========================
# Phase P1: Registered Sources
# =========================

class SourceRequest(BaseModel):
    server_id: str
    path: str
    profile_id: UUID

class SourceResponse(BaseModel):
    id: UUID
    server_id: str
    path: str
    profile_id: UUID
    profile_name: str | None = None
    enabled: bool
    last_seen_at: datetime | None = None

@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(
    req: SourceRequest,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    _ensure_admin_access(ctx)
    pg = _pg()
    
    # Check profile
    row = pg.get_profile(req.profile_id)
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    s_id = uuid4()
    pg.create_source(
        id=s_id,
        tenant_id=ctx.tenant_id,
        server_id=req.server_id,
        path=req.path,
        profile_id=req.profile_id
    )
    
    # Return simulated response (or fetch fresh)
    return SourceResponse(
        id=s_id,
        server_id=req.server_id,
        path=req.path,
        profile_id=req.profile_id,
        profile_name=row['name'],
        enabled=True,
        last_seen_at=None
    )

@router.get("/sources", response_model=List[SourceResponse])
def list_sources(
    ctx: TrustedContext = Depends(get_trusted_context)
):
    _ensure_admin_access(ctx)
    pg = _pg()
    rows = pg.list_sources(ctx.tenant_id)
    return [SourceResponse(**r) for r in rows]

@router.delete("/sources/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    id: UUID,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    _ensure_admin_access(ctx)
    pg = _pg()
    # Check tenant ownership
    s = pg.get_source(id)
    if s and s['tenant_id'] == ctx.tenant_id:
        pg.delete_source(id)

@router.patch("/sources/{id}/toggle", status_code=status.HTTP_200_OK)
def toggle_source(
    id: UUID,
    enabled: bool,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    _ensure_admin_access(ctx)
    pg = _pg()
    s = pg.get_source(id)
    if not s or s['tenant_id'] != ctx.tenant_id:
         raise HTTPException(status_code=404, detail="Source not found")
         
    pg.toggle_source(id, enabled)
    return {"message": f"Source enabled={enabled}"}

@router.get("/sources/config")
def get_source_config(
    server_id: str,
    # This endpoint is polled by Watcher (System Agent).
    # Watcher authenticate via API Key or just be internal?
    # For now, we assume Watcher has an Admin Key or runs in TrustedContext?
    # Context usually comes from headers. Watcher should send X-GOVAI-TENANT-ID / ROLE=admin
    ctx: TrustedContext = Depends(get_trusted_context) 
):
    """
    Called by Watcher to get list of paths to watch.
    """
    # Verify role (Admin/System)
    if ctx.user_role not in (UserRole.ADMIN, UserRole.OFFICER):
         # Or maybe specific 'SYSTEM' role? For Pilot, Admin is fine.
         raise HTTPException(status_code=403, detail="Poll access denied")
         
    pg = _pg()
    # We ignore context tenant for server config? 
    # NO. Watcher belongs to a tenant? Or is Watcher Cross-Tenant?
    # Architecture: 1 Watcher per Tenant? Or 1 Watcher per File Server?
    # If Watcher is per Server, that Server might serve multiple Tenants?
    # Prompt says: "Return list ... where server_id matches".
    # And "watcher polls /config?server_id=...".
    # And Watcher needs to know Profile ID.
    
    # If Watcher sends tenant_id in header, we only return sources for that tenant.
    # This implies 1 Watcher process = 1 Tenant context.
    # If we want multi-tenant watcher, it needs super-admin access.
    # Pilot assumption: Single Tenant deployment.
    
    binds = pg.get_server_config(server_id)
    # Update heartbeats (optional, side effect in GET is acceptable for heartbeat)
    for b in binds:
        pg.update_source_heartbeat(b['id'])
        
    return {
        "server_id": server_id,
        "bindings": [
            {"path": b['path'], "profile_id": b['profile_id']} for b in binds
        ]
    }

# =========================
# Phase P2: Ops Maturity
# =========================

@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_200_OK)
def retry_job(
    job_id: UUID,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    _ensure_admin_access(ctx)
    pg = _pg()
    
    job = pg.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job['status'] != 'failed':
         # Allow force retry if user really wants? 
         # For now restrict to failed to be safe.
         raise HTTPException(status_code=400, detail="Only failed jobs can be retried")
    
    pg.reset_job(job_id)
    
    # Audit
    pg.insert_audit(
        tenant_id=ctx.tenant_id,
        user_id=str(ctx.user_role), # Should be email ideally
        action="retry_job",
        resource_id=str(job_id),
        details={"original_status": job['status'], "error": job.get('error')}
    )
    
    # Fire Worker
    from app.workers.worker_main import celery_app
    celery_app.send_task("ingestion.run_job", args=[str(job_id)])
    
    return {"status": "queued", "message": "Job queued for retry"}

@router.get("/audit-logs", response_model=List[Dict[str, Any]])
def get_audit_logs(
    limit: int = 100,
    ctx: TrustedContext = Depends(get_trusted_context)
):
    _ensure_admin_access(ctx)
    pg = _pg()
    return pg.list_audit_logs(ctx.tenant_id, limit)

@router.get("/metrics", response_model=Dict[str, Any])
def get_system_metrics(
    ctx: TrustedContext = Depends(get_trusted_context)
):
    # Visible to all internal staff?
    # Ensure role check
    _ensure_admin_access(ctx)
    pg = _pg()
    return pg.get_dashboard_metrics(ctx.tenant_id)
