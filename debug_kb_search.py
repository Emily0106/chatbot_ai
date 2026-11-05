import asyncio
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "apps/backend/src"))

# Mock Settings
os.environ["QDRANT_URL"] = "http://localhost:6333"
os.environ["QDRANT_COLLECTION"] = "ingestion_chunks"
# Ensure we use the same embedding model config as ingestion if possible, 
# or rely on defaults if they match.
# Assuming OpenAI embeddings for now as per config.py default.
os.environ.setdefault("OPENAI_API_KEY", "dummy")  # set the real key in your shell
os.environ["OPENAI_EMBEDDING_MODEL"] = "text-embedding-ada-002"
os.environ["OPENAI_EMBEDDING_DIMENSIONS"] = "1536"
os.environ["POSTGRES_USER"] = "test"
os.environ["POSTGRES_PASSWORD"] = "test"
os.environ["POSTGRES_DB"] = "test"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["DB_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test"
os.environ["QDRANT_READONLY_API_KEY"] = "test_readonly_key"
os.environ["QDRANT_WRITE_API_KEY"] = "test_write_key"

from app.core import db_vector
from app.core.llm import embed_texts

async def embed_query_wrapper(text: str):
    vecs = await embed_texts([text])
    return vecs[0]

async def test_kb_search():
    query = "nhiệm vụ và quyền hạn của bộ phận một cửa"
    tenant_id = "xa_demo" # Try with the tenant from the demo
    
    print(f"Testing KB Search for query: '{query}'")
    print(f"Tenant: {tenant_id}")
    
    try:
        # 1. Test Embedding
        print("Generating embedding...")
        emb = await embed_query_wrapper(query)
        print(f"Embedding generated: {len(emb)} dims")
        
        # 2. Test Search
        print("Searching Qdrant...")
        results = await db_vector.search_hybrid_chunks(
            query=query,
            dense_embed_fn=embed_query_wrapper,
            tenant_id=tenant_id,
            top_k=5,
            mode="hybrid"
        )
        
        print(f"Found {len(results)} results:")
        for res in results:
            # res is (chunk_id, score, payload)
            cid, score, payload = res
            print(f" - [{score:.4f}] {cid}: {payload.get('chunk_text', '')[:50]}...")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_kb_search())
