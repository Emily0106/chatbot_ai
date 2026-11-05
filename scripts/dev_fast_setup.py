#!/usr/bin/env python3
import sys
import os
import argparse
import json
import logging
import uuid
from datetime import datetime
from qdrant_client import QdrantClient
from qdrant_client.http import models
import psycopg2
from urllib.parse import urlparse

# Path setup
sys.path.append(os.getcwd())

from app.config import settings

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dev_setup")

# Constants matching PROD Core
COLLECTION_NAME = "gov_knowledge" 
VECTOR_SIZE = 768 # Force 768 for Pilot Parity
DOCS_TABLE = "documents"
CHUNKS_TABLE = "chunks"

def get_args():
    parser = argparse.ArgumentParser(description="Lite Dev Kit Setup")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate data")
    parser.add_argument("--embed", choices=["fastembed", "mock", "openai"], default="fastembed")
    parser.add_argument("--force", action="store_true", help="Force run even if DB looks like prod")
    return parser.parse_args()

def check_safety(args):
    env_mode = os.getenv("ENV_MODE", "prod")
    db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL") or ""
    
    # Relaxed check for CI
    is_local = "localhost" in db_url or "127.0.0.1" in db_url or "postgres-lite" in db_url or "docker" in db_url or "postgres" in db_url
    if not is_local and not args.force:
        logger.error("SAFETY: DATABASE_URL does not look local. Use --force to override.")
        sys.exit(1)

def get_db_connection():
    db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL")
    # Handle asyncpg URL if present
    if db_url and "+asyncpg" in db_url:
        db_url = db_url.replace("+asyncpg", "")
    return psycopg2.connect(db_url)

