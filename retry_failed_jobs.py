import asyncio
import os
import sys
from sqlalchemy import text
from celery import Celery

# Set environment variables required by app.config
os.environ["POSTGRES_USER"] = "test"
os.environ["POSTGRES_PASSWORD"] = "test"
os.environ["POSTGRES_DB"] = "test"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["QDRANT_URL"] = "http://localhost:6333"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["DB_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test"
os.environ["OPENAI_API_KEY"] = "sk-test" # Required by app.config

# Add paths to sys.path
sys.path.append(os.path.abspath("apps/backend/src"))
sys.path.append(os.path.abspath("libs/core_shared"))
sys.path.append(os.path.abspath("apps/ingestion/src"))

from app.core.db_sql import get_async_db

# Celery setup
REDIS_URL = os.environ["REDIS_URL"]
celery_app = Celery(
    "ingestion_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

async def retry_jobs():
    print("--- Retrying Failed Ingestion Jobs ---")
    async for session in get_async_db():
        try:
            # Get ALL jobs (failed + done) to ensure Qdrant is populated
            result = await session.execute(text("SELECT job_id FROM ingestion_jobs"))
            failed_jobs = result.fetchall()
            
            if not failed_jobs:
                print("No jobs found.")
                return

            print(f"Found {len(failed_jobs)} jobs. Resubmitting ALL...")
            
            count = 0
            for row in failed_jobs:
                job_id = str(row[0])
                
                # Update status to pending
                await session.execute(
                    text("UPDATE ingestion_jobs SET status = 'pending', error = NULL, progress = 0 WHERE job_id = :job_id"),
                    {"job_id": job_id}
                )
                
                # Resubmit to Celery
                celery_app.send_task("ingestion.run_job", args=[job_id])
                count += 1
                
                if count % 10 == 0:
                    print(f"  Resubmitted {count} jobs...")
            
            await session.commit()
            print(f"Successfully resubmitted {count} jobs.")

        except Exception as e:
            print(f"Error retrying jobs: {e}")
            await session.rollback()
        finally:
            await session.close()
            break

if __name__ == "__main__":
    asyncio.run(retry_jobs())
