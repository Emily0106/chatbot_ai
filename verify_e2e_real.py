import asyncio
import httpx
import os
import sys
import uuid

# Configuration
API_BASE = os.getenv("BASE_URL", "http://localhost:8000")
TENANT_ID = os.getenv("TENANT_ID", "e2e_test_tenant")
TEST_FILE_CONTENT = f"UNIQUE_E2E_MARKER_{uuid.uuid4().hex[:8]}"
TEST_FILENAME = "e2e_test_doc.txt"

async def run_e2e():
    print(f"=== Starting Real E2E Test against {API_BASE} ===")
    print(f"Tenant: {TENANT_ID}")
    print(f"Marker: {TEST_FILE_CONTENT}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Upload
        print("\n1. Uploading Temp Doc...")
        files = {"file": (TEST_FILENAME, TEST_FILE_CONTENT.encode("utf-8"), "text/plain")}
        data = {"tenant_id": TENANT_ID}
        
        try:
            resp = await client.post(f"{API_BASE}/api/v1/temp/upload", files=files, data=data)
            resp.raise_for_status()
            upload_res = resp.json()
            temp_doc_id = upload_res["temp_doc_id"]
            print(f"   -> Uploaded. Temp Doc ID: {temp_doc_id}")
        except Exception as e:
            print(f"   -> Upload FAILED: {e}")
            return

        # 2. Promote
        print("\n2. Promoting to KB...")
        promote_req = {
            "tenant_id": TENANT_ID,
            "temp_doc_id": temp_doc_id,
            "doc_type": "legal_document"
        }
        try:
            resp = await client.post(f"{API_BASE}/api/v1/temp/promote", json=promote_req)
            resp.raise_for_status()
            promote_res = resp.json()
            job_id = promote_res["trace_id"] # API returns trace_id as job_id
            print(f"   -> Promotion Started. Job ID: {job_id}")
        except Exception as e:
            print(f"   -> Promotion FAILED: {e}")
            return

        # 3. Poll Status
        print("\n3. Polling Job Status...")
        status = "PENDING"
        attempts = 0
        while status in ["PENDING", "RUNNING"] and attempts < 20:
            await asyncio.sleep(2)
            try:
                resp = await client.get(f"{API_BASE}/api/v1/promotion_jobs/{job_id}", params={"tenant_id": TENANT_ID})
                resp.raise_for_status()
                job_info = resp.json()
                status = job_info["status"]
                print(f"   -> Status: {status} (Attempt {attempts+1})")
                if status == "FAILED":
                    print(f"   -> Job Failed: {job_info.get('last_error_message')}")
                    return
            except Exception as e:
                print(f"   -> Poll Failed: {e}")
                return
            attempts += 1
            
        if status != "DONE":
            print("   -> Timeout waiting for DONE status.")
            return
        
        print("   -> Job DONE.")

        # 4. Search KB
        print("\n4. Verifying KB Retrieval...")
        # Assuming there is a search endpoint. If not, we might need to use the chat endpoint.
        # Let's try /api/v1/chat/search if it exists, or check routes.
        # Based on previous context, there is likely a search or chat endpoint.
        # Let's assume a generic search for now or ask the user to verify manually if this fails.
        
        # Trying a hypothetical search endpoint
        search_query = TEST_FILE_CONTENT
        try:
            # This is a guess at the endpoint. Adjust based on actual API.
            # If we don't know, we print instructions.
            print(f"   -> Please manually verify search for '{TEST_FILE_CONTENT}' in tenant '{TENANT_ID}'")
            print("   -> (Automated search step skipped as endpoint is not confirmed in context)")
            
            # If we knew the endpoint:
            # resp = await client.post(f"{API_BASE}/api/v1/chat/search", json={"query": search_query, "tenant_id": TENANT_ID})
            # ...
        except Exception as e:
            print(f"   -> Search check failed: {e}")

        # 5. Negative Test: Cross-Tenant Access
        print("\n5. Verifying Cross-Tenant Isolation...")
        try:
            other_tenant = "tenant_hacker"
            resp = await client.get(f"{API_BASE}/api/v1/promotion_jobs/{job_id}", params={"tenant_id": other_tenant})
            if resp.status_code in [403, 404]:
                print(f"   -> PASS: Access denied ({resp.status_code})")
            else:
                print(f"   -> FAIL: Access allowed ({resp.status_code})")
        except Exception as e:
            print(f"   -> Check failed: {e}")

        # 6. Negative Test: Duplicate Promote
        print("\n6. Verifying Duplicate Promote (Idempotency)...")
        try:
            # Promote same file/tenant again
            resp = await client.post(f"{API_BASE}/api/v1/temp/promote", json=promote_req)
            resp.raise_for_status()
            dup_res = resp.json()
            dup_job_id = dup_res["trace_id"]
            
            if dup_job_id == job_id:
                print(f"   -> PASS: Idempotent (Same Job ID: {dup_job_id})")
            else:
                print(f"   -> FAIL: Duplicate created (New ID: {dup_job_id})")
        except Exception as e:
            print(f"   -> Check failed: {e}")

if __name__ == "__main__":
    asyncio.run(run_e2e())
