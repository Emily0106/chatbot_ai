import os
import sys
import hashlib
import mimetypes
from pathlib import Path
from uuid import uuid4
from datetime import datetime

# Add src and libs to path
sys.path.append("/app/src")
sys.path.append("/app/libs/core_shared")

from app.preproc.stores.postgres_repo import PostgresRepo, PostgresRepoConfig
from app.core.config import settings
from app.core.canonical_models import Scope

def calculate_checksum(file_path: Path) -> str:
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def main():
    print("Starting ingestion job creation for legal docs...")
    
    # Configuration
    db_url = settings.DATABASE_URL
    if not db_url:
        print("Error: DATABASE_URL not set")
        return

    repo = PostgresRepo(PostgresRepoConfig(conninfo=db_url))
    
    # Path to legal docs
    # In container: /app/storage/legal_docs (mapped from storage/raw_files/legal_docs)
    base_path = Path("/app/storage/legal_docs")
    
    if not base_path.exists():
        print(f"Error: Path {base_path} does not exist.")
        # Fallback for local testing if not in container
        if Path("storage/raw_files/legal_docs").exists():
            base_path = Path("storage/raw_files/legal_docs")
            print(f"Found local path: {base_path}")
        else:
            return

    files = [f for f in base_path.rglob("*") if f.is_file()]
    print(f"Found {len(files)} files.")

    for file_path in files:
        try:
            print(f"Processing {file_path.name}...")
            
            job_id = uuid4()
            checksum = calculate_checksum(file_path)
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"
            
            # Relative path for source_uri
            # We want source_uri to be relative to storage root or absolute?
            # The worker uses this URI to read the file.
            # If worker mounts /app/storage, then source_uri should probably be relative to it or absolute inside container.
            # Let's use relative to /app/storage for consistency if possible, or just the absolute path in container.
            # worker_main.py calls orch.process(job["source_uri"], meta)
            # orch.process likely expects a path it can open.
            
            # If we use absolute path inside container:
            source_uri = str(file_path.absolute())
            if not source_uri.startswith("/app/storage"):
                 # If running locally, adjust to container path expectation if needed
                 # But for now let's assume we run this script INSIDE container.
                 pass

            repo.create_job(
                job_id=job_id,
                job_type="ingest",
                scope=Scope.global_law.value,
                commune_id=None,
                source_uri=source_uri,
                mime_type=mime_type,
                checksum=checksum,
                title=file_path.stem,
                pipeline_version="v1",
                doc_category_hint="legal" 
            )
            print(f"Created job {job_id} for {file_path.name}")
            
        except Exception as e:
            print(f"Failed to create job for {file_path.name}: {e}")

    print("Done creating jobs.")

if __name__ == "__main__":
    main()
