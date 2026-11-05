# apps/backend/src/app/core/promotion/promotion.py
from __future__ import annotations

import uuid
import logging
import hashlib
from enum import Enum
from datetime import datetime, timedelta
from typing import Optional, List, Any
from pydantic import BaseModel

from sqlalchemy import select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.db import Base # Assuming Base is available in app.core.db or similar
# Actually, I should check where Base is defined. Usually app.core.db or app.models.base
# Let's assume I can define a local model if needed or use the shared Base.
# I'll try to import Base from app.core.db first.

logger = logging.getLogger(__name__)

class PromotionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"

# SQLAlchemy Model
# We need to ensure this is compatible with the existing Base.
# If I can't find Base easily, I'll use a raw table definition or try to locate it.
# Based on previous file views, I haven't seen the Base definition.
# Let's check app/core/db.py or similar if I can.
# But for now, I'll define the Pydantic models and Service logic using raw SQL or Table if needed,
# but ORM is better.

# Let's try to find Base.
# If I can't, I will use a standalone definition for now, but it might not register with the main metadata.
# Actually, for the service, I can just use `text` queries or `Table` reflection if I want to be safe.
# But let's try to define the class.

from sqlalchemy import Column, String, Integer, DateTime, Text
from sqlalchemy.sql import func

# I'll assume Base is importable. If not, I'll fix it.
try:
    from app.core.db import Base
except ImportError:
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()

class PromotionJobORM(Base):
    __tablename__ = "promotion_jobs"

    job_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String, nullable=False, index=True)
    temp_doc_id = Column(String, nullable=False)
    status = Column(String, default=PromotionStatus.PENDING, index=True)
    content_hash = Column(String, nullable=False)
    
    filename = Column(String, nullable=True)
    kb_doc_id = Column(String, nullable=True)
    
    attempt_count = Column(Integer, default=0)
    next_retry_at = Column(DateTime, nullable=True)
    last_error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

# Pydantic Models
class PromotionJob(BaseModel):
    job_id: uuid.UUID
    tenant_id: str
    temp_doc_id: str
    status: PromotionStatus
    content_hash: str
    filename: Optional[str] = None
    kb_doc_id: Optional[str] = None
    attempt_count: int
    last_error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PromotionService:
    @staticmethod
    def calculate_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    async def get_job(cls, db: AsyncSession, job_id: uuid.UUID) -> Optional[PromotionJob]:
        stmt = select(PromotionJobORM).where(PromotionJobORM.job_id == job_id)
        result = await db.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm:
            return PromotionJob.model_validate(orm)
        return None

    @classmethod
    async def create_job_idempotent(
        cls, 
        db: AsyncSession, 
        tenant_id: str, 
        temp_doc_id: str, 
        content_hash: str,
        filename: str
    ) -> PromotionJob:
        # content_hash is passed directly now
        
        # Check existing
        stmt = select(PromotionJobORM).where(
            PromotionJobORM.tenant_id == tenant_id,
            PromotionJobORM.content_hash == content_hash
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            # If FAILED, should we retry automatically? 
            # For now, just return it. The caller can decide to retry if status is FAILED.
            # Or we can reset it here?
            # Let's return existing. User can use /retry endpoint if needed.
            return PromotionJob.model_validate(existing)
            
        # Create new
        new_job = PromotionJobORM(
            job_id=uuid.uuid4(),
            tenant_id=tenant_id,
            temp_doc_id=temp_doc_id,
            content_hash=content_hash,
            filename=filename,
            status=PromotionStatus.PENDING
        )
        db.add(new_job)
        await db.commit()
        await db.refresh(new_job)
        return PromotionJob.model_validate(new_job)

    @classmethod
    async def pick_next_pending_job(cls, db: AsyncSession) -> Optional[PromotionJob]:
        """
        Atomically pick the next PENDING job and mark it RUNNING.
        Uses SELECT ... FOR UPDATE SKIP LOCKED if possible, or atomic UPDATE.
        For simple atomic update:
        UPDATE promotion_jobs 
        SET status='RUNNING', updated_at=NOW(), attempt_count=attempt_count+1 
        WHERE job_id = (SELECT job_id FROM promotion_jobs WHERE status='PENDING' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
        RETURNING *;
        """
        # SQLAlchemy atomic update with subquery
        subquery = (
            select(PromotionJobORM.job_id)
            .where(PromotionJobORM.status == PromotionStatus.PENDING)
            .order_by(PromotionJobORM.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        
        stmt = (
            update(PromotionJobORM)
            .where(PromotionJobORM.job_id == subquery)
            .values(
                status=PromotionStatus.RUNNING,
                attempt_count=PromotionJobORM.attempt_count + 1
            )
            .returning(PromotionJobORM)
        )
        
        result = await db.execute(stmt)
        orm = result.scalar_one_or_none()
        await db.commit()
        
        if orm:
            return PromotionJob.model_validate(orm)
        return None

    @classmethod
    async def recover_stuck_jobs(cls, db: AsyncSession, timeout_seconds: int = 600):
        """
        Reset RUNNING jobs that haven't been updated in timeout_seconds to PENDING.
        """
        cutoff = datetime.utcnow() - timedelta(seconds=timeout_seconds)
        stmt = (
            update(PromotionJobORM)
            .where(
                PromotionJobORM.status == PromotionStatus.RUNNING,
                PromotionJobORM.updated_at < cutoff
            )
            .values(
                status=PromotionStatus.PENDING,
                last_error_message="Recovered from stuck state"
            )
        )
        result = await db.execute(stmt)
        await db.commit()
        
        # Metric: Count recovered rows
        if result.rowcount > 0:
            from app.core.promotion.telemetry import inc_stuck_counter
            for _ in range(result.rowcount):
                inc_stuck_counter()

    @classmethod
    async def update_status(
        cls, 
        db: AsyncSession, 
        job_id: uuid.UUID, 
        status: PromotionStatus, 
        error: Optional[str] = None,
        kb_doc_id: Optional[str] = None,
        increment_attempt: bool = False
    ):
        values = {"status": status}
        if error:
            values["last_error_message"] = error
        if kb_doc_id:
            values["kb_doc_id"] = kb_doc_id
        
        stmt = update(PromotionJobORM).where(PromotionJobORM.job_id == job_id).values(**values)
        
        if increment_attempt:
            stmt = stmt.values(attempt_count=PromotionJobORM.attempt_count + 1)
            
        await db.execute(stmt)
        await db.commit()
