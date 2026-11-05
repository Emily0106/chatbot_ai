# apps/backend/src/app/api/routes/promotion_jobs.py
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_sql import get_async_db

from app.core.promotion.promotion import PromotionService, PromotionJob

router = APIRouter(tags=["promotion_jobs"])

@router.get("/promotion_jobs/{job_id}", response_model=PromotionJob)
async def get_promotion_job(
    job_id: uuid.UUID,
    tenant_id: str, # Assume passed via query or header for now, ideally from Auth
    db: AsyncSession = Depends(get_async_db)
):
    job = await PromotionService.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # Enforce Tenant Isolation
    if job.tenant_id != tenant_id:
        # Return 404 to avoid leaking existence
        raise HTTPException(status_code=404, detail="Job not found")
        
    return job
