from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel
from app.core.canonical_models import DocCategory

class HealthCheck(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"

class IngestResponse(BaseModel):
    job_id: str
    doc_id: UUID
    status: str = "queued"

class JobStatus(BaseModel):
    job_id: str
    status: str
    result: Optional[str] = None
    error: Optional[str] = None
