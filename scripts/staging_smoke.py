#!/usr/bin/env python3
"""
Staging Smoke Test Suite
Validates Gov-AI Backend staging deployment end-to-end.

Usage:
    python3 scripts/staging_smoke.py --base-url http://localhost:8000 --api-key <key>
    python3 scripts/staging_smoke.py --base-url http://localhost:8000 --api-key <key1> --api-key-2 <key2>
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Tuple
import requests
from requests.exceptions import RequestException

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def print_test(name: str, status: str, details: str = ""):
    """Print test result with color"""
    symbol = "✅" if status == "PASS" else "❌"
    color = Colors.GREEN if status == "PASS" else Colors.RED
    print(f"{color}{symbol} {name}: {status}{Colors.RESET}")
    if details:
        print(f"  {details}")

def test_health(base_url: str) -> bool:
    """Test A: Health endpoint"""
    try:
        resp = requests.get(f"{base_url}/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "ok":
                print_test("A) Health check", "PASS", f"Status: {data}")
                return True
        print_test("A) Health check", "FAIL", f"Status: {resp.status_code}, Body: {resp.text[:200]}")
        return False
    except Exception as e:
        print_test("A) Health check", "FAIL", f"Error: {str(e)}")
        return False

def test_health_ready(base_url: str) -> bool:
    """Test A2: Health ready endpoint"""
    try:
        resp = requests.get(f"{base_url}/health/ready", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print_test("A2) Health ready", "PASS", f"Status: {data}")
            return True
        print_test("A2) Health ready", "FAIL", f"Status: {resp.status_code}, Body: {resp.text[:200]}")
        return False
    except Exception as e:
        print_test("A2) Health ready", "FAIL", f"Error: {str(e)}")
        return False

def test_metrics(base_url: str) -> bool:
    """Test B: Metrics endpoint"""
    try:
        resp = requests.get(f"{base_url}/metrics", timeout=5)
        if resp.status_code == 200:
            if "govai_chat_requests_total" in resp.text:
                print_test("B) Metrics endpoint", "PASS", "Found govai_chat_requests_total")
                return True
            else:
                print_test("B) Metrics endpoint", "FAIL", "Missing govai_chat_requests_total metric")
                return False
        print_test("B) Metrics endpoint", "FAIL", f"Status: {resp.status_code}")
        return False
    except Exception as e:
        print_test("B) Metrics endpoint", "FAIL", f"Error: {str(e)}")
        return False

def test_auth_fail(base_url: str) -> bool:
    """Test C: Auth validation - should fail without API key"""
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json={"message": "test", "agent_id": "gov_assistant"},
            timeout=5
        )
        if resp.status_code == 401 or resp.status_code == 403:
            print_test("C) Auth validation (no key)", "PASS", f"Correctly rejected: {resp.status_code}")
            return True
        print_test("C) Auth validation (no key)", "FAIL", f"Expected 401/403, got {resp.status_code}")
        return False
    except Exception as e:
        print_test("C) Auth validation (no key)", "FAIL", f"Error: {str(e)}")
        return False

def test_blocking_chat(base_url: str, api_key: str) -> Tuple[bool, str]:
    """Test D: Blocking chat with valid API key"""
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json={
                "message": "What is your purpose?",
                "agent_id": "gov_assistant",
                "stream": False
            },
            headers={"X-API-Key": api_key},
            timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            # Validate schema
            if "answer" in data and "meta" in data:
                tenant_id = data.get("meta", {}).get("tenant_id", "unknown")
                print_test("D) Blocking chat", "PASS", f"Answer received, tenant_id: {tenant_id}")
                return True, tenant_id
            else:
                print_test("D) Blocking chat", "FAIL", f"Invalid schema: {list(data.keys())}")
                return False, ""
        print_test("D) Blocking chat", "FAIL", f"Status: {resp.status_code}, Body: {resp.text[:200]}")
        return False, ""
    except Exception as e:
        print_test("D) Blocking chat", "FAIL", f"Error: {str(e)}")
        return False, ""

def test_streaming_chat(base_url: str, api_key: str) -> Tuple[bool, str]:
    """Test E: Streaming chat"""
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json={
                "message": "Hello",
                "agent_id": "gov_assistant",
                "stream": True
            },
            headers={"X-API-Key": api_key},
            stream=True,
            timeout=30
        )
        if resp.status_code == 200:
            chunks_received = 0
            tenant_id = "unknown"
            
            for line in resp.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    chunks_received += 1
                    try:
                        data = json.loads(line[5:].strip())
                        if "meta" in data and "tenant_id" in data["meta"]:
                            tenant_id = data["meta"]["tenant_id"]
                    except:
                        pass
                    
                    # Stop after receiving a few chunks
                    if chunks_received >= 5:
                        break
            
            if chunks_received > 0:
                print_test("E) Streaming chat", "PASS", f"Received {chunks_received} chunks, tenant_id: {tenant_id}")
                return True, tenant_id
            else:
                print_test("E) Streaming chat", "FAIL", "No chunks received")
                return False, ""
        print_test("E) Streaming chat", "FAIL", f"Status: {resp.status_code}")
        return False, ""
    except Exception as e:
        print_test("E) Streaming chat", "FAIL", f"Error: {str(e)}")
        return False, ""

def test_tenant_isolation(base_url: str, api_key_1: str, api_key_2: str) -> bool:
    """Test F: Tenant isolation with two different API keys"""
    if not api_key_2:
        print_test("F) Tenant isolation", "SKIP", "No second API key provided")
        return True  # Don't fail if optional test skipped
    
    try:
        # Request with key 1
        resp1 = requests.post(
            f"{base_url}/api/chat",
            json={"message": "test1", "agent_id": "gov_assistant", "stream": False},
            headers={"X-API-Key": api_key_1},
            timeout=30
        )
        
        # Request with key 2
        resp2 = requests.post(
            f"{base_url}/api/chat",
            json={"message": "test2", "agent_id": "gov_assistant", "stream": False},
            headers={"X-API-Key": api_key_2},
            timeout=30
        )
        
        if resp1.status_code == 200 and resp2.status_code == 200:
            tenant1 = resp1.json().get("meta", {}).get("tenant_id", "unknown")
            tenant2 = resp2.json().get("meta", {}).get("tenant_id", "unknown")
            
            if tenant1 != tenant2 and tenant1 != "unknown" and tenant2 != "unknown":
                print_test("F) Tenant isolation", "PASS", f"Tenant1: {tenant1}, Tenant2: {tenant2}")
                return True
            else:
                print_test("F) Tenant isolation", "FAIL", f"Same tenant or unknown: {tenant1} vs {tenant2}")
                return False
        
        print_test("F) Tenant isolation", "FAIL", f"Status1: {resp1.status_code}, Status2: {resp2.status_code}")
        return False
    except Exception as e:
        print_test("F) Tenant isolation", "FAIL", f"Error: {str(e)}")
        return False

def test_authz_denial(base_url: str, api_key: str) -> bool:
    """Test G: AuthZ Denial (request forbidden agent)"""
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json={
                "message": "test context", 
                "agent_id": "unauthorized_agent_007", 
                "stream": False
            },
            headers={"X-API-Key": api_key},
            timeout=10
        )
        if resp.status_code == 403:
             print_test("G) AuthZ Denial", "PASS", "Correctly rejected (403)")
             return True
        
        print_test("G) AuthZ Denial", "FAIL", f"Expected 403, got {resp.status_code} (Ensure API Key has restricted allowed_agents)")
        return False
    except Exception as e:
        print_test("G) AuthZ Denial", "FAIL", f"Error: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Staging Smoke Tests for Gov-AI Backend")
    parser.add_argument("--base-url", required=True, help="Base URL of the backend (e.g., http://localhost:8000)")
    parser.add_argument("--api-key", required=True, help="Valid API key for testing")
    parser.add_argument("--api-key-2", help="Second API key for tenant isolation test (optional)")
    parser.add_argument("--timeout", type=int, default=60, help="Overall timeout in seconds")
    
    args = parser.parse_args()
    
    print(f"{Colors.BLUE}{'='*50}{Colors.RESET}")
    print(f"{Colors.BLUE}Gov-AI Backend Staging Smoke Tests{Colors.RESET}")
    print(f"{Colors.BLUE}Base URL: {args.base_url}{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*50}{Colors.RESET}\n")
    
    results = []
    start_time = time.time()
    
    # Run tests
    results.append(("A) Health", test_health(args.base_url)))
    results.append(("A2) Health Ready", test_health_ready(args.base_url)))
    results.append(("B) Metrics", test_metrics(args.base_url)))
    results.append(("C) Auth", test_auth_fail(args.base_url)))
    
    d_pass, tenant_d = test_blocking_chat(args.base_url, args.api_key)
    results.append(("D) Blocking Chat", d_pass))
    
    e_pass, tenant_e = test_streaming_chat(args.base_url, args.api_key)
    results.append(("E) Streaming Chat", e_pass))
    
    results.append(("F) Tenant Isolation", test_tenant_isolation(args.base_url, args.api_key, args.api_key_2)))

    results.append(("G) AuthZ Denial", test_authz_denial(args.base_url, args.api_key)))
    
    elapsed = time.time() - start_time
    
    # Summary
    print(f"\n{Colors.BLUE}{'='*50}{Colors.RESET}")
    print(f"{Colors.BLUE}SMOKE TEST SUMMARY{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*50}{Colors.RESET}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    print(f"PASSED: {passed}/{total}")
    print(f"FAILED: {total - passed}/{total}")
    print(f"TIME: {elapsed:.2f}s")
    
    if passed == total:
        print(f"{Colors.GREEN}STATUS: ✅ ALL TESTS PASSED{Colors.RESET}")
        return 0
    else:
        print(f"{Colors.RED}STATUS: ❌ SOME TESTS FAILED{Colors.RESET}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
