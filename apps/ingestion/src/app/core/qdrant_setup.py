
import logging
from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)

# Strict indexes required for gov-grade filtering
REQUIRED_PAYLOAD_INDEXES = {
    "tenant_id": "keyword",
    "doc_type": "keyword",
    "scope": "keyword",
    "security_level": "integer",  # IMPORTANT: integer for range filters
    "department_id": "keyword",
    "geo_code": "keyword",
    "ingested_at": "integer",     # Optional but good for sorting
}

def ensure_qdrant_schema(client: QdrantClient, collection_name: str, vector_size: int = 768):
    """
    Ensures the Qdrant collection exists and has strict payload indexes.
    Self-healing: Creates or updates schema on startup.
    """
    try:
        # 1. Check/Create Collection
        if not client.collection_exists(collection_name):
            logger.info(f"Creating missing collection: {collection_name}")
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE
                )
            )
        else:
            logger.info(f"Collection {collection_name} exists.")

        # 2. Enforce Indices
        # We don't have an easy "list indices" API that maps cleanly to logic without fetching info.
        # But create_payload_index is idempotent in Qdrant (usually returns "ok" or "already exists").
        # We will iterate and ensure they exist.
        
        for field_name, field_type in REQUIRED_PAYLOAD_INDEXES.items():
            schema_type = models.PayloadSchemaType.KEYWORD
            if field_type == "integer":
                schema_type = models.PayloadSchemaType.INTEGER
            elif field_type == "text":
                schema_type = models.PayloadSchemaType.TEXT
            
            logger.info(f"Ensuring index for '{field_name}' ({schema_type}) in {collection_name}...")
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=schema_type
            )
            
        logger.info("Qdrant Schema Enforcement Complete.")
        
    except Exception as e:
        logger.error(f"Failed to enforce Qdrant schema: {e}")
        # In strict mode, we might want to raise, but for resilience allowing partial startup might be ok?
        # No, for Gov-Grade, schema failure is critical.
        raise e
