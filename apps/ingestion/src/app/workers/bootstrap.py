from __future__ import annotations

import os
from functools import lru_cache

from app.preproc.pipeline.orchestrator import IngestionOrchestrator
from app.preproc.pipeline.registry import ToolRegistry
from app.preproc.classifiers.heuristic import HeuristicClassifier
from app.preproc.pipeline.local_embedder import LocalEmbedder

from app.preproc.stores.postgres_repo import PostgresRepo, PostgresRepoConfig
from app.preproc.stores.qdrant_repo import QdrantRepo, QdrantRepoConfig
from app.core.config import settings

@lru_cache(maxsize=1)
def get_pg_repo() -> PostgresRepo:
    db_url = str(settings.DATABASE_URL)
    # Use pooling in worker
    try:
        return PostgresRepo(PostgresRepoConfig(conninfo=db_url, use_pool=True))
    except TypeError:
        return PostgresRepo(PostgresRepoConfig(conninfo=db_url))


@lru_cache(maxsize=1)
def get_qdrant_client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)


@lru_cache(maxsize=1)
def get_orchestrator() -> IngestionOrchestrator:
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    collection = os.environ.get("QDRANT_COLLECTION", "ingestion_chunks")
    model_path = os.environ.get("EMBED_MODEL_PATH", "sentence-transformers/all-MiniLM-L6-v2")
    device = os.environ.get("EMBED_DEVICE", "cpu")

    pg = get_pg_repo()
    
    # PR-A2: Centralize Vector Size
    target_dim = settings.VECTOR_SIZE
    
    embedder = LocalEmbedder(model_path=model_path, device=device, target_dim=target_dim)
    # Infer vector size from model (now accounts for padding)
    vector_size = len(embedder.embed(["probe"])[0])

    qd = QdrantRepo(QdrantRepoConfig(
        url=qdrant_url,
        collection_name=collection,
        vector_name="dense", # Use named vector "dense"
        vector_size=vector_size,
        recreate_if_exists=False,
    ))

    registry = ToolRegistry()
    classifier = HeuristicClassifier()

    return IngestionOrchestrator(
        registry=registry,
        classifier=classifier,
        embedder=embedder,
        postgres_repo=pg,
        qdrant_repo=qd,
    )
