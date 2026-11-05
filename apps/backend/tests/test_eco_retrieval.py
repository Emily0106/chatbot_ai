import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import time
from app.core.rag.retrieve import retrieve
from app.core.rag import rerank as rerank_module

@pytest.mark.asyncio
async def test_eco_mode_skips_rerank():
    """Verify that RETRIEVAL_MODE='eco' skips rerank entirely."""
    with patch("app.core.rag.retrieve.settings") as mock_settings:
        mock_settings.RETRIEVAL_MODE = "eco"
        mock_settings.RERANK_ENABLED = True
        
        # Mock dependencies
        db = AsyncMock()
        
        with patch("app.core.rag.retrieve.search_hybrid_chunks") as mock_search:
            # Return some dummy chunks
            mock_search.return_value = [("c1", 0.9, {}), ("c2", 0.8, {})]
            
            with patch("app.core.rag.retrieve.rerank") as mock_rerank:
                res = await retrieve(
                    db, 
                    tenant_id="t1", 
                    agent_id="a1", 
                    query="test",
                    enable_rerank=True # Request rerank, but mode=eco should override
                )
                
                # Verify rerank was NOT called
                mock_rerank.assert_not_called()
                assert res.debug["rerank_skipped"] is True
                assert res.debug["rerank_skip_reason"] == "mode_eco"

@pytest.mark.asyncio
async def test_gov_mode_calls_rerank():
    """Verify that RETRIEVAL_MODE='gov' calls rerank."""
    with patch("app.core.rag.retrieve.settings") as mock_settings:
        mock_settings.RETRIEVAL_MODE = "gov"
        mock_settings.RERANK_ENABLED = True
        
        db = AsyncMock()
        
        with patch("app.core.rag.retrieve.search_hybrid_chunks") as mock_search:
            mock_search.return_value = [("c1", 0.9, {}), ("c2", 0.8, {})]
            
            with patch("app.core.rag.retrieve.rerank") as mock_rerank:
                # Mock rerank return
                mock_rerank.return_value = [{"chunk_id": "c1", "rerank_score": 2.0}]
                
                res = await retrieve(
                    db, 
                    tenant_id="t1", 
                    agent_id="a1", 
                    query="test",
                    enable_rerank=True
                )
                
                # Verify rerank WAS called
                mock_rerank.assert_called_once()
                # Gov mode should NOT try_acquire (wait indefinitely)
                # But my implementation passes try_acquire=(mode == "auto" and try_acquire)
                # So for gov, try_acquire should be False
                call_kwargs = mock_rerank.call_args.kwargs
                assert call_kwargs["try_acquire"] is False
                assert call_kwargs["deadline_ts"] is not None # Gov still has deadline passed? Yes, logic says: deadline_ts if mode in ("auto", "gov") else None

@pytest.mark.asyncio
async def test_auto_mode_deadline_exceeded():
    """Verify that RETRIEVAL_MODE='auto' skips rerank if deadline exceeded."""
    with patch("app.core.rag.retrieve.settings") as mock_settings:
        mock_settings.RETRIEVAL_MODE = "auto"
        mock_settings.RERANK_ENABLED = True
        mock_settings.RETRIEVAL_DEADLINE_MS = 100 # Very short deadline
        
        db = AsyncMock()
        
        with patch("app.core.rag.retrieve.search_hybrid_chunks") as mock_search:
            mock_search.return_value = [("c1", 0.9, {})]
            
            # Simulate time passing to exceed deadline
            with patch("app.core.rag.retrieve.time.perf_counter") as mock_time:
                # First call sets t0
                # Second call checks deadline
                mock_time.side_effect = [100.0, 100.2] # 200ms elapsed > 100ms deadline
                
                with patch("app.core.rag.retrieve.rerank") as mock_rerank:
                    res = await retrieve(
                        db, 
                        tenant_id="t1", 
                        agent_id="a1", 
                        query="test",
                        enable_rerank=True
                    )
                    
                    mock_rerank.assert_not_called()
                    assert res.debug["rerank_skipped"] is True
                    assert res.debug["rerank_skip_reason"] == "deadline_exceeded"

def test_circuit_breaker_logic():
    """Unit test for circuit breaker in rerank.py."""
    # Reset state
    rerank_module._fail_count = 0
    rerank_module._open_until = 0.0
    rerank_module._BREAKER_FAILS = 2
    rerank_module._BREAKER_COOLDOWN_S = 10.0
    
    # 1. Fail once
    rerank_module._record_fail(100.0)
    assert rerank_module._fail_count == 1
    assert rerank_module._breaker_open(100.0) is False
    
    # 2. Fail twice -> Open
    rerank_module._record_fail(100.0)
    assert rerank_module._fail_count == 0 # Reset after open
    assert rerank_module._open_until == 110.0
    assert rerank_module._breaker_open(105.0) is True
    
    # 3. Cooldown passed -> Close
    assert rerank_module._breaker_open(111.0) is False
    
    # 4. Success -> Reset
    rerank_module._record_success()
    assert rerank_module._fail_count == 0
    assert rerank_module._open_until == 0.0
