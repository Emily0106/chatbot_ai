import os
import sys
# Add project root to path
sys.path.append(os.getcwd())

from app.core.config import settings
from app.core.llm.embedding import embed_texts
from qdrant_client import QdrantClient

def main():
    print("Verifying Legal Data Retrieval...")
    
    # Connect to Qdrant
    client = QdrantClient(url=settings.QDRANT_URL)
    collection_name = settings.QDRANT_COLLECTION
    
    print(f"Collection: {collection_name}")
    
    # Check count
    try:
        count = client.count(collection_name=collection_name)
        print(f"Total points in collection: {count.count}")
    except Exception as e:
        print(f"Error checking count: {e}")
        return
    
    # Query
    query_text = "Quy định về an toàn thông tin mạng"
    print(f"\nQuerying: '{query_text}'")
    
    # Embed
    try:
        query_vector = embed_texts([query_text])[0]
    except Exception as e:
        print(f"Error embedding text: {e}")
        return
    
    # Search
    try:
        results = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=5,
            with_payload=True
        )
        
        print(f"\nFound {len(results)} results:")
        for i, res in enumerate(results):
            payload = res.payload
            print(f"\n[{i+1}] Score: {res.score:.4f}")
            print(f"File: {payload.get('source_uri')}")
            print(f"Text: {payload.get('display_text')[:200]}...")
            
    except Exception as e:
        print(f"Error searching: {e}")

if __name__ == "__main__":
    main()
