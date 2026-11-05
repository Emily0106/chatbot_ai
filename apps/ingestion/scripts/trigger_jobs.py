import sys
import os

# Add src to path
sys.path.append("/app/src")

# Ensure env vars are set (should be inherited from container env)
# But settings might need them.

from app.workers.worker_main import celery_app
from app.preproc.stores.postgres_repo import PostgresRepo, PostgresRepoConfig
from app.core.config import settings

def trigger_queued_jobs():
    print("Connecting to DB...")
    repo = PostgresRepo(PostgresRepoConfig(conninfo=str(settings.DATABASE_URL)))
    
    with repo._conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT job_id FROM ingestion_jobs WHERE status='queued'")
            rows = cur.fetchall()
            print(f"Found {len(rows)} queued jobs.")
            
            for row in rows:
                job_id = str(row[0])
                print(f"Triggering job {job_id}")
                celery_app.send_task("ingestion.run_job", args=[job_id])
    
    print("Done triggering jobs.")

if __name__ == "__main__":
    trigger_queued_jobs()
