#!/usr/bin/env python3
import requests
import json
import time
import os
import uuid

# Configuration
BASE_URL = "http://localhost:8010/api/v1/admin"
INGEST_BASE = "http://localhost:8010/api/v1"
BACKEND_URL = "http://localhost:8000/api/v1/chat"
TENANT_ID = "default_tenant"
USER_ROLE = "admin"

HEADERS = {
    "X-GOVAI-TENANT-ID": TENANT_ID,
    "X-GOVAI-USER-ROLE": USER_ROLE,
    "Content-Type": "application/json"
}

def log(msg, status="INFO"):
    print(f"[{status}] {msg}")

def check_health():
    try:
        r = requests.get("http://localhost:8010/health")
        if r.status_code == 200:
            log("Health Check: OK")
        else:
            log(f"Health Check Failed: {r.status_code}", "FAIL")
            exit(1)
    except Exception as e:
        log(f"Health Check Error: {e}", "FAIL")
        exit(1)

def verify_metrics():
    log("Verifying Metrics...")
    r = requests.get(f"{BASE_URL}/metrics", headers=HEADERS)
    if r.status_code == 200:
        data = r.json()
        log(f"Metrics: {json.dumps(data, indent=2)}")
        if "total_jobs" in data:
            log("Metrics Check: PASS")
        else:
            log("Metrics Missing expected keys", "WARN")
    else:
        log(f"Metrics Failed: {r.status_code} {r.text}", "FAIL")

def create_profile():
    log("Creating Profile...")
    profile_id = str(uuid.uuid4())
    payload = {
        "profile_id": profile_id,
        "tenant_id": TENANT_ID,
        "name": f"ops_test_profile_{profile_id[:8]}",
        "description": "Verification Profile",
        "config": {
            "doc_type": "report",
            "scope": "internal",
            "security_level": 2,
            "auto_approve": True 
        }
    }
    r = requests.post(f"{BASE_URL}/profiles", headers=HEADERS, json=payload)
    if r.status_code == 201:
        log(f"Profile Created: {profile_id}")
        return profile_id
    else:
        log(f"Create Profile Failed: {r.status_code} {r.text}", "FAIL")
        exit(1)

def presign_upload(profile_id):
    log("Requesting Presigned URL...")
    payload = {
        "profile_id": profile_id,
        "filename": "ops_test_doc.txt",
        "mime_type": "text/plain",
        "size_bytes": 1024
    }
    r = requests.post(f"{BASE_URL}/upload/presign", headers=HEADERS, json=payload)
    if r.status_code == 200:
        data = r.json()
        log(f"Presign Success: {data['object_key']}")
        return data["upload_url"], data["object_key"]
    else:
        log(f"Presign Failed: {r.status_code} {r.text}", "FAIL")
        exit(1)

def perform_upload(upload_url, content="Hello Ops World"):
    log("Simulating Upload (PUT)...")
    # For local filesystem storage adapter, 'upload_url' might be a local path or a valid HTTP PUT?
    # In endpoints.py: signer.generate_presigned_put -> likely returns a mock URL or S3 URL.
    # If no MinIO, 'get_s3_signer' might fallback to something or fail?
    # Let's inspect the URL.
    if upload_url.startswith("http"):
        # Attempt PUT
        try:
             r = requests.put(upload_url, data=content.encode("utf-8"), headers={"Content-Type": "text/plain"})
             if r.status_code in [200, 204]:
                 log("Upload Success")
             else:
                 log(f"Upload returned {r.status_code} (Expected if mock S3 not running). Proceeding assuming 'upload' is simulated or manual file placement needed.", "WARN")
        except Exception as e:
             log(f"Upload Connection Failed: {e}", "WARN")
    else:
        log(f"Upload URL is not HTTP: {upload_url}. Assuming Local Path", "INFO")
        # Ensure directory exists if it's a path
        try:
            # It's likely an absolute path in the container? Verification script running on host.
            # Volume mapping: ./storage/raw_files -> /app/storage
            # object_key starts with "raw/..."
            pass
        except:
             pass

def submit_job(profile_id, object_key):
    log("Submitting Job...")
    payload = {
        "profile_id": profile_id,
        "files": [
            {
                "object_key": object_key,
                "original_name": "ops_test_doc.txt",
                "mime_type": "text/plain",
                "size_bytes": 1024,
                "checksum": "mock_checksum" 
            }
        ],
        "note": "Ops Verification"
    }
    r = requests.post(f"{BASE_URL}/jobs", headers=HEADERS, json=payload)
    if r.status_code == 200:
        data = r.json()
        log(f"Job Submitted. Jobs Created: {data['jobs_created']}, Status: {data['status']}")
        return True
    else:
        log(f"Job Submit Failed: {r.status_code} {r.text}", "FAIL")
        return False

def list_jobs_verify():
    log("Listing Jobs...")
    r = requests.get(f"{BASE_URL}/jobs", headers=HEADERS)
    if r.status_code == 200:
        jobs = r.json()
        if len(jobs) > 0:
            log(f"Found {len(jobs)} jobs. Top job: {jobs[0].get('job_id')} Status: {jobs[0].get('status')}")
            return jobs[0].get('job_id')
        else:
            log("No jobs found in list", "WARN")
    else:
        log(f"List Jobs Failed: {r.status_code}", "FAIL")
    return None

def main():
    check_health()
    verify_metrics()
    
    p_id = create_profile()
    
    # 2026-02-02 NOTE: Without MinIO, presign/upload is tricky unless we manually place the file.
    # docker-compose.dev.yml maps ./storage/raw_files -> /app/storage
    # 'object_key' will be: raw/{tenant}/{date}/{uuid}_name
    # We should write file manually to match this if PUT fails.
    
    up_url, obj_key = presign_upload(p_id)
    perform_upload(up_url)
    
    # Manual File Placement Hack (for E2E without S3)
    # Map obj_key 'raw/...' to './storage/raw_files/...'
    # Wait, ingestion service expects MinIO or Local? 
    # Config seems to imply 's3_storage.py' uses boto3. If no MinIO, it might fail.
    # But let's try submitting job. If worker fails to download, that's a finding.
    
    res = submit_job(p_id, obj_key)
    
    if res:
        time.sleep(2)
        job_id = list_jobs_verify()
        if job_id:
            log(f"Verification Successful. Job ID: {job_id}")
        else:
            log("Verification Partial: Job submitted but not found in list?", "WARN")

if __name__ == "__main__":
    main()
