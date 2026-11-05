from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.rag.retrieve import retrieve
from app.schemas.chat import RetrievalFilters
from app.config import settings

@pytest.fixture
def mock_db():
    db = AsyncMock()
    # for lexical raw query
    db.execute.return_value = MagicMock(mappings=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    return db


@pytest.mark.asyncio
async def test_retrieval_expansion_disabled(mock_db):
    """Verify feature flag off = old behavior."""
    with patch("app.core.rag.retrieve.search_hybrid_chunks", new_callable=AsyncMock) as mock_hybrid, \
         patch("app.core.rag.retrieve.search_lexical_chunks", new_callable=AsyncMock) as mock_lexical, \
         patch("app.core.policy.manager.PolicyManager.enforce_filters") as mock_policy:
         
        mock_policy.return_value = {"filters": {}, "policy_meta": {}}
        mock_hybrid.return_value = [("chunk1", 0.9, {})]
        
        # Override settings local to test
        with patch.dict("os.environ", {"ENABLE_QUERY_EXPANSION": "0"}):
            res = await retrieve(
                db=mock_db,
                tenant_id="t1",
                agent_id="a1",
                query="test query",
                top_k=5
            )
        
        # Called exactly once with original query
        mock_hybrid.assert_called_once()
        args, kwargs = mock_hybrid.call_args
        assert kwargs["query"] == "test query"
        assert "query_expanded" not in res.debug or not res.debug["query_expanded"]


@pytest.mark.asyncio
async def test_retrieval_expansion_qdrant_multi_search(mock_db):
    """Verify qdrant multi-search called N times with same filters."""
    with patch("app.core.rag.retrieve.search_hybrid_chunks", new_callable=AsyncMock) as mock_hybrid, \
         patch("app.core.rag.retrieve.QueryExpansionEngine", autospec=True) as MockEngine, \
         patch("app.core.policy.manager.PolicyManager.enforce_filters") as mock_policy:
         
        # Setup mock Policy
        mock_policy.return_value = {"filters": {"doc_type": "PUBLIC"}, "policy_meta": {}}
        
        # Setup mock Engine
        mock_engine_instance = MockEngine.return_value
        mock_pack = MagicMock()
        mock_pack.normalized_query = "normalized query"
        mock_pack.variants = [
            MagicMock(text="variant 1", weight=1.0),
            MagicMock(text="variant 2", weight=0.8)
        ]
        mock_pack.audit = {"expansion_applied": True}
        mock_engine_instance.expand = AsyncMock(return_value=mock_pack)
        
        # Setup mock Hybrid Search Returns
        mock_hybrid.side_effect = [
            [("chunk_a", 0.9, {})], # For variant 1
            [("chunk_b", 0.8, {})]  # For variant 2
        ]
        
        with patch.dict("os.environ", {"ENABLE_QUERY_EXPANSION": "1"}):
            # We need mock_fetch_chunks_by_ids to successfully return an empty list or mock rows so it doesn't fail
            with patch("app.core.rag.retrieve.fetch_chunks_by_ids", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = []
                res = await retrieve(
                    db=mock_db,
                    tenant_id="t1",
                    agent_id="a1",
                    query="original query",
                    top_k=5
                )
        
        # Assert Query Expansion Engine Was Called
        assert res.debug.get("query_expanded") is True
        
        # Hybrid called twice (once for each variant)
        assert mock_hybrid.call_count == 2
        
        calls = mock_hybrid.call_args_list
        q1 = calls[0].kwargs["query"]
        q2 = calls[1].kwargs["query"]
        assert set([q1, q2]) == {"variant 1", "variant 2"}
        
        # Assert same strict filters passed to both calls
        qf1 = calls[0].kwargs["q_filter"]
        qf2 = calls[1].kwargs["q_filter"]
        assert qf1 == qf2


@pytest.mark.asyncio
async def test_retrieval_expansion_lexical_or_bind(mock_db):
    """Verify variant OR query building logic explicitly passes variants to db_lexical."""
    from app.core.db_lexical import search_lexical_chunks
    
    with patch("app.core.db_lexical._execute_sql", new_callable=AsyncMock) as mock_sql:
        mock_sql.return_value = []
        
        variants = [
            {"query": "variant 1", "weight": 1.0},
            {"query": "variant 2", "weight": 0.8}
        ]
        
        await search_lexical_chunks(
            mock_db,
            query="normalized",
            tenant_id="t1",
            variants=variants
        )
        
        # Verify SQL generation includes multiple websearch_to_tsquery bindings
        assert mock_sql.call_count == 1
        sql_query = mock_sql.call_args[0][1]
        params = mock_sql.call_args[0][2]
        
        # OR binding check for FTS with safe regconfig cast
        assert (
            "websearch_to_tsquery(CAST(:cfg AS regconfig), :q0) || "
            "websearch_to_tsquery(CAST(:cfg AS regconfig), :q1)"
        ) in sql_query
        assert ":cfg::regconfig" not in sql_query
        
        # Param correct bind count
        assert "q0" in params
        assert "q1" in params
        assert params["q0"] == "variant 1"
        assert params["q1"] == "variant 2"
