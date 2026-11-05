import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.core.rag import pipeline
from app.config import settings

@pytest.mark.asyncio
async def test_fast_strict_fallback(monkeypatch):
    """
    Simulate a FAST lane failure (gating fail) and verify fallback to STRICT.
    """
    # Enable FAST lane
    monkeypatch.setattr(settings, "ENABLE_FAST_LANE", True)
    
    # Mock retrieve to return something so we proceed to gate
    mock_chunks = [{"chunk_id": "c1", "chunk_text": "text", "document_id": "d1"}]
    mock_retrieve = AsyncMock(return_value=MagicMock(chunks=mock_chunks, doc_map={}, debug={"code_like": False}))
    monkeypatch.setattr(pipeline, "retrieve", mock_retrieve)

    # Mock decide_lane to return FAST
    mock_decide = MagicMock(return_value=MagicMock(lane="fast", reason="simple"))
    monkeypatch.setattr(pipeline, "decide_lane", mock_decide)

    # Mock _evaluate_evidence to FAIL first time (FAST), SUCCEED second time (strict)
    # We need to control the side effect of _evaluate_evidence
    # It is called inside _attempt.
    
    # Actually, simpler to mock _attempt? 
    # But _attempt is a local async function inside rag_retrieve. We can't mock it easily.
    # We have to mock the components strictly.
    
    # Strategy: Mock `retrieve` (done).
    # Mock `_maybe_rerank` to pass.
    # Mock `_evaluate_evidence` to return (False, reason="low_evidence") first call
    # and (True, ...) second call?
    
    # Problem: `rag_retrieve` logic is complex.
    # Let's inspect calls to `_attempt`.
    # First call: lane="fast". 
    # Second call: lane="strict" (fallback).
    
    call_count = 0
    def side_effect_evidence(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First attempt (FAST) -> Fail gate
            return False, {"reason": "low_evidence"}
        else:
            # Second attempt (Fallback) -> Pass gate
            return True, {"reason": "ok"}
            
    monkeypatch.setattr(pipeline, "_evaluate_evidence", side_effect_evidence)
    
    # Run pipeline
    res = await pipeline.rag_retrieve(
        db=AsyncMock(),
        tenant_id="t1",
        agent_id="a1",
        query="hi",
        enable_rerank=True # Request rerank (will be skipped in FAST)
    )
    
    # Verify fallback happened
    attempts = res.meta.get("attempts", [])
    assert len(attempts) >= 2
    
    # Attempt 0: FAST
    assert attempts[0].get("evidence_ok") is False
    # Check if rerank was skipped (FAST logic) -> FAST_SKIP_RERANK default is True
    # We passed enable_rerank=True, but effective should be False in FAST lane
    assert attempts[0].get("eff_rerank") is False 
    
    # Attempt 1: Fallback (STRICT)
    assert attempts[1].get("fallback_from") == "fast"
    assert attempts[1].get("eff_rerank") is True # Should respect original request or strict default
    assert attempts[1].get("evidence_ok") is True

    # Check output
    assert res.context # Should be built from successful attempt
