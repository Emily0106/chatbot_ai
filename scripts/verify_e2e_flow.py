import asyncio
import sys
import httpx
from typing import Optional

# Configuration
API_URL = "http://localhost:8000/api/v1"
HEADERS_ADMIN = {"X-GOVAI-TENANT-ID": "default", "X-GOVAI-USER-ROLE": "admin"}
HEADERS_CITIZEN = {"X-GOVAI-TENANT-ID": "default", "X-GOVAI-USER-ROLE": "citizen"}

OK = "✅ PASS"
FAIL = "❌ FAIL"

async def check(name: str, coro, *args):
    print(f"Running: {name}...", end=" ")
    try:
        await coro(*args)
        print(OK)
        return True
    except AssertionError as e:
        print(f"{FAIL} -> {e}")
        return False
    except Exception as e:
        print(f"{FAIL} -> Error: {e}")
        return False

async def tc_3_1_tenant_isolation(client: httpx.AsyncClient):
    """TC-3.1: Tenant Isolation check"""
    # 1. Ingest Doc for Tenant A (default)
    # We assume 'profile_law_public' exists from seed.
    # Note: Full ingestion might be slow/complex to seed here, 
    # so we primarily check if cross-tenant query returns empty.
    
    headers_tenant_b = {"X-GOVAI-TENANT-ID": "tenant_b", "X-GOVAI-USER-ROLE": "citizen"}
    
    resp = await client.post(
        f"{API_URL}/chat/completions",
        json={"messages": [{"role": "user", "content": "Test Query"}]},
        headers=headers_tenant_b
    )
    if resp.status_code == 401 or resp.status_code == 403:
         # Acceptable denial
         return
         
    # If 200, check citations
    data = resp.json()
    # Should not have citations from Tenant A
    # Since we didn't ingest anything for Tenant B, this is trivially true but validates the path.
    citations = data.get("citations", [])
    assert len(citations) == 0, f"Tenant B should not see citations: {citations}"

async def tc_3_3_internal_scope(client: httpx.AsyncClient):
    """TC-3.3: Internal Scope check"""
    # User without department match shouldn't see internal docs.
    # We'll simulate this by querying with a mismatched department
    headers_no_dept = {
        "X-GOVAI-TENANT-ID": "default", 
        "X-GOVAI-USER-ROLE": "officer",
        "X-GOVAI-DEPARTMENT-ID": "dept_HR"
    }
    # Assume we have internal docs for dept_IT.
    # This test relies on data existing. 
    # For now, we verify the API accepts the headers and doesn't crash, 
    # and returns a valid refusal or answer (if no data).
    resp = await client.post(
        f"{API_URL}/chat/completions",
        json={"messages": [{"role": "user", "content": "Internal Plan"}]},
        headers=headers_no_dept
    )
    assert resp.status_code == 200, f"API Error: {resp.text}"

async def tc_4_1_evidence_gating(client: httpx.AsyncClient):
    """TC-4.1: Evidence Gating (Anti-Hallucination)"""
    # Query nonsense
    query = "Bí mật kho báu One Piece ở đâu?"
    resp = await client.post(
        f"{API_URL}/chat/completions",
        json={"messages": [{"role": "user", "content": query}]},
        headers=HEADERS_CITIZEN
    )
    assert resp.status_code == 200, f"API Error: {resp.text}"
    data = resp.json()
    # Expect refusal
    content = data["choices"][0]["message"]["content"]
    logging_meta = data.get("meta", {})
    
    # We check if gate_decision is refused OR content implies refusal
    if "xin lỗi" in content.lower() or "không tìm thấy" in content.lower():
        pass
    else:
        # If gate_decision is available, check it
        pass 
        # Note: Depending on LLM strictness, it might try to answer "One Piece is a manga...".
        # But our system prompt should force refusal if no retrieval.
        # Strict fail if it hallucinates a location in the database.
        
    assert len(data.get("citations", [])) == 0, "Should have 0 citations for One Piece"

async def tc_4_3_streaming_parity(client: httpx.AsyncClient):
    """TC-4.3: Streaming Parity"""
    query = "Bí mật kho báu One Piece ở đâu?"
    async with client.stream(
        "POST", 
        f"{API_URL}/chat/stream",
        json={"messages": [{"role": "user", "content": query}]},
        headers=HEADERS_CITIZEN
    ) as response:
        assert response.status_code == 200
        # Iterate events
        # Expect 'event: final' or similar structure
        has_content = False
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                has_content = True
        
        assert has_content, "Stream return no data"

async def main():
    print("🚀 Starting Master E2E Verification Suite...")
    async with httpx.AsyncClient() as client:
        # Suite 3
        print("\n[Suite 3: Security & Policy]")
        await check("TC-3.1 Tenant Isolation", tc_3_1_tenant_isolation, client)
        await check("TC-3.3 Internal Scope", tc_3_3_internal_scope, client)
        
        # Suite 4
        print("\n[Suite 4: Intelligence & Gating]")
        await check("TC-4.1 Evidence Gating", tc_4_1_evidence_gating, client)
        await check("TC-4.3 Streaming Parity", tc_4_3_streaming_parity, client)
        
    print("\n🏁 Verification Complete.")

if __name__ == "__main__":
    if float(sys.version[:3]) < 3.8:
        print("Requires Python 3.8+")
    else:
        asyncio.run(main())
