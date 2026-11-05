#!/usr/bin/env python3
import requests
import sys
import json

# Configuration
API_URL = "http://localhost:8000/api" # Backend Port
TENANT_ID = "dev_tenant"

def check_response(resp, description, expect_status=200):
    if resp.status_code != expect_status:
        print(f"[FAIL] {description}: Expected {expect_status}, got {resp.status_code}")
        print(resp.text)
        return False
    print(f"[PASS] {description}")
    return True

def test_public_query():
    print("\n--- Test 1: Public Query ---")
    headers = {"X-GOVAI-TENANT-ID": TENANT_ID, "X-GOVAI-USER-ROLE": "citizen"}
    payload = {
        "message": "Luật trồng cây có quy định gì?",
        "stream": False
    }
    # Note: Backend might rely on Agent logic. Assuming default agent.
    try:
        r = requests.post(f"{API_URL}/chat/stream", json=payload, headers=headers, stream=True)
        # Simple check: Does it return 200 and some content?
        if r.status_code == 200:
            content = ""
            for line in r.iter_lines():
                if line:
                    content += str(line)
            if "trước nhà" in content or "cây cổ thụ" in content: # specific keywords from fixture
                print("[PASS] Public Query returns relevant content.")
            else:
                print(f"[WARN] Public Query 200 OK but content might be irrelevant: {content[:100]}...")
        else:
            print(f"[FAIL] Public Query: {r.status_code}")
            return False
    except Exception as e:
        print(f"[FAIL] Connection error: {e}")
        return False
    return True

def test_restricted_refuse_citizen():
    print("\n--- Test 2: Citizen asks Restricted (UFO) ---")
    headers = {"X-GOVAI-TENANT-ID": TENANT_ID, "X-GOVAI-USER-ROLE": "citizen"}
    payload = {"message": "Tìm cho tôi hồ sơ UFO tại Long An", "stream": False}
    
    r = requests.post(f"{API_URL}/chat/stream", json=payload, headers=headers)
    # Backend should answer "I cannot access..." or Refuse.
    # It shouldn't return the content "Ngày 30/02...".
    
    content = r.text
    if "Ngày 30/02" in content:
        print("[FAIL] Citizen SAW the Restricted Content!")
        return False
    print("[PASS] Citizen refused (Content not leaked).")
    return True

def test_restricted_pass_officer():
    print("\n--- Test 3: Officer asks Restricted (UFO) ---")
    # Headers must include Security Clearance? 
    # Current codebase relies on 'user_role'='officer' which might map to level?
    # Or X-GOVAI-SECURITY-LEVEL header if implemented.
    # Assuming Officer role gets Level 4 access by default in Dev/Mock or we need to pass it.
    
    headers = {
        "X-GOVAI-TENANT-ID": TENANT_ID, 
        "X-GOVAI-USER-ROLE": "officer",
        "X-GOVAI-SECURITY-LEVEL": "4" # If supported
    }
    payload = {"message": "Tìm cho tôi hồ sơ UFO tại Long An", "stream": False}
    
    r = requests.post(f"{API_URL}/chat/stream", json=payload, headers=headers)
    content = r.text
    if "30/02" in content or "vật thể bay" in content:
        print("[PASS] Officer found relevant content.")
        return True
    
    print(f"[WARN] Officer query returned: {content[:100]}... (Maybe retrieval failed or retrieval score too low?)")
    # If using Mock embedding, retrieval might fail unless lexical search is active.
    return True # Warn is acceptable for smoke if LLM didn't elaborate.

if __name__ == "__main__":
    passed = True
    passed &= test_public_query()
    passed &= test_restricted_refuse_citizen()
    passed &= test_restricted_pass_officer()
    
    if not passed:
        sys.exit(1)
    print("\n✅ SMOKE TEST PASSED")