def run_migrations():
    logger.info("Running DB migrations...")
    # Initialize schema
    init_sql = """
    CREATE TABLE IF NOT EXISTS documents (
        doc_id TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        doc_category TEXT,
        title TEXT,
        source_uri TEXT,
        mime_type TEXT,
        checksum TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        doc_id TEXT REFERENCES documents(doc_id) ON DELETE CASCADE,
        scope TEXT NOT NULL,
        doc_category TEXT,
        chunk_kind TEXT,
        order_index INT,
        display_text TEXT,
        embed_text TEXT,
        citation JSONB,
        source_uri TEXT,
        mime_type TEXT,
        checksum TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        commune_id TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(init_sql)
        conn.commit()
    logger.info("DB Migrations Complete.")

def ensure_qdrant_client():
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    api_key = os.getenv("QDRANT_API_KEY", "")
    client = QdrantClient(url=url, api_key=api_key if api_key else None)
    return client

def get_embedder(mode):
    if mode == "mock":
        return lambda x: [0.1] * VECTOR_SIZE
    elif mode == "fastembed":
        try:
            from fastembed import TextEmbedding
            # BAAI/bge-small-en-v1.5 outputs 384 dims
            # Verify if user has cached models or if CI can download
            # For CI, falling back to mock might be safer unless cache is configured
            logger.info("Loading FastEmbed...")
            model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            
            def padded_embed(text):
                vec = list(model.embed([text]))[0].tolist() # 384
                # PILOT HOTFIX: Pad to 768
                if len(vec) < VECTOR_SIZE:
                    vec += [0.0] * (VECTOR_SIZE - len(vec))
                return vec
                
            return padded_embed
        except ImportError:
            logger.warning("fastembed not installed. Falling back to Mock.")
            return lambda x: [0.1] * VECTOR_SIZE
        except Exception as e:
            logger.warning(f"FastEmbed failed ({e}). Falling back to Mock.")
            return lambda x: [0.1] * VECTOR_SIZE
            
    return lambda x: [0.0] * VECTOR_SIZE

def seed_corpus(args, client: QdrantClient):
    embed_fn = get_embedder(args.embed)
    
    fixtures_dir = "fixtures/synthetic_corpus"
    if not os.path.exists(fixtures_dir):
        logger.warning(f"No fixtures found in {fixtures_dir}")
        return

    logger.info(f"Seeding corpus from {fixtures_dir} into {DOCS_TABLE}/{CHUNKS_TABLE}...")
    
    docs_inserted = 0
    chunks_inserted = 0
    
    for fname in os.listdir(fixtures_dir):
        if not fname.endswith(".jsonl"):
            continue
            
        fpath = os.path.join(fixtures_dir, fname)
        
        with open(fpath, "r") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except:
                    continue
                
                doc_id = str(uuid.uuid4())
                chunk_id = str(uuid.uuid4())
                
                # Metadata Mapping (Strict Production Contract)
                doc_payload = {
                    "doc_id": doc_id,
                    "title": row.get('title', 'Untitled'),
                    "content": row.get('content', ''),
                    "doc_type": row.get('doc_type', 'other'),
                    "tenant_id": row.get('tenant_id', 'dev_tenant'),
                    "scope": row.get('scope', 'public'),
                    "security_level": row.get('security_level', 1),
                    "url": row.get('file_url', ''), 
                    "created_at": datetime.utcnow()
                }

                # 1. Insert Postgres
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        # Insert Document
                        cur.execute(f"""
                            INSERT INTO {DOCS_TABLE} (
                                doc_id, scope, doc_category, title, source_uri, mime_type, checksum
                            )
                            VALUES (%s, %s, %s, %s, %s, 'text/plain', 'md5')
                            ON CONFLICT (doc_id) DO NOTHING
                        """, (
                            doc_id, 
                            doc_payload['scope'], 
                            doc_payload['doc_type'], 
                            doc_payload['title'], 
                            doc_payload['url']
                        ))
                        docs_inserted += 1

                        # Insert Chunk
                        cur.execute(f"""
                            INSERT INTO {CHUNKS_TABLE} (
                                chunk_id, doc_id, scope, doc_category, chunk_kind, order_index, 
                                display_text, embed_text, citation, source_uri, mime_type, checksum, commune_id
                            )
                            VALUES (%s, %s, %s, %s, 'text', 0, %s, %s, '{{}}', %s, 'text/plain', 'md5', %s)
                        """, (
                            chunk_id, 
                            doc_id, 
                            doc_payload['scope'], 
                            doc_payload['doc_type'], 
                            row['content'], 
                            row['content'], 
                            doc_payload['url'],
                            doc_payload['tenant_id']
                        ))
                        chunks_inserted += 1
                    conn.commit()

                # 2. Upsert Qdrant
                vector = embed_fn(row['content'])
                
                # Payload construction (Strict Contract)
                payload = {
                    "chunk_id": chunk_id,
                    "document_id": doc_id,
                    "doc_id": doc_id,
                    "text": row['content'],
                    "title": row['title'],
                    "source": "synthetic_seed",
                    "url": row.get('file_url'),
                    "tenant_id": row['tenant_id'],
                    "doc_type": row['doc_type'],
                    "scope": row['scope'],
                    "security_level": int(row['security_level']),
                    "department_id": row.get('department_id', 'demo_dept'),
                    "geo_code": row.get('geo_code', 'VN-DEMO'),
                    "_score_kind": "cosine"
                }
                
                client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=[
                        models.PointStruct(
                            id=chunk_id,
                            vector=vector,
                            payload=payload
                        )
                    ]
                )
                
    logger.info(f"Seeding Complete. Docs: {docs_inserted}, Chunks: {chunks_inserted}")

def main():
    args = get_args()
    check_safety(args)
    
    # Init Client
    client = ensure_qdrant_client()

    if args.reset:
        logger.warning("RESET MODE: Truncating Tables and Recreating Collection...")
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    try:
                        cur.execute(f"DROP TABLE IF EXISTS {DOCS_TABLE}, {CHUNKS_TABLE} CASCADE")
                        conn.commit()
                        logger.info("Tables dropped.")
                    except Exception as e:
                        logger.warning(f"Drop failed: {e}")
        except Exception as e:
             logger.warning(f"DB Connection failed check: {e}")
        
        # Drop/Create Collection
        try:
            client.delete_collection(COLLECTION_NAME)
        except:
             pass
        
        try:
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE)
            )
            logger.info(f"Collection {COLLECTION_NAME} recreated.")
        except Exception as e:
             logger.error(f"Failed to create collection: {e}")

    run_migrations()
    
    # Seed
    seed_corpus(args, client)

if __name__ == "__main__":
    main()
