import asyncio
import os
import sys
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "apps/backend/src"))

# Mock Settings
os.environ["QDRANT_URL"] = "http://localhost:6333"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ENABLE_TEMP_DOCS"] = "true"
os.environ["INGESTION_BASE_URL"] = "http://localhost:8010"

from app.core.audit.audit import AuditService
from app.core.ops.retention import RetentionService
from app.api.routes.ops import get_system_health

async def test_p3_at01_audit_logging():
    print("\n=== P3-AT01/02: Audit Logging ===")
    db = AsyncMock()
    
    # Test Upload Log
    await AuditService.log_upload(db, "t1", "doc1", "file.txt", 100)
    
    # Verify SQL execution
    calls = db.execute.call_args_list
    found_upload = False
    for call in calls:
        stmt = str(call[0][0])
        params = call[0][1]
        if "INSERT INTO audit_log_events" in stmt and params["action"] == "TEMP_UPLOAD_CREATED":
            found_upload = True
            print("PASS: TEMP_UPLOAD_CREATED logged.")
            break
            
    if not found_upload:
        print("FAIL: Upload log not found.")

async def test_p3_at03_retention_cleanup():
    print("\n=== P3-AT03: Retention Cleanup ===")
    db = AsyncMock()
    
    # Mock delete returning 5 rows
    mock_result = MagicMock()
    mock_result.__iter__.return_value = [MagicMock(count=5, tenant_id="t1")]
    db.execute.return_value = mock_result
    
    await RetentionService.cleanup_jobs(db)
    
    # Verify Audit Log for cleanup
    calls = db.execute.call_args_list
    found_cleanup = False
    for call in calls:
        if len(call[0]) > 1 and isinstance(call[0][1], dict):
            params = call[0][1]
            if params.get("action") == "RETENTION_CLEANUP":
                found_cleanup = True
                print("PASS: RETENTION_CLEANUP logged.")
                break
                
    if not found_cleanup:
        print("FAIL: Cleanup log not found.")

async def test_p3_at04_health_endpoint():
    print("\n=== P3-AT04: Health Endpoint ===")
    db = AsyncMock()
    
    # Mock job counts
    mock_result = MagicMock()
    mock_result.__iter__.return_value = [
        MagicMock(status=MagicMock(value="DONE"), count=10),
        MagicMock(status=MagicMock(value="FAILED"), count=1)
    ]
    db.execute.return_value = mock_result
    
    health = await get_system_health(db)
    
    if health["status"] == "healthy" and health["failure_rate"] > 0:
        print(f"PASS: Health returned valid data: {health}")
    else:
        print(f"FAIL: Invalid health data: {health}")

async def main():
    await test_p3_at01_audit_logging()
    await test_p3_at03_retention_cleanup()
    await test_p3_at04_health_endpoint()

if __name__ == "__main__":
    asyncio.run(main())
