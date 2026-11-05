# apps/backend/src/app/api/routes/temp_docs.py
from __future__ import annotations

import logging
import os
import shutil
import uuid
from typing import Optional, Dict, Any


import httpx
from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel

from app.core.db_sql import get_async_db

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.temp_docs.store import TempDocStore
from app.core.temp_docs.extract import extract_text_from_bytes

router = APIRouter(tags=["temp_docs"])
logger = logging.getLogger(__name__)

class TempUploadResponse(BaseModel):
    temp_doc_id: str
    expires_in: int
    chunk_count: int
    message: str

class PromoteRequest(BaseModel):
    tenant_id: str
    temp_doc_id: str
    doc_type: str
    meeting_id: Optional[str] = None

class PromoteResponse(BaseModel):
    status: str
    trace_id: str
    message: str

@router.post("/upload", response_model=Dict[str, Any])
async def upload_temp_doc(
    file: UploadFile = File(...),
    tenant_id: str = Form(...),
    db: AsyncSession = Depends(get_async_db)
):
    if not settings.ENABLE_TEMP_DOCS:
        raise HTTPException(status_code=403, detail="Temp docs feature is disabled")

    # 0. Check Quota
    if not await TempDocStore.check_quota(tenant_id):
        raise HTTPException(status_code=429, detail="Upload quota exceeded (max 50 files/hour)")

    # 1. Read file with Size Limit
    MAX_SIZE = 10 * 1024 * 1024 # 10MB
    content = bytearray()
    
    try:
        while True:
            chunk = await file.read(1024 * 1024) # 1MB chunks
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_SIZE:
                raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}")

    # 2. Extract text with Timeout
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        # Run sync extraction in thread pool with timeout
        text = await asyncio.wait_for(
            loop.run_in_executor(None, extract_text_from_bytes, bytes(content), file.filename or "unknown"),
            timeout=10.0 # 10s timeout
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="File processing timed out")
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        raise HTTPException(status_code=400, detail="Failed to process file")

    if not text:
        raise HTTPException(status_code=400, detail="Could not extract text from file (supported: .txt, .pdf, .docx)")

    # Simple Chunking (split by double newline or max chars)
    # For MVP: split by double newline
    raw_chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
    if not raw_chunks:
        # Fallback: single chunk
        raw_chunks = [text]

    chunks = []
    for i, c_text in enumerate(raw_chunks):
        chunks.append({
            "chunk_id": str(i),
            "text": c_text,
            "order": i
        })

    # Save to Redis
    meta = {
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(content)
    }
    
    # Calculate Hash (Raw Bytes)
    import hashlib
    content_hash = hashlib.sha256(content).hexdigest()
    
    try:
        temp_doc_id = await TempDocStore.save(tenant_id, text, chunks, meta, content_hash=content_hash)
        
        # Audit Log: Upload
        from app.core.audit.audit import AuditService
        await AuditService.log_upload(db, tenant_id, temp_doc_id, file.filename, len(content))
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to save temp doc: {e}")
        raise HTTPException(status_code=500, detail="Failed to save temporary document")

    return TempUploadResponse(
        temp_doc_id=temp_doc_id,
        expires_in=settings.TEMP_DOC_TTL,
        chunk_count=len(chunks),
        message="Temporary document uploaded successfully"
    )

@router.post("/temp/promote", response_model=PromoteResponse)
async def promote_temp_doc(
    req: PromoteRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db)
):
    if not settings.ENABLE_TEMP_DOCS:
        raise HTTPException(status_code=403, detail="Temp docs feature is disabled")

    # 1. Get from Redis
    data = await TempDocStore.get(req.tenant_id, req.temp_doc_id)
    if not data:
        raise HTTPException(status_code=404, detail="Temp doc not found or expired")

    text_content = data.get("text", "")
    filename = data.get("meta", {}).get("filename", "promoted.txt")
    if not filename.endswith(".txt"):
        filename += ".txt"
        
    # Get stored hash or fallback to text hash (backward compatibility for old docs)
    content_hash = data.get("content_hash")
    if not content_hash:
        import hashlib
        content_hash = hashlib.sha256(text_content.encode("utf-8")).hexdigest()

    # 2. Create Job (Idempotent)
    from app.core.promotion.promotion import PromotionService, PromotionStatus
    
    job = await PromotionService.create_job_idempotent(
        db,
        tenant_id=req.tenant_id,
        temp_doc_id=req.temp_doc_id,
        content_hash=content_hash,
        filename=filename
    )
    
    # Audit Log: Promotion Created
    from app.core.audit.audit import AuditService
    await AuditService.log_promotion(db, req.tenant_id, str(job.job_id), req.temp_doc_id)
    await db.commit() # Commit audit log
    
    # If job is already DONE, return immediately
    if job.status == PromotionStatus.DONE:
        return PromoteResponse(
            status="DONE",
            trace_id=str(job.job_id),
            message="Document already promoted"
        )
        
    # If job is RUNNING or PENDING, we might want to re-trigger if it's stuck?
    # For P1, if it exists, we just return the ID.
    # But if it's PENDING, we should ensure the worker runs.
    # Since we use BackgroundTasks here (in-process), if the previous request died, the task died.
    # So we should probably re-queue it if it's PENDING/RUNNING but old?
    # For MVP, we just re-queue always if not DONE.
    
    # 3. Prepare File for Worker
    # We need to save the file again because worker needs it.
    # Ideally, worker should fetch from Redis, but Redis might expire.
    # So we save to FS.
    trace_id = str(job.job_id)
    storage_tmp = os.getenv("STORAGE_TMP_DIR", "/tmp/ai_chat_storage")
    os.makedirs(storage_tmp, exist_ok=True)
    file_path = os.path.join(storage_tmp, f"{trace_id}_{filename}")
    
    # Write file (overwrite is fine)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text_content)
    except Exception as e:
        logger.error(f"Failed to write temp file: {e}")
        raise HTTPException(status_code=500, detail="Failed to prepare file")

    # 4. Trigger Worker
    from app.core.promotion.worker import process_promotion_job
    background_tasks.add_task(process_promotion_job, job.job_id, file_path, req.doc_type)

    return PromoteResponse(
        status=job.status.value,
        trace_id=str(job.job_id),
        message="Promotion job started"
    )
