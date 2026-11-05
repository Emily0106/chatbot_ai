# apps/backend/src/app/core/promotion/worker.py
import asyncio
import logging
import uuid
import os
import httpx
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.db import get_async_db_session_context # Assuming context manager or similar
# If not, we need to manually create session.
# Let's use the generator pattern manually.
from app.core.db_sql import get_async_db # This is a dependency, returns generator.


from app.core.promotion.promotion import PromotionService, PromotionStatus

logger = logging.getLogger(__name__)

from app.core.promotion.telemetry import StructuredLogger, measure_duration, inc_job_counter, inc_failure_counter

async def process_promotion_job(job_id: uuid.UUID, file_path: str, doc_type: str):
    """
    Background task to process promotion.
    """
    # Initial logger without tenant_id (will update later)
    log = StructuredLogger(str(job_id), "unknown")
    log.info("Starting promotion job")
    
    try:
        from app.core.db import async_session_factory
    except ImportError:
        log.error("Could not import async_session_factory")
        return

    async with async_session_factory() as db:
        # 1. Update to RUNNING
        await PromotionService.update_status(db, job_id, PromotionStatus.RUNNING, increment_attempt=True)
        
        # 2. Get Job Details
        job = await PromotionService.get_job(db, job_id)
        if not job:
            log.error("Job not found during processing")
            return
            
        # Update logger with tenant_id
        log = StructuredLogger(str(job_id), job.tenant_id)
        log.info(f"Processing promotion for tenant {job.tenant_id}")

    # 3. Call Ingestion Service (Retry Loop)
    ingest_base = settings.INGESTION_BASE_URL
    ingest_url = f"{ingest_base}/api/v1/ingest"
    
    retries = 5
    backoff = [5, 15, 45, 120, 300] # seconds
    
    success = False
    error_msg = ""
    kb_doc_id = None
    
    with measure_duration():
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    with open(file_path, "rb") as f:
                        files = {"file": (job.filename or "doc.txt", f, "text/plain")}
                        form_data = {
                            "scope": "local_gov",
                            "commune_id": job.tenant_id,
                            "doc_category_hint": doc_type,
                            "job_id": str(job_id)
                        }
                        
                        headers = {
                            "X-Idempotency-Key": f"{job.tenant_id}-{job.content_hash}"
                        }
                        
                        resp = await client.post(ingest_url, files=files, data=form_data, headers=headers)
                        resp.raise_for_status()
                        
                        data = resp.json()
                        kb_doc_id = data.get("doc_id") or data.get("id") or "unknown"
                        success = True
                        break
                        
            except Exception as e:
                error_msg = str(e)
                log.warning(f"Attempt {attempt+1} failed: {e}", attempt=attempt+1)
                if attempt < retries - 1:
                    wait = backoff[attempt]
                    await asyncio.sleep(wait)
    
    # 4. Update Final Status
    async with async_session_factory() as db:
        from app.core.audit.audit import AuditService
        
        if success:
            await PromotionService.update_status(
                db, 
                job_id, 
                PromotionStatus.DONE, 
                kb_doc_id=kb_doc_id
            )
            await AuditService.log_status_change(db, job.tenant_id, str(job_id), "RUNNING", "DONE")
            log.info("Job completed successfully", kb_doc_id=kb_doc_id)
            inc_job_counter("DONE", job.tenant_id)
        else:
            await PromotionService.update_status(
                db, 
                job_id, 
                PromotionStatus.FAILED, 
                error=error_msg
            )
            await AuditService.log_status_change(db, job.tenant_id, str(job_id), "RUNNING", "FAILED", error=error_msg)
            log.error(f"Job failed after retries: {error_msg}")
            inc_job_counter("FAILED", job.tenant_id)
            inc_failure_counter("INGESTION_ERROR")
            
        await db.commit()
            
    # Cleanup temp file
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
