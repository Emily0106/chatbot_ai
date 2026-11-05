import asyncio
import time
import sys
from unittest.mock import MagicMock, patch

# Mock sentence_transformers to avoid slow import/download
sys.modules["sentence_transformers"] = MagicMock()

from app.core.rag.retrieve import retrieve
from app.config import settings
from app.core.rag import rerank as rerank_module

async def test_eco_mode():
    print("\n--- Testing Eco Mode (in pipeline.py) ---")
    settings.RETRIEVAL_MODE = "eco"
    settings.RERANK_ENABLED = True
    
    # Mock retrieve to return chunks
    with patch("app.core.rag.pipeline.retrieve") as mock_retrieve:
        # Provide chunk_text that overlaps with query "test"
        mock_retrieve.return_value = MagicMock(chunks=[{"chunk_id": "1", "score": 0.9, "chunk_text": "this is a test query"}])
        
        # Mock rerank to verify it's skipped
        with patch("app.core.rag.rerank.rerank") as mock_rerank:
            from app.core.rag.pipeline import rag_retrieve
            
            db = MagicMock()
            res = await rag_retrieve(db=db, tenant_id="t1", agent_id="a1", query="test")
            
            if not mock_rerank.called:
                print("PASS: Rerank skipped in Eco mode")
            else:
                print("FAIL: Rerank NOT skipped in Eco mode")

async def test_gov_mode():
    print("\n--- Testing Gov Mode (in pipeline.py) ---")
    settings.RETRIEVAL_MODE = "gov"
    settings.RERANK_ENABLED = True
    
    with patch("app.core.rag.pipeline.retrieve") as mock_retrieve:
        mock_retrieve.return_value = MagicMock(chunks=[{"chunk_id": "1", "score": 0.9, "chunk_text": "this is a test query"}])
        
        # Mock rerank to verify it's called
        with patch("app.core.rag.rerank.rerank") as mock_rerank:
            mock_rerank.return_value = [{"chunk_id": "1", "rerank_score": 0.95}]
            
            from app.core.rag.pipeline import rag_retrieve
            db = MagicMock()
            res = await rag_retrieve(db=db, tenant_id="t1", agent_id="a1", query="test")
            
            if mock_rerank.called:
                print("PASS: Rerank called in Gov mode")
            else:
                print("FAIL: Rerank NOT called in Gov mode")

async def test_auto_mode_deadline():
    print("\n--- Testing Auto Mode (Deadline) in pipeline.py ---")
    settings.RETRIEVAL_MODE = "auto"
    settings.RERANK_ENABLED = True
    settings.RETRIEVAL_DEADLINE_MS = 10
    
    with patch("app.core.rag.pipeline.retrieve") as mock_retrieve:
        # Simulate slow retrieval
        async def slow_retrieve(*args, **kwargs):
            await asyncio.sleep(0.02)
            return MagicMock(chunks=[{"chunk_id": "1", "score": 0.9, "chunk_text": "this is a test query"}])
        mock_retrieve.side_effect = slow_retrieve
        
        with patch("app.core.rag.rerank.rerank") as mock_rerank:
            from app.core.rag.pipeline import rag_retrieve
            db = MagicMock()
            res = await rag_retrieve(db=db, tenant_id="t1", agent_id="a1", query="test")
            
            if not mock_rerank.called:
                print("PASS: Rerank skipped due to deadline")
            else:
                print("FAIL: Rerank NOT skipped (or wrong reason)")

async def test_gating_logic():
    print("\n--- Testing Gating Logic (Fallback) ---")
    
    from app.core.rag.pipeline import _evaluate_evidence
    
    # Mock evaluator.evaluate to raise exception, forcing fallback logic
    with patch("app.core.rag.evaluator.evaluate", side_effect=Exception("Force fallback")):
        
        # Case 1: Eco + code_like (RRF) -> query difficult, weak match -> low_evidence
        print("Case 1: Eco + code_like (RRF) -> weak match")
        chunks = [{"score": 0.005, "payload": {"_score_kind": "rrf", "_sources": ["lexical"]}, "chunk_text": "irrelevant text"}]
        ok, info = _evaluate_evidence(query="complex code query", chunks=chunks)
        if not ok:
            print("PASS: Weak RRF match rejected")
        else:
            print(f"FAIL: Weak RRF match accepted: {info}")

        # Case 2: Eco + code_like -> strong match (overlap)
        print("Case 2: Eco + code_like -> strong match")
        chunks = [{"score": 0.02, "payload": {"_score_kind": "rrf", "_sources": ["lexical", "hybrid"]}, "chunk_text": "complex code query solution"}]
        ok, info = _evaluate_evidence(query="complex code query", chunks=chunks)
        if ok:
            print("PASS: Strong RRF match accepted")
        else:
            print(f"FAIL: Strong RRF match rejected: {info}")

        # Case 3: Eco + non-code -> hybrid cosine < 0.45 -> refuse
        print("Case 3: Eco + non-code -> weak vector match")
        chunks = [{"score": 0.3, "payload": {"_score_kind": "cosine"}, "chunk_text": "somewhat related"}]
        ok, info = _evaluate_evidence(query="specific question", chunks=chunks)
        if not ok:
            print("PASS: Weak vector match rejected")
        else:
            print(f"FAIL: Weak vector match accepted: {info}")

        # Case 4: Gov (rerank) -> rerank_score low -> refuse
        print("Case 4: Gov -> low rerank score")
        chunks = [{"rerank_score": -5.0, "chunk_text": "irrelevant"}]
        ok, info = _evaluate_evidence(query="test", chunks=chunks)
        if not ok:
            print("PASS: Low rerank score rejected")
        else:
            print(f"FAIL: Low rerank score accepted: {info}")

async def main():
    await test_eco_mode()
    await test_gov_mode()
    await test_auto_mode_deadline()
    await test_gating_logic()

if __name__ == "__main__":
    asyncio.run(main())
