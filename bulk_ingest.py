import os
import requests
import time
from pathlib import Path

API_URL = "http://localhost:8010/ingest"
DATA_DIR = "storage/raw_files/legal_docs"

def ingest_file(file_path):
    print(f"Ingesting {file_path}...")
    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/pdf")} # Defaulting to PDF, API might detect
            data = {
                "scope": "global_law",
                "doc_category_hint": "legal_doc"
            }
            resp = requests.post(API_URL, files=files, data=data)
            resp.raise_for_status()
            print(f"  -> Success: {resp.json()}")
            return resp.json().get("job_id")
    except Exception as e:
        print(f"  -> Failed: {e}")
        return None

def main():
    root = Path(DATA_DIR)
    if not root.exists():
        print(f"Directory {DATA_DIR} not found.")
        return

    job_ids = []
    for f in root.glob("**/*"):
        if f.is_file():
            job_id = ingest_file(f)
            if job_id:
                job_ids.append(job_id)
    
    print(f"\nQueued {len(job_ids)} jobs.")
    
    # Optional: Monitor jobs?
    # For now, just let them run.

if __name__ == "__main__":
    main()
