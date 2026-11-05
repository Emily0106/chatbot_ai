# apps/backend/src/app/core/ops/retention.py
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.audit.audit import AuditService

logger = logging.getLogger(__name__)

class RetentionService:
    @classmethod
    async def cleanup_jobs(cls, db: AsyncSession, retention_days_done: int = 90, retention_days_failed: int = 30):
        """
        Delete old promotion jobs and log audit events.
        """
        cutoff_done = datetime.utcnow() - timedelta(days=retention_days_done)
        cutoff_failed = datetime.utcnow() - timedelta(days=retention_days_failed)
        
        # We can do a bulk delete, but we might want to log which IDs were deleted?
        # For simplicity, bulk delete and log count.
        
        # 1. Delete DONE
        stmt_done = text("""
            WITH deleted AS (
                DELETE FROM promotion_jobs 
                WHERE status = 'DONE' AND updated_at < :cutoff
                RETURNING job_id, tenant_id
            )
            SELECT count(*) as count, tenant_id FROM deleted GROUP BY tenant_id
        """)
        
        result_done = await db.execute(stmt_done, {"cutoff": cutoff_done})
        # Result is rows of (count, tenant_id)
        
        for row in result_done:
            count = row.count
            tenant_id = row.tenant_id
            await AuditService.log_event(
                db, tenant_id, "RETENTION_CLEANUP", 
                actor_type="system",
                metadata={"deleted_count": count, "status": "DONE", "retention_days": retention_days_done}
            )
            logger.info(f"Cleaned up {count} DONE jobs for tenant {tenant_id}")

        # 2. Delete FAILED
        stmt_failed = text("""
            WITH deleted AS (
                DELETE FROM promotion_jobs 
                WHERE status = 'FAILED' AND updated_at < :cutoff
                RETURNING job_id, tenant_id
            )
            SELECT count(*) as count, tenant_id FROM deleted GROUP BY tenant_id
        """)
        
        result_failed = await db.execute(stmt_failed, {"cutoff": cutoff_failed})
        
        for row in result_failed:
            count = row.count
            tenant_id = row.tenant_id
            await AuditService.log_event(
                db, tenant_id, "RETENTION_CLEANUP", 
                actor_type="system",
                metadata={"deleted_count": count, "status": "FAILED", "retention_days": retention_days_failed}
            )
            logger.info(f"Cleaned up {count} FAILED jobs for tenant {tenant_id}")
            
        await db.commit()
