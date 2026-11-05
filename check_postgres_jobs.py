import asyncio
import os
import sys
from sqlalchemy import text

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
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["INGESTION_SERVICE_URL"] = "http://localhost:8010"
os.environ["STORAGE_TMP_DIR"] = "/tmp/ai_chat_storage"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

# Add paths to sys.path
sys.path.append(os.path.abspath("apps/backend/src"))
sys.path.append(os.path.abspath("libs/core_shared"))

from app.core.db_sql import get_async_db

async def check_jobs():
    print("--- Analyzing Ingestion Jobs ---")
    async for session in get_async_db():
        try:
            # Check all job statuses
            print("\nJob Status Counts:")
            try:
                result = await session.execute(text("SELECT status, count(*) FROM ingestion_jobs GROUP BY status"))
                rows = result.fetchall()
                if not rows:
                    print("  No ingestion jobs found.")
                for status, count in rows:
                    print(f"  {status}: {count}")
            except Exception as e:
                print(f"  Error querying ingestion_jobs: {e}")

            # Check failed jobs errors (if any)
            print("\nTop 5 Failed Job Errors:")
            try:
                result = await session.execute(text(
                    "SELECT error, count(*) as cnt FROM ingestion_jobs WHERE status = 'failed' GROUP BY error ORDER BY cnt DESC LIMIT 5"
                ))
                rows = result.fetchall()
                if not rows:
                    print("  No failed jobs found.")
                for error, count in rows:
                    print(f"  Count: {count} | Error: {error}")
            except Exception as e:
                print(f"  Error querying failed jobs: {e}")

        except Exception as e:
            print(f"Error connecting to database: {e}")
        finally:
            await session.close()
            break

if __name__ == "__main__":
    asyncio.run(check_jobs())
