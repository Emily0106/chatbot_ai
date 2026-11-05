from __future__ import annotations

from unittest.mock import MagicMock

from qdrant_client.http import models as qm

from app.preproc.stores.qdrant_repo import QdrantRepo, QdrantRepoConfig


def test_delete_by_doc_id_and_tenant_uses_both_filters() -> None:
    repo = object.__new__(QdrantRepo)
    repo.cfg = QdrantRepoConfig(collection_name="ingestion_chunks_test")
    repo.client = MagicMock()

    repo.delete_by_doc_id_and_tenant("doc-123", "tenant-abc", wait=False)

    repo.client.delete.assert_called_once()
    kwargs = repo.client.delete.call_args.kwargs
    assert kwargs["collection_name"] == "ingestion_chunks_test"
    assert kwargs["wait"] is False

    selector = kwargs["points_selector"]
    assert isinstance(selector, qm.FilterSelector)
    flt = selector.filter
    assert isinstance(flt, qm.Filter)

    conds = flt.must or []
    assert len(conds) == 2
    cond_map = {
        str(getattr(cond, "key", "")): getattr(getattr(cond, "match", None), "value", None)
        for cond in conds
    }
    assert cond_map == {
        "doc_id": "doc-123",
        "tenant_id": "tenant-abc",
    }
