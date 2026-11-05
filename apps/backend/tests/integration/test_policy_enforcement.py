
import pytest

pytestmark = pytest.mark.integration
from unittest.mock import MagicMock, patch, AsyncMock
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue, MatchAny, Range, VectorParams, Distance
from app.core.policy.manager import PolicyManager
from app.core.policy.types import UserContext
from app.schemas.chat import RetrievalFilters
from app.core.policy.contract_validator import validate_point_payload
from app.core.rag.retrieve import retrieve
from app.core.rag.evidence import EvidenceGate
from app.core.rag.router import HandoffRouter
from fastapi import HTTPException

@pytest.fixture
def qdrant_client():
    # In-memory Qdrant for fast integration testing
    client = QdrantClient(":memory:")
    client.recreate_collection(
        collection_name="test_collection",
        vectors_config={"dense": VectorParams(size=768, distance=Distance.COSINE)}
    )
    return client

@pytest.fixture
def seeded_qdrant(qdrant_client):
    """
    Seed Qdrant with specific payloads testing:
    - Tenant Isolation (T1 vs T2)
    - Doc Types (Law vs Meeting)
    - Scope (Public vs Internal vs Restricted)
    - Security Level (1, 2, 3)
    - Department (HR, FIN)
    """
    points = [
        # T1 Public Law
        PointStruct(id=1, vector={"dense": [0.1]*768}, payload={"tenant_id": "T1", "doc_type": "law", "scope": "public", "security_level": 1, "contains_pii": False}),
        # T1 Internal Meeting HR (Sec 2)
        PointStruct(id=2, vector={"dense": [0.1]*768}, payload={"tenant_id": "T1", "doc_type": "meeting_transcript", "scope": "internal", "security_level": 2, "department_id": "HR"}),
        # T2 Public Law (Cross Tenant)
        PointStruct(id=3, vector={"dense": [0.1]*768}, payload={"tenant_id": "T2", "doc_type": "law", "scope": "public", "security_level": 1, "contains_pii": False}),
        # T1 Restricted (Sec 3) - Valid Min Level
        PointStruct(id=4, vector={"dense": [0.1]*768}, payload={"tenant_id": "T1", "doc_type": "law", "scope": "restricted", "security_level": 3}),
        # T1 Restricted (Sec 4) - Higher Level
        PointStruct(id=5, vector={"dense": [0.1]*768}, payload={"tenant_id": "T1", "doc_type": "law", "scope": "restricted", "security_level": 4}),
        # T1 Internal Meeting FIN (Cross Dept)
        PointStruct(id=6, vector={"dense": [0.1]*768}, payload={"tenant_id": "T1", "doc_type": "meeting_transcript", "scope": "internal", "security_level": 2, "department_id": "FIN"}),
    ]
    
    # Audit payloads with Contract Validator before inserting
    for p in points:
        errors = validate_point_payload(p.payload)
        assert not errors, f"Seed point {p.id} failed contract: {errors}"
        
    qdrant_client.upsert("test_collection", points)
    return qdrant_client

@pytest.mark.asyncio
async def backend_retrieve(client, tenant_id: str, context_filters: RetrievalFilters = None, user_ctx: UserContext = None):
    """
    Simulates the Backend Retrieval Pipeline using REAL retrieve function.
    Mocks SQL and Embedding to isolate Vector/Policy logic.
    """
    # 1. Prepare Mocks
    mock_db = AsyncMock()
    
    # Mock SQL Fetch to return chunks for whatever IDs were found
    async def mock_fetch_chunks(db, tenant_id, chunk_ids, security_level):
        return [{"chunk_id": cid, "document_id": f"doc_{cid}", "chunk_text": f"Content {cid}"} for cid in chunk_ids]
    
    # Mock Doc Meta
    async def mock_fetch_docs(db, tenant_id, document_ids):
        return {did: {"title": f"Title {did}", "file_url": f"http://{did}"} for did in document_ids}

    # Mock Embed
    async def mock_embed(text):
        return [0.1] * 768

    # Patch dependencies
    # We patch app.core.db_vector.qdrant_client to use our seeded client
    # We patch embed_query
    # We patch fetch_chunks
    
    # Mock Async Query Wrapper to bridge Sync Qdrant Client (Memory)
    async def mock_query_points_safe(**kwargs):
        # Remove timeout_s arg which QdrantClient doesn't accept
        kwargs.pop("timeout_s", None)
        return client.query_points(**kwargs)

    # Patch dependencies
    with patch("app.core.db_vector._qdrant_query_points_safe", side_effect=mock_query_points_safe), \
         patch("app.core.db_vector.COLLECTION_NAME", "test_collection"), \
         patch("app.core.rag.retrieve.embed_query", side_effect=mock_embed), \
         patch("app.core.rag.retrieve.fetch_chunks_by_ids", side_effect=mock_fetch_chunks), \
         patch("app.core.rag.retrieve._fetch_documents_meta_bulk", side_effect=mock_fetch_docs), \
         patch("app.core.rag.retrieve.is_code_query", return_value=False):
         
         user_context_dict = {}
         security_level = 1 # Default
         
         if user_ctx:
             user_context_dict = {
                 "department_id": user_ctx.department_id,
                 "geo_code": user_ctx.geo_code,
             }
             # Handle security_level safely
             sl = getattr(user_ctx, "security_level", None)
             if sl is not None:
                 security_level = sl
         
         res = await retrieve(
             db=mock_db,
             tenant_id=tenant_id,
             agent_id="generic_agent",
             query="test query", 
             top_k=10,
             filters=context_filters,
             user_security_level=security_level,
             user_context=user_context_dict
         )
         return [int(c["chunk_id"]) for c in res.chunks]

