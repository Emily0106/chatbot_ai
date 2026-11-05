# apps/backend/src/app/core/audit/audit.py
import uuid
import logging
import json
import time
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)

class AuditEvent(BaseModel):
    event_id: uuid.UUID
    timestamp: datetime
    tenant_id: str
    actor_type: str
    actor_id: Optional[str]
    action: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    trace_id: Optional[str]
    metadata: Dict[str, Any]

class AuditService:
    @classmethod
    async def log_event(
        cls,
        db: AsyncSession,
        tenant_id: str,
        action: str,
        actor_type: str = "system",
        actor_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log an audit event to the database.
        """
        try:
            event_id = uuid.uuid4()
            metadata_json = metadata or {}
            
            # Raw SQL insert for simplicity and speed, or use ORM if preferred.
            # Using text() for now to avoid creating another ORM model file if not strictly needed,
            # but creating a model is cleaner. Let's use raw SQL for this utility.
            
            stmt = text("""
                INSERT INTO audit_log_events (
                    event_id, tenant_id, actor_type, actor_id, action, 
                    entity_type, entity_id, trace_id, metadata, timestamp
                ) VALUES (
                    :event_id, :tenant_id, :actor_type, :actor_id, :action,
                    :entity_type, :entity_id, :trace_id, :metadata, :timestamp
                )
            """)
            
            await db.execute(stmt, {
                "event_id": event_id,
                "tenant_id": tenant_id,
                "actor_type": actor_type,
                "actor_id": actor_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "trace_id": trace_id,
                "metadata": import_json(metadata_json), # Helper needed? SQLAlchemy handles dict as JSONB usually
                "timestamp": datetime.utcnow()
            })
            # We don't commit here, let the caller commit to ensure atomicity with the main operation
            # UNLESS this is a fire-and-forget log. 
            # Ideally audit logs should be part of the transaction.
            
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")

    @classmethod
    async def log_upload(cls, db: AsyncSession, tenant_id: str, temp_doc_id: str, filename: str, size: int):
        await cls.log_event(
            db, tenant_id, "TEMP_UPLOAD_CREATED", 
            entity_type="temp_doc", entity_id=temp_doc_id,
            metadata={"filename": filename, "size": size}
        )

    @classmethod
    async def log_promotion(cls, db: AsyncSession, tenant_id: str, job_id: str, temp_doc_id: str):
        await cls.log_event(
            db, tenant_id, "PROMOTION_JOB_CREATED",
            entity_type="promotion_job", entity_id=job_id,
            metadata={"temp_doc_id": temp_doc_id}
        )

    @classmethod
    async def log_status_change(cls, db: AsyncSession, tenant_id: str, job_id: str, old_status: str, new_status: str, error: Optional[str] = None):
        meta = {"old_status": old_status, "new_status": new_status}
        if error:
            meta["error"] = error
            
        await cls.log_event(
            db, tenant_id, "PROMOTION_JOB_STATUS_CHANGED",
            entity_type="promotion_job", entity_id=job_id,
            metadata=meta
        )

def import_json(d):
    import json
    return json.dumps(d)

# =============================================================================
# B6: Structural JSON Audit Logging (File/Stdout)
# =============================================================================

audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)

def compute_query_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()

def audit_event(event_name: str, **kwargs: Any) -> None:
    """
    Emit a structured audit log event.
    Auto-injects: timestamp, service, env, version.
    """
    payload = {
        "ts": time.time(),
        "event": event_name,
        "service": "backend",
        "env": settings.ENV_MODE,
        # "version": settings.VERSION, # If available
    }
    
    # Merge kwargs
    payload.update(kwargs)
    
    # Redaction / Safety checks (Double check)
    if "message" in payload:
        payload["message_redacted_len"] = len(str(payload["message"]))
        del payload["message"]
    if "query" in payload:
        payload["query_redacted_len"] = len(str(payload["query"]))
        del payload["query"]
        
    try:
        # ensure_ascii=False allow UTF-8
        json_line = json.dumps(payload, ensure_ascii=False)
        audit_logger.info(json_line)
    except Exception as e:
        # Fallback to avoid crashing app on log error
        audit_logger.error(f"Failed to log audit event: {e}")
