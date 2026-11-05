# apps/backend/src/app/api/routes/ops.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, func
from typing import List, Optional, Dict, Any
from app.core.db import get_async_db
from app.core.promotion.promotion import PromotionJobORM, PromotionStatus
from app.core.ops.retention import RetentionService
from app.core.audit.audit import AuditService
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/health", response_model=Dict[str, Any])
async def get_system_health(db: AsyncSession = Depends(get_async_db)):
    """
    Get system health summary.
    """
    # 1. Job Counts
    stmt = select(PromotionJobORM.status, func.count(PromotionJobORM.job_id)).group_by(PromotionJobORM.status)
    result = await db.execute(stmt)
    job_counts = {row.status.value: row.count for row in result}
    
    # 2. Failure Rate (Last 24h)
    # Simplified: just total failure count for now
    failure_count = job_counts.get(PromotionStatus.FAILED.value, 0)
    total_count = sum(job_counts.values())
    failure_rate = (failure_count / total_count) if total_count > 0 else 0.0
    
    # 3. Redis Status (Mocked or Real check)
    redis_status = "UP" # Assume UP if app is running, or check ping
    
    return {
        "status": "healthy",
        "jobs": job_counts,
        "failure_rate": round(failure_rate, 4),
        "redis": redis_status
    }

@router.get("/jobs", response_model=List[Dict[str, Any]])
async def list_jobs(
    status: Optional[PromotionStatus] = None,
    tenant_id: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_db)
):
    """
    List promotion jobs with filtering.
    """
    stmt = select(PromotionJobORM).limit(limit).order_by(PromotionJobORM.created_at.desc())
    
    if status:
        stmt = stmt.where(PromotionJobORM.status == status)
    if tenant_id:
        stmt = stmt.where(PromotionJobORM.tenant_id == tenant_id)
        
    result = await db.execute(stmt)
    jobs = result.scalars().all()
    
    return [
        {
            "job_id": str(job.job_id),
            "tenant_id": job.tenant_id,
            "status": job.status,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "attempt_count": job.attempt_count,
            "last_error": job.last_error_message
        }
        for job in jobs
    ]

@router.post("/cleanup", response_model=Dict[str, str])
async def trigger_cleanup(
    retention_days_done: int = 90,
    retention_days_failed: int = 30,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Trigger manual retention cleanup.
    """
    await RetentionService.cleanup_jobs(db, retention_days_done, retention_days_failed)
    return {"status": "cleanup_initiated"}
