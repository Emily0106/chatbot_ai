import pytest

@pytest.mark.asyncio
async def test_embed_query_calls_embed_texts(monkeypatch):
    # import đúng module chứa embed_query/embed_texts
    import app.core.llm.embedding as emb

    called = {"n": 0}

    async def fake_embed_texts(texts):
        called["n"] += 1
        assert texts == ["hello"]
        return [[0.1, 0.2, 0.3]]

    monkeypatch.setattr(emb, "embed_texts", fake_embed_texts)

    vec = await emb.embed_query("hello")
    assert vec == [0.1, 0.2, 0.3]
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_embed_query_empty_returns_empty(monkeypatch):
    import app.core.llm.embedding as emb

    async def fake_embed_texts(_texts):
        raise AssertionError("embed_texts must not be called for empty input")

    monkeypatch.setattr(emb, "embed_texts", fake_embed_texts)

    vec = await emb.embed_query("")
    assert vec == []
