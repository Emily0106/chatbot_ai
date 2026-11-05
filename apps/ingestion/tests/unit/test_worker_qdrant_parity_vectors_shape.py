from types import SimpleNamespace

import app.workers.worker_main as worker_main


class _MockClient:
    def __init__(self, vectors_cfg):
        self._vectors_cfg = vectors_cfg

    def get_collection(self, _name):
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(vectors=self._vectors_cfg),
            ),
            points_count=0,
        )

    def scroll(self, **_kwargs):
        return [], None


def _run_parity(vectors_cfg):
    worker_main._LAST_PARITY_CHECK = 0.0
    client = _MockClient(vectors_cfg)
    worker_main._ensure_qdrant_parity(client, "gov_knowledge")


def test_parity_accepts_vector_params_like(monkeypatch):
    monkeypatch.setattr(worker_main.settings, "VECTOR_SIZE", 768, raising=False)
    _run_parity(SimpleNamespace(size=768))


def test_parity_accepts_flat_dict_shape(monkeypatch):
    monkeypatch.setattr(worker_main.settings, "VECTOR_SIZE", 768, raising=False)
    _run_parity({"size": 768, "distance": "Cosine"})


def test_parity_accepts_named_vectors_dict_shape(monkeypatch):
    monkeypatch.setattr(worker_main.settings, "VECTOR_SIZE", 768, raising=False)
    _run_parity({"default": {"size": 768}})


def test_parity_accepts_named_vectors_object_shape(monkeypatch):
    monkeypatch.setattr(worker_main.settings, "VECTOR_SIZE", 768, raising=False)
    _run_parity({"default": SimpleNamespace(size=768)})
