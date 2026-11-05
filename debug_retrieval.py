import os
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

# Config
QDRANT_URL = "http://qdrant:6333"
COLLECTION_NAME = "people_demo"
MODEL_NAME = "all-MiniLM-L6-v2"

def main():
    print("--- Debugging Retrieval Accuracy ---")
    
    # 1. Connect to Qdrant
    client = QdrantClient(url=QDRANT_URL)
    
    # 2. List all points
    try:
        # Scroll to get all points (limit 100)
        res, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,
            with_payload=True,
            with_vectors=False
        )
        print(f"Total points found: {len(res)}")
        for point in res:
            data = point.payload.get("data_content", {})
            print(f"ID: {point.id} | Name: {data.get('full_name')} | Role: {data.get('occupation')}")
    except Exception as e:
        print(f"Error listing points: {e}")
        return

    # 3. Embed Query
    print("\n--- Embedding Query ---")
    query_text = "nguyễn văn a là ai"
    print(f"Query: '{query_text}'")
    
    model = SentenceTransformer(MODEL_NAME)
    query_vector = model.encode(query_text).tolist()
    
    # 4. Search
    print("\n--- Searching ---")
    try:
        hits = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=5,
            with_payload=True
        ).points
        
        for i, hit in enumerate(hits):
            data = hit.payload.get("data_content", {})
            print(f"Rank {i+1}: {data.get('full_name')} (Score: {hit.score:.4f})")
            
    except Exception as e:
        print(f"Error searching: {e}")

if __name__ == "__main__":
    main()