# --- TESTS ---

@pytest.mark.asyncio
async def test_tenant_isolation(seeded_qdrant):
    # Mock Policy for T1 Public
    with patch("app.core.rag.retrieve.PolicyManager.enforce_filters") as mock_policy:
        mock_policy.return_value = {
            "filters": {"tenant_id": "T1", "scope": "public"},
            "policy_meta": {}
        }
        
        # Retrieve for T1
        ids_t1 = await backend_retrieve(seeded_qdrant, "T1")
        # Should see id=1 (Public)
        assert 1 in ids_t1
        assert 3 not in ids_t1 # T2
    
    # Mock Policy for T2
    with patch("app.core.rag.retrieve.PolicyManager.enforce_filters") as mock_policy:
        mock_policy.return_value = {
            "filters": {"tenant_id": "T2", "scope": "public"},
            "policy_meta": {}
        }
        ids_t2 = await backend_retrieve(seeded_qdrant, "T2") # T2 has id=3
        assert 3 in ids_t2
        assert 1 not in ids_t2

@pytest.mark.asyncio
async def test_internal_scope_department_isolation(seeded_qdrant):
    """
    Scope INTERNAL must match department_id.
    """
    # User is in HR. Should see HR meetings (id=2).
    # Should NOT see FIN meetings (id=6).
    
    ctx = UserContext(tenant_id="T1", department_id="HR")
    filters = RetrievalFilters(doc_types=["meeting_transcript"], doc_type="meeting_transcript") 
    # Note: Policy enforces scope=internal for meeting_transcript usually? 
    # Or we request scope="internal" via filters?
    # Let's request scope="internal" via filters dict simulation?
    # RetrievalFilters doesn't have scope field exposed to API usually (it's internal policy).
    # But PolicyManager maps doc_type 'meeting_transcript' -> scope 'internal'.
    # Assuming PolicyManager works as configured.
    # If not configured, we manually inject scope in filters for test purposes?
    # No, retrieve use RetrievalFilters. 
    # Let's assume generic_agent policy allows 'meeting_transcript' and maps it to proper scope if needed, 
    # OR if scope is determined by doc_type.
    # Actually, in this codebase, PolicyManager decides filters based on Context + Request.
    # If we want to find Internal docs, we ask for them.
    # Let's assume we ask for doc_type='meeting_transcript'.
    
    # Mocking PolicyManager to return scope=internal for this test? 
    # Or relying on real PolicyManager.
    # Real PolicyManager uses `generic_agent` policy.
    # We haven't seen `generic_agent` policy config.
    # But strictly, the Builder enforces: IF scope=internal in filters -> Check Dept.
    # We can inject "filters={'scope': 'internal', ...}" via `context_filters` if PolicyManager passes them through.
    # PolicyManager often merges request filters.
    # BUT RetrievalFilters schema doesn't have 'scope'.
    # So we cannot pass 'scope' from request.
    # Policy must inject it.
    # For this test, let's mock PolicyManager.enforce_filters to return scope='internal'.
    
    with patch("app.core.rag.retrieve.PolicyManager.enforce_filters") as mock_policy:
        # Return filters with scope=internal
        mock_policy.return_value = {
            "filters": {"scope": "internal", "department_id": "HR", "tenant_id": "T1"}, 
            "policy_meta": {}
        }
        
        ids = await backend_retrieve(seeded_qdrant, "T1", context_filters=None, user_ctx=ctx)
        assert 2 in ids # HR Meeting
        assert 6 not in ids # FIN Meeting

