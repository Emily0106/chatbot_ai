from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.rag import pipeline
from app.core.rag.retrieve import RetrieveResult


def _make_key(epoch: int) -> str:
    return pipeline._make_cache_key(
        tenant_id="tenant_a",
        tenant_epoch=epoch,
        agent_id="legal",
        query="canary query",
        filters=None,
        top_k=10,
        enable_rerank=True,
        rerank_top_k=5,
        gate_top_n=5,
        max_total_chars=9000,
        max_chunk_chars=1400,
        dedup=True,
        max_chunks=12,
        max_per_document=6,
        include_scores=True,
        include_scores_in_prompt=False,
        prefer_parent_text=True,
    )


def test_cache_key_changes_when_tenant_epoch_changes() -> None:
    key0 = _make_key(0)
    key1 = _make_key(1)

    assert key0 != key1
    assert '"tenant_epoch": 0' in key0
    assert '"tenant_epoch": 1' in key1


@pytest.mark.asyncio
async def test_rag_retrieve_bypasses_cache_when_epoch_lookup_fails(monkeypatch) -> None:
    mock_cache_get = AsyncMock(return_value='{"context":"cached","citations":[],"meta":{}}')
    mock_cache_set = AsyncMock()
    mock_epoch = AsyncMock(return_value=(0, False))

    monkeypatch.setattr(pipeline, "cache_get", mock_cache_get)
    monkeypatch.setattr(pipeline, "cache_set", mock_cache_set)
    monkeypatch.setattr(pipeline, "cache_get_tenant_epoch", mock_epoch)
    monkeypatch.setattr(
        pipeline,
        "decide_lane",
        MagicMock(return_value=SimpleNamespace(lane="strict", reason="test")),
    )
    monkeypatch.setattr(
        pipeline,
        "retrieve",
        AsyncMock(return_value=RetrieveResult(chunks=[], doc_map={}, used_tools=[], debug={})),
    )

    res = await pipeline.rag_retrieve(
        db=AsyncMock(),
        tenant_id="tenant_a",
        agent_id="legal",
        query="find canary",
        enable_cache=True,
    )

    assert res.meta["cache_enabled"] is False
    assert res.meta["cache_skip_reason"] == "tenant_epoch_unavailable"
    assert mock_cache_get.await_count == 0
    assert mock_cache_set.await_count == 0
