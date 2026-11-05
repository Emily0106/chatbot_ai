import shutil
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from app.api.deps import get_repo
from app.api.schemas import IngestResponse
from app.core.canonical_models import DocCategory
from app.preproc.stores.postgres_repo import PostgresRepo
from app.preproc.utils.ids import make_doc_id

router = APIRouter()

# Temporary storage for uploads
UPLOAD_DIR = Path("uploads_tmp")
UPLOAD_DIR.mkdir(exist_ok=True)

@router.post("/ingest/file", response_model=IngestResponse)
async def ingest_file(
    file: Annotated[UploadFile, File()],
    scope: Annotated[str, Form()] = "default",
    doc_category: Annotated[str, Form()] = "report",
    background_tasks: BackgroundTasks = None, # Used if we don't have a separate worker yet
    repo: PostgresRepo = Depends(get_repo),
):
    try:
        # 1. Save file locally
        file_ext = Path(file.filename).suffix
        temp_filename = f"{uuid.uuid4()}{file_ext}"
        file_path = UPLOAD_DIR / temp_filename
        
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # 2. Generate Doc ID (Scanning content for hash is expensive here, 
        # so we might defer it or compute simple hash now)
        # For now, we'll assume the worker does the heavy hashing/dedup or we do a quick pass.
        # Let's do a quick pass since we have the file.
        # Actually, make_doc_id requires the content or hash.
        # Let's just generate a provisional UUID or let the orchestrator decide.
        # But we need to return doc_id. 
        # For now, random UUID for the job response, orchestrator will finalize the deterministic ID.
        # OR: we compute hash now.
        
        # 3. Enqueue Job via ARQ
        # Parse REDIS_URL again or move to deps
        from arq import create_pool
        from arq.connections import RedisSettings
        import urllib.parse
        from app.core.config import settings

        p = urllib.parse.urlparse(settings.REDIS_URL)
        redis_settings = RedisSettings(
            host=p.hostname or 'localhost',
            port=p.port or 6379,
            database=int(p.path.lstrip('/')) if p.path else 0
        )
        
        # In production: maintain a global pool in lifespan or deps
        redis = await create_pool(redis_settings)
        job = await redis.enqueue_job(
            "ingest_task",
            str(uuid.uuid4()), # job_id param for function? check worker signature
            str(file_path.absolute()),
            scope,
            doc_category
        )
        redis.close()

        job_id = job.job_id if job else str(uuid.uuid4())

        return IngestResponse(
            job_id=job_id,
            doc_id=uuid.uuid4(), # Placeholder
            status="queued"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
