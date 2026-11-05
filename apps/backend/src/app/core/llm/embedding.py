import asyncio
from typing import List
# Global model instance (lazy load or load on import)
_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        from app.config import settings
        model_path = settings.EMBED_MODEL_PATH or "all-MiniLM-L6-v2"
        device = getattr(settings, "EMBEDDING_DEVICE", "cpu")
        _model = SentenceTransformer(model_path, device=device)
    return _model

def _embed_sync(texts: List[str]) -> List[List[float]]:
    from app.config import settings
    # 1. Mock Mode (CI / No-GPU)
    backend = getattr(settings, "EMBEDDING_BACKEND", "local")
    if backend == "mock":
        # Return random-ish deterministic vectors for smoke tests
        # or simplified zeros. VECTOR_DIM default 768.
        dim = getattr(settings, "VECTOR_DIM", 768)
        return [[0.1] * dim for _ in texts]

    if backend == "openai":
        from app.core.llm_client import _client_instance as client
        model = getattr(settings, "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        dimensions = getattr(settings, "OPENAI_EMBEDDING_DIMENSIONS", 1536)
        
        response = client.embeddings.create(
            input=texts,
            model=model,
            dimensions=dimensions
        )
        return [data.embedding for data in response.data]

    model = _get_model()
    embeddings = model.encode(texts)
    
    # Pilot Hotfix (PR-A2): Pad to VECTOR_DIM (768)
    from app.config import settings
    target_dim = getattr(settings, "VECTOR_DIM", 768)
    
    if len(embeddings) > 0:
        current_dim = embeddings.shape[1]
        if target_dim > current_dim:
             import numpy as np
             pad_width = ((0, 0), (0, target_dim - current_dim))
             embeddings = np.pad(embeddings, pad_width, mode='constant', constant_values=0)
             
    return embeddings.tolist()

async def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for a list of texts using local SentenceTransformer.
    Runs in a thread pool to avoid blocking the async event loop.
    """
    if not texts:
        return []
    
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _embed_sync, texts)


async def embed_query(text: str) -> List[float]:
    """
    Embed a single query string into a vector (List[float]).
    Wrapper over embed_texts([text]).
    """
    if not text:
        return []

    vecs = await embed_texts([text])
    # runbook safety guard: ensure it return list not numpy array
    if not vecs:
        return []
    
    v0 = vecs[0] or []
    return list(v0)
