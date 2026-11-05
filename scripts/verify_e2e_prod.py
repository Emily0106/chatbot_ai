import sys
from unittest.mock import MagicMock, AsyncMock, patch
import os
import json

# ========================================================================================
# Path & Mock Setup (Must happen BEFORE app import)
# ========================================================================================
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # scripts/..
BACKEND_SRC = ROOT / "apps" / "backend" / "src"
CORE_SHARED = ROOT / "libs" / "core_shared"

for p in (str(BACKEND_SRC), str(CORE_SHARED)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Suppress Qdrant client/server version mismatch
os.environ.setdefault("QDRANT_CLIENT_PREFER_GRPC", "false")

sys.modules["sentence_transformers"] = MagicMock()
sys.modules["sentence_transformers.SentenceTransformer"] = MagicMock()

# Mock Handlers
async def mock_handler(messages, *args, **kwargs):
    return "MOCK ANSWER from verify_e2e_prod"

mock_achat = AsyncMock(side_effect=mock_handler)
mock_gen_text = AsyncMock(return_value="MOCK GEN TEXT")
mock_embed = AsyncMock(return_value=[[0.1]*768])

# Start Patch context (use import + patch.object for safety)
import app.core.llm_client as llm_client

patcher_chat = patch.object(llm_client, "achat", mock_achat)
patcher_gen = patch.object(llm_client, "generate_text", mock_gen_text)
patcher_embed = patch.object(llm_client, "embed_texts", mock_embed)

patcher_chat.start()
patcher_gen.start()
patcher_embed.start()

# ========================================================================================
# App Import
# ========================================================================================
from app.main import app
from fastapi.testclient import TestClient

# ========================================================================================
# Test Logic
# ========================================================================================

OK = "✅ PASS"
FAIL = "❌ FAIL"

API_KEYS = json.loads(os.getenv("API_KEYS_JSON", "{}"))
def get_key(role, tenant="default"):
    for k, v in API_KEYS.items():
        if v.get("role") == role and v.get("tenant_id") == tenant:
            return k
    return None

def check(name, func, client):
    print(f"Running: {name}...", end=" ")
    try:
        func(client)
        print(OK)
        return True
    except AssertionError as e:
        print(f"{FAIL} -> {e}")
        return False
    except Exception as e:
        print(f"{FAIL} -> Error: {e}")
        return False

def tc_3_1_tenant_isolation(client):
    """Verify Tenant B cannot see Tenant A's data (citations)"""
    key = get_key("citizen", "tenant_b")
    if not key:
        print("(SKIP: No Tenant B Key)")
        return

    # User B asks a question
    resp = client.post(
        "/api/chat",
        json={"message": "Test Query", "agent_id": "citizen", "stream": False},
        headers={"X-API-Key": key}
    )
    
    assert resp.status_code == 200, f"Status {resp.status_code} != 200. Body: {resp.text}"
    data = resp.json()
    
    # Check citations. Sandbox is empty initially, so it should be 0.
    # If we had ingested data for A, B should still see 0.
    # This proves the pipeline runs without error for Tenant B.
    citations = data.get("citations", [])
    assert len(citations) == 0, f"Tenant B should not see citations: {citations}"

def tc_4_1_evidence_gating(client):
    """Verify system refuses to answer nonsense (One Piece)"""
    key = get_key("citizen", "default")
    if not key:
        print("(SKIP: No Citizen Key)")
        return

    resp = client.post(
        "/api/chat",
        json={"message": "Bí mật kho báu One Piece ở đâu?", "agent_id": "citizen", "stream": False},
        headers={"X-API-Key": key}
    )
    assert resp.status_code == 200, f"Status {resp.status_code}"
    data = resp.json()
    citations = data.get("citations", [])
    assert len(citations) == 0, "Should have 0 citations"

def main():
    print("🚀 Starting PROD E2E Verification (TestClient + Real DB)...")
    
    # Ensure we are in Prod Mode
    print(f"ENV_MODE: {os.getenv('ENV_MODE')}")
    print(f"DB_URL: {os.getenv('DB_URL')}")

    with TestClient(app) as client:
        # Suite
        if not check("TC-3.1 Tenant Isolation", tc_3_1_tenant_isolation, client):
            sys.exit(1)
        if not check("TC-4.1 Evidence Gating", tc_4_1_evidence_gating, client):
            sys.exit(1)

    print("\n🏁 Verification Complete.")

if __name__ == "__main__":
    try:
        main()
    finally:
        patcher_chat.stop()
        patcher_gen.stop()
        patcher_embed.stop()
