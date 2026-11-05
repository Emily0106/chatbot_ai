import asyncio
import os
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "apps/backend/src"))

from app.config import settings

async def apply():
    print(f"Connecting to {settings.DB_URL}")
    engine = create_async_engine(settings.DB_URL)
    
    with open("apps/ingestion/migrations/004_add_approval_cols.sql", "r") as f:
        sql = f.read()
        
    async with engine.begin() as conn:
        # Split by ; if multiple statements, but execute supports multiple usually?
        # SQLAlchemy execute might not support multiple statements in one go depending on driver.
        # Let's try executing the whole block.
        await conn.execute(text(sql))
        
    print("Migration applied successfully.")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(apply())
