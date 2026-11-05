import pytest
from qdrant_client.http import models as qmodels

from app.core import db_vector


def test_sanitize_vector_name_defaults():
    assert db_vector._sanitize_vector_name(None) == "dense"
    assert db_vector._sanitize_vector_name("   ") == "dense"
    assert db_vector._sanitize_vector_name(" dense ") == "dense"
    assert db_vector._sanitize_vector_name("   ", allow_empty=True) == ""


@pytest.mark.asyncio
async def test_dense_query_uses_named_dense_vector(monkeypatch):
    captured = {}

    async def _fake_query_points_safe(**kwargs):
        captured.update(kwargs)

        class _Resp:
            points = []

        return _Resp()

    monkeypatch.setattr(db_vector, "DENSE_VECTOR_NAME", "dense")
    monkeypatch.setattr(db_vector, "_qdrant_query_points_safe", _fake_query_points_safe)

    out = await db_vector._dense_query(
        query_vector=[0.1, 0.2],
        q_filter=qmodels.Filter(),
        limit=3,
        timeout_s=1.0,
    )

    assert out == []
    assert captured["using"] == "dense"
    assert captured["query"] == [0.1, 0.2]


@pytest.mark.asyncio
async def test_hybrid_mode_falls_back_to_dense_only_when_sparse_disabled(monkeypatch):
    async def _fake_dense_embed_nonblocking(_dense_embed_fn, _query):
        return [0.5, 0.6]

    async def _fake_dense_query(**_kwargs):
        return [("chunk-1", 0.9, {"_score_mode": "dense"})]

    async def _must_not_call_sparse(_query):
        raise AssertionError("sparse embedding should not run when SPARSE_ENABLED=False")

    monkeypatch.setattr(db_vector, "SPARSE_ENABLED", False)
    monkeypatch.setattr(db_vector, "_dense_embed_nonblocking", _fake_dense_embed_nonblocking)
    monkeypatch.setattr(db_vector, "_dense_query", _fake_dense_query)
    monkeypatch.setattr(db_vector, "_sparse_embed_nonblocking", _must_not_call_sparse)

    out = await db_vector.search_hybrid_chunks(
        query="canary",
        dense_embed_fn=lambda _q: [0.5, 0.6],
        tenant_id="tenant_a_e2e",
        mode="hybrid",
    )

    assert out
    assert out[0][0] == "chunk-1"
