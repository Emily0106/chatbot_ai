import asyncio
import os
from qdrant_client import QdrantClient, models

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
API_KEY = os.getenv("QDRANT_WRITE_API_KEY", "")
COLLECTION_NAME = "ingestion_chunks"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2

def reset_collection():
    print(f"Connecting to Qdrant at {QDRANT_URL}...")
    client = QdrantClient(url=QDRANT_URL, api_key=API_KEY)
    
    if client.collection_exists(COLLECTION_NAME):
        print(f"Deleting existing collection '{COLLECTION_NAME}'...")
        client.delete_collection(COLLECTION_NAME)
        
    print(f"Creating collection '{COLLECTION_NAME}' with size {VECTOR_SIZE}...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE)
    )
    print("Collection reset successfully.")

if __name__ == "__main__":
    reset_collection()
