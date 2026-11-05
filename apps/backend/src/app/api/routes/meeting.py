from __future__ import annotations

import logging
import os
import shutil
import uuid
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.config import settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.agents.registry import get_agent

router = APIRouter(tags=["meeting"])
logger = logging.getLogger(__name__)

# Config for Ingestion Service
INGESTION_SERVICE_URL = os.getenv("INGESTION_SERVICE_URL", "http://ingestion:8000")
STORAGE_TMP_DIR = os.getenv("STORAGE_TMP_DIR", "/app/storage/raw_files/tmp")

class MeetingUploadResponse(BaseModel):
    status: str
    trace_id: str
    filename: str
    message: str

@router.post("/meeting/upload", response_model=MeetingUploadResponse)
async def upload_meeting_transcript(
    file: UploadFile = File(...),
    tenant_id: str = "default", # Should ideally come from token/header
):
    trace_id = str(uuid.uuid4())
    
    # 1. Save file locally (tmp)
    os.makedirs(STORAGE_TMP_DIR, exist_ok=True)
    file_path = os.path.join(STORAGE_TMP_DIR, f"{trace_id}_{file.filename}")
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        logger.error(f"Failed to save file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save file")

    # 2. Trigger Ingestion via HTTP (Multipart)
    ingest_url = f"{INGESTION_SERVICE_URL}/api/v1/ingest"
    
    # We need to send 'file' and 'scope' as form data
    # Since we already saved the file, we can open it and send it.
    # Note: In a shared volume setup, ideally we would pass the path, 
    # but the current Ingestion API expects a file upload.
    
    async with httpx.AsyncClient() as client:
        try:
            with open(file_path, "rb") as f:
                files = {"file": (file.filename, f, file.content_type)}
                data = {
                    "scope": "local_gov", # Default scope
                    "commune_id": tenant_id # Map tenant_id to commune_id for isolation
                }
                resp = await client.post(ingest_url, files=files, data=data, timeout=30.0)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ingestion trigger failed: {e}")
            raise HTTPException(status_code=502, detail=f"Ingestion service unavailable: {str(e)}")

    return MeetingUploadResponse(
        status="processing",
        trace_id=trace_id,
        filename=file.filename,
        message="File uploaded and queued for ingestion"
    )

@router.post("/meeting/analyze", response_model=ChatResponse)
async def analyze_meeting(req: ChatRequest):
    # Delegate to MeetingAgent
    agent = get_agent("meeting_agent") # Fixed ID from meeting_assistant
    if not agent:
        raise HTTPException(status_code=500, detail="Meeting Agent not found")
    
    # Check for Temp Flow
    # temp_doc_id = getattr(req, "temp_doc_id", None)
    # if temp_doc_id:
    #     from app.core.temp_docs.store import TempDocStore
        
    #     # 1. Resolve tenant
    #     tenant_id = agent.resolved_tenant_id(req, None)
    #     trace_id = getattr(req, "trace_id", None) or "unknown_trace"
        
    #     # 2. Search in Temp Store
    #     search_res = await TempDocStore.search(tenant_id, temp_doc_id, query=req.message or "")
        
    #     # 3. Call Agent with Context
    #     return await agent.analyze_with_context(
    #         query=req.message or "",
    #         context=search_res["context"],
    #         citations=search_res["citations"],
    #         tenant_id=tenant_id,
    #         trace_id=trace_id
    #     )

    # Default: KB Flow
    return await agent.handle(req)