@pytest.mark.asyncio
async def test_restricted_security_level(seeded_qdrant):
    """
    Restricted docs require security check.
    """
    # Mock Policy to return scope=restricted
    with patch("app.core.rag.retrieve.PolicyManager.enforce_filters") as mock_policy:
        
        # Case 1: Clearance 3 -> Matches Level 3 (id=4). Matches 5 (Level 4)? NO.
        mock_policy.return_value = {
            "filters": {"scope": "restricted", "tenant_id": "T1"},
            "policy_meta": {}
        }
        ctx_3 = UserContext(tenant_id="T1", security_level=3)
        ids_3 = await backend_retrieve(seeded_qdrant, "T1", user_ctx=ctx_3)
        assert 4 in ids_3
        assert 5 not in ids_3 # Level 4

        # Case 2: Clearance 4 -> Matches 4 and 5
        ctx_4 = UserContext(tenant_id="T1", security_level=4)
        ids_4 = await backend_retrieve(seeded_qdrant, "T1", user_ctx=ctx_4)
        assert 4 in ids_4
        assert 5 in ids_4

        # Case 3: Clearance 2 -> Denied (HTTP 403)
        # backend_retrieve catches 403 and returns empty
        ctx_2 = UserContext(tenant_id="T1", security_level=2)
        
        with pytest.raises(HTTPException) as excinfo:
            await backend_retrieve(seeded_qdrant, "T1", user_ctx=ctx_2)
        assert excinfo.value.status_code == 403

def test_contract_validator_catches_legacy():
    payload = {"tenant_id": "T1", "doc_category": "law"} # Legacy key
    errors = validate_point_payload(payload)
    assert "Found legacy keys" in errors[0]
    assert "missing strict keys" in str(errors).lower()


def test_evidence_low_score_refusal():
    """
    Unit test for EvidenceGate threshold.
    """
    gate = EvidenceGate()
    
    # Case 1: High Score -> Pass
    chunks_high = [{"chunk_id": "1", "score": 0.8, "payload": {"file_url": "http://ok"}}]
    assert gate.evaluate(chunks_high).status == "pass"
    
    # Case 2: Low Score -> Refuse
    chunks_low = [{"chunk_id": "2", "score": 0.35, "payload": {"file_url": "http://ok"}}]
    d = gate.evaluate(chunks_low)
    assert d.status == "refuse"
    assert "Low confidence" in d.reason

    # Case 3: No Source -> Refuse
    chunks_no_src = [{"chunk_id": "3", "score": 0.9, "payload": {}}]
    d_src = gate.evaluate(chunks_no_src)
    assert d_src.status == "refuse"
    assert "lacks citation" in d_src.reason

def test_handoff_logic():
    """
    Unit test for HandoffRouter.
    """
    # Case 1: Law query -> Legal Agent
    assert HandoffRouter.route("Tìm hiểu về Luật Đất đai", "generic_agent") == "legal_agent"
    
    # Case 2: Meeting query -> Meeting Agent
    assert HandoffRouter.route("Biên bản cuộc họp tuần trước", "generic_agent") == "meeting_agent"
    
    # Case 3: Generic -> None
    assert HandoffRouter.route("Thời tiết hôm nay", "generic_agent") is None
    
    # Case 4: Already on correct agent -> None
    assert HandoffRouter.route("Luật Đất đai", "legal_agent") is None

def test_rrf_compatibility():
    """
    Verify that RRF scores (small values) pass if kind is RRF/Fused.
    """
    gate = EvidenceGate()
    
    # Case 1: Low score (0.02) but RRF kind -> Pass
    chunks_rrf = [{
        "chunk_id": "1", 
        "score": 0.02, 
        "payload": {"file_url": "http://ok", "_score_kind": "rrf_fusion"}
    }]
    assert gate.evaluate(chunks_rrf).status == "pass"

    # Case 2: Low score (0.02) but Cosine kind -> Refuse
    chunks_cosine = [{
        "chunk_id": "2", 
        "score": 0.02, 
        "payload": {"file_url": "http://ok", "_score_kind": "cosine"}
    }]
    decision = gate.evaluate(chunks_cosine)
    assert decision.status == "refuse"
    assert "Low confidence" in decision.reason
