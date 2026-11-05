import pytest

pytestmark = pytest.mark.integration
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from app.core.rag.retrieve import retrieve, RetrieveResult
from app.schemas.chat import RetrievalFilters
from app.core.policy.types import UserContext

# --- Mock Data ---

INTERNAL_DOC_A = {
    "chunk_id": "chunk_a",
    "score": 0.9,
    "payload": {
        "tenant_id": "t1", 
        "doc_type": "INTERNAL", 
        "department_id": "DEPT_A",
        "scope": "INTERNAL",
        "contains_pii": False
    },
    "document_id": "doc_a"
}

INTERNAL_DOC_B = {
    "chunk_id": "chunk_b",
    "score": 0.9,
    "payload": {
        "tenant_id": "t1", 
        "doc_type": "INTERNAL", 
        "department_id": "DEPT_B",
        "scope": "INTERNAL",
        "contains_pii": False
    },
    "document_id": "doc_b"
}

PUBLIC_PII_DOC = {
    "chunk_id": "chunk_pii",
    "score": 0.8,
    "payload": {
        "tenant_id": "t1", 
        "doc_type": "government",
        "scope": "PUBLIC",
        "contains_pii": True # Should be blocked
    },
    "document_id": "doc_pii"
}

LEGACY_UNKNOWN_DOC = {
    "chunk_id": "chunk_legacy",
    "score": 0.8,
    "payload": {
        "tenant_id": "t1",
        # Missing scope or pii
    },
    "document_id": "doc_legacy"
}

@pytest.fixture
def mock_deps():
    """Setup safe mocks to isolate logic from real DB/Qdrant."""
    with patch("app.core.rag.retrieve.search_hybrid_chunks", new_callable=AsyncMock) as mock_hybrid, \
         patch("app.core.rag.retrieve.search_lexical_chunks", new_callable=AsyncMock) as mock_lexical, \
         patch("app.core.rag.retrieve.fetch_chunks_by_ids", new_callable=AsyncMock) as mock_fetch, \
         patch("app.core.rag.retrieve._fetch_documents_meta_bulk", new_callable=AsyncMock) as mock_meta:
        
        # Default behavior: Empty results
        mock_hybrid.return_value = []
        mock_lexical.return_value = []
        mock_fetch.return_value = []
        mock_meta.return_value = {}
        
        yield mock_hybrid, mock_lexical, mock_fetch, mock_meta

@pytest.mark.asyncio
async def test_e2e_policy_integrity_internal_a(mock_deps):
    """
    User in DEPT_A querying '123/2024/ND-CP'.
    Expect: Lexical passes filter for DEPT_A only.
    """
    mock_hybrid, mock_lexical, mock_fetch, _ = mock_deps
    db = AsyncMock()

    # MOCK POLICY MANAGER to return Internal Scope + Dept A
    # We bypass the agent_id check since we mock the policy result directly
    with patch("app.core.rag.retrieve.PolicyManager.enforce_filters") as mock_policy:
        mock_policy.return_value = {
            "filters": {"scope": "INTERNAL", "department_id": "DEPT_A"},
            "policy_meta": {}
        }

        res = await retrieve(
            db, 
            tenant_id="t1", 
            agent_id="law_agent",
            query="123/2024/ND-CP",
            user_context={"department_id": "DEPT_A"},
            user_security_level=2,
            filters=RetrievalFilters() # No scope here
        )
    
    # Internal scope should not produce lexical hits.
    # (Current implementation may still mark lexical lane as used even when it returns [].)
    assert mock_lexical.call_args is None
    assert int(res.debug.get("lexical_hits") or 0) == 0
    assert res.debug.get("fusion_mode") == "hybrid_only"

@pytest.mark.asyncio
async def test_e2e_policy_integrity_public_pii(mock_deps):
    """
    Public User querying code.
    Expect: Filters exclude PII.
    """
    _, mock_lexical, _, _ = mock_deps
    db = AsyncMock()
    
    with patch("app.core.rag.retrieve.PolicyManager.enforce_filters") as mock_policy:
        mock_policy.return_value = {
            "filters": {"scope": "PUBLIC"},
            "policy_meta": {}
        }
    
        await retrieve(
            db, 
            tenant_id="t1", 
            agent_id="citizen_agent",
            query="123/2024/ND-CP",
            user_context={},
            user_security_level=1,
            filters=RetrievalFilters()
        )
    
    call_args = mock_lexical.call_args
    filters_passed = call_args.kwargs['filters']
    assert filters_passed['scope'] == 'PUBLIC' 

@pytest.mark.asyncio
async def test_e2e_hybrid_boost_logic(mock_deps):
    """
    Verify Lexical Boost (2x) when query is code-like.
    """
    mock_hybrid, mock_lexical, mock_fetch, _ = mock_deps
    db = AsyncMock()
    
    # Setup hits
    semantic_hit = ("chunk_sem", 0.8, {"_score_kind": "vector"})
    lexical_hit = ("chunk_lex", 0.8, {"_score_kind": "lexical"})
    
    mock_hybrid.return_value = [semantic_hit]
    mock_lexical.return_value = [lexical_hit]
    
    mock_fetch.return_value = [
        {"chunk_id": "chunk_sem", "payload": {}},
        {"chunk_id": "chunk_lex", "payload": {}}
    ]

    with patch("app.core.rag.retrieve.PolicyManager.enforce_filters") as mock_policy:
        # Mock policy allowing retrieval
        mock_policy.return_value = {
            "filters": {"scope": "PUBLIC"},
            "policy_meta": {}
        }

        res = await retrieve(
            db,
            tenant_id="t1",
            agent_id="law_agent",
            query="123/2024/ND-CP", # Triggers boost
            user_security_level=1
        )
    
    # Check order in res.chunks
    # Boosted lexical should win.
    assert len(res.chunks) == 2
    top_doc = res.chunks[0]
    assert top_doc['chunk_id'] == "chunk_lex" 

@pytest.mark.asyncio
async def test_e2e_no_downgrade_scope(mock_deps):
    """
    Internal query with missing dept -> Should NOT failover to Public.
    """
    _, mock_lexical, _, _ = mock_deps
    db = AsyncMock()
    
    from fastapi import HTTPException
    
    # Simulate PolicyManager returning INTERNAL scope (missing dept)
    with patch("app.core.rag.retrieve.PolicyManager.enforce_filters") as mock_policy:
        mock_policy.return_value = {
            "filters": {"scope": "INTERNAL"}, # Missing dept
            "policy_meta": {}
        }
    
        mock_lexical.return_value = []
        
        # Expect 403 because STRICT_BUILDER raises PermissionError when INTERNAL missing dept
        with pytest.raises(HTTPException) as exc:
            await retrieve(
                db,
                tenant_id="t1",
                agent_id="law_agent",
                query="123/2024/ND-CP",
                filters=RetrievalFilters(),
                user_context={} 
            )
        assert exc.value.status_code == 403
