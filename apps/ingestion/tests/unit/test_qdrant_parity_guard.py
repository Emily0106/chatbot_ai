import pytest
from unittest.mock import MagicMock, patch
from app.workers.worker_main import _ensure_qdrant_parity
from app.core.config import settings

class MockQdrantClient:
    def __init__(self, dim=768, points=None):
        self.dim = dim
        self.points = points or []
        
    def get_collection(self, name):
        config = MagicMock()
        config.config.params.vectors.size = self.dim
        config.points_count = len(self.points)
        return config

    def scroll(self, collection_name, limit, with_payload, with_vectors):
        return self.points, None

class MockPoint:
    def __init__(self, payload):
        self.payload = payload

class TestQdrantParityGuard:
    
    def setup_method(self):
        # Reset cache for each test
        import app.workers.worker_main
        app.workers.worker_main._LAST_PARITY_CHECK = 0.0

    @patch("app.workers.worker_main.settings")
    def test_dim_mismatch_raises(self, mock_settings):
        """Should raise RuntimeError if vector dimension mismatches"""
        mock_settings.VECTOR_SIZE = 768
        client = MockQdrantClient(dim=1024) # Mismatch
        
        with pytest.raises(RuntimeError) as exc:
            _ensure_qdrant_parity(client, "test_coll")
        assert "Vector Dimension Mismatch" in str(exc.value)

    @patch("app.workers.worker_main.settings")
    def test_dim_match_ok(self, mock_settings):
        """Should pass if dimension matches"""
        mock_settings.VECTOR_SIZE = 768
        client = MockQdrantClient(dim=768)
        _ensure_qdrant_parity(client, "test_coll") # No raise

    @patch("app.workers.worker_main.settings")
    def test_model_id_mismatch_raises(self, mock_settings):
        """Should raise if existent point has different model_id"""
        mock_settings.VECTOR_SIZE = 768
        mock_settings.EMBEDDING_MODEL_ID = "v2_model"
        
        # Point has v1_model
        points = [MockPoint({"embedding_model_id": "v1_model"})]
        client = MockQdrantClient(dim=768, points=points)
        
        with pytest.raises(RuntimeError) as exc:
             _ensure_qdrant_parity(client, "test_coll")
        assert "Embedding Model Mismatch" in str(exc.value)

    @patch("app.workers.worker_main.settings")
    def test_model_id_match_ok(self, mock_settings):
        """Should pass if model_id matches"""
        mock_settings.VECTOR_SIZE = 768
        mock_settings.EMBEDDING_MODEL_ID = "v2_model"
        
        points = [MockPoint({"embedding_model_id": "v2_model"})]
        client = MockQdrantClient(dim=768, points=points)
        _ensure_qdrant_parity(client, "test_coll") # No raise

    @patch("app.workers.worker_main.settings")
    def test_legacy_point_ignored(self, mock_settings):
        """Should pass if legacy point has no model_id key"""
        mock_settings.VECTOR_SIZE = 768
        mock_settings.EMBEDDING_MODEL_ID = "v2_model"
        
        points = [MockPoint({"other_key": "val"})] # Missing embedding_model_id
        client = MockQdrantClient(dim=768, points=points)
        _ensure_qdrant_parity(client, "test_coll") # No raise (for now)
