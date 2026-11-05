
import os
import sys
import argparse
import json
import logging
from typing import Dict, Any, List
from uuid import UUID

# Setup path to import app modules
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
sys.path.append(os.path.join(APP_ROOT, "src"))

from app.core.config import settings
from app.preproc.stores.qdrant_repo import QdrantRepo, QdrantRepoConfig
from qdrant_client.http import models as qm

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrator")

# Mapping Config
DOC_CATEGORY_MAP = {
    "law": "law",
    "decree": "decree",
    "circular": "circular",
    "decision": "decision",
    "admin_procedure": "admin_procedure",
    "land_plan": "land_plan",
    "welfare_policy": "welfare_policy",
    "public_news": "public_news",
    # Legacy/Fallback mappings
    "legal": "law", 
    "notice": "public_news",
    "report": "other",
    "mixed": "other",
    "table": "other",
    "list": "other",
    "schedule": "meeting_schedule",
}

def migrate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform legacy payload to strict payload.
    Returns modified payload (or same if no changes needed).
    """
    new_p = payload.copy()
    changed = False

    # 1. Map doc_type
    if not new_p.get("doc_type"):
        cat = new_p.get("doc_category")
        if cat:
            mapped = DOC_CATEGORY_MAP.get(cat, "other")
            new_p["doc_type"] = mapped
            changed = True
    
    # 2. Map geo_code
    if not new_p.get("geo_code"):
        commune = new_p.get("commune_id")
        if commune:
            new_p["geo_code"] = commune
            changed = True
            
    # 3. Clean legacy keys (Strict Producer)
    for key in ["doc_category", "commune_id"]:
        if key in new_p:
            del new_p[key]
            changed = True
            
    return new_p, changed

def run_migration(apply: bool, dry_run: bool):
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    api_key = os.getenv("QDRANT_API_KEY")
    repo = QdrantRepo(QdrantRepoConfig(url=url, api_key=api_key))
    client = repo.client
    collection_name = repo.cfg.collection_name
    
    logger.info(f"Connecting to Qdrant: {url}, Collection: {collection_name}")
    
    # Stats
    stats = {
        "total_scanned": 0,
        "migrated": 0,
        "quarantined_missing_tenant": 0,
        "already_strict": 0,
        "errors": 0
    }

    # Scroll all points
    offset = None
    batch_size = 100
    
    quarantine_buffer = [] # Points to move to quarantine
    update_buffer = []     # Points to update in place
    
    while True:
        try:
            res = client.scroll(
                collection_name=collection_name,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
            points, next_offset = res
            if not points:
                break
            
            offset = next_offset
            
            for pt in points:
                stats["total_scanned"] += 1
                payload = pt.payload or {}
                
                # Check Tenant ID (Strict security)
                if not payload.get("tenant_id"):
                    stats["quarantined_missing_tenant"] += 1
                    if apply:
                        quarantine_buffer.append(pt.id)
                    continue

                new_payload, changed = migrate_payload(payload)
                
                if changed:
                    stats["migrated"] += 1
                    if apply:
                        update_buffer.append(qm.PointStruct(id=pt.id, payload=new_payload, vector={})) # Partial update payload only? No, set_payload
                else:
                    stats["already_strict"] += 1

        except Exception as e:
            logger.error(f"Error scrolling: {e}")
            stats["errors"] += 1
            break
            
    # Apply Updates
    if apply and update_buffer:
        logger.info(f"Applying updates to {len(update_buffer)} points...")
        # Simple loop for batch set_payload (in prod use proper batching)
        for pt in update_buffer:
             client.set_payload(collection_name=collection_name, payload=pt.payload, points=[pt.id])
    
    # Apply Quarantine (Safe Move)
    if apply and quarantine_buffer:
        q_col = "ingestion_chunks_quarantine"
        logger.info(f"Quarantining {len(quarantine_buffer)} points to '{q_col}'...")
        
        # 1. Ensure Quarantine Collection Exists (Clone config from main roughly)
        try:
            repo.ensure_collection() # Ensure main exists/refreshed
            # We assume qdrant_repo.ensure_collection only handles the config ID.
            # We manually create quarantine collection if not exists
            exists = False
            try:
                client.get_collection(q_col)
                exists = True
            except Exception:
                pass
                
            if not exists:
                logger.info(f"Creating quarantine collection '{q_col}'")
                client.create_collection(
                    collection_name=q_col,
                    vectors_config=qm.VectorParams(size=768, distance=qm.Distance.COSINE) # Default fallback
                )
        except Exception as e:
            logger.warning(f"Quarantine collection check failed: {e}")

        # 2. Retrieve fully points to Move (we need vectors if we want to query them later, 
        # but for simple storage payload is enough? 
        # Plan says "Move". Ideally we move vector too.
        # But scroll() above was with_vectors=False to save bandwidth.
        # To strictly move without data loss, we need vectors.
        # RETHINK: If we don't have vectors, we can't fully "Restore" them easily to vector search.
        # However, for metadata migration "Quarantine" usually means "Park metadata".
        # Let's assume we copy payload + ID. If vector is lost, it's acceptable for "Quarantined/invalid" data 
        # OR we should have fetched vectors.
        
        # FIX: We only fetched payload. We will just upsert payload (vector=None/Empty?). 
        # Qdrant requires vector for upsert? Yes usually.
        # Actually, we can use `scroll` with `with_vectors=True` or `retrieve` now.
        # Optimization: Fetch full points for quarantine batch.
        
        q_ids = [pt.id for pt in quarantine_buffer]
        # Retrieve full info for quarantine candidates
        q_full_points = client.retrieve(collection_name=collection_name, ids=q_ids, with_payload=True, with_vectors=True)
        
        client.upsert(
            collection_name=q_col,
            points=q_full_points
        )

        # 3. Delete from Main
        logger.info(f"Deleting {len(quarantine_buffer)} points from '{collection_name}'...")
        client.delete(collection_name=collection_name, points_selector=qm.PointIdsList(points=q_ids))

    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Execute changes")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Simulate only (default)")
    args = parser.parse_args()
    
    # If apply is set, dry-run is False unless explicitly set
    if args.apply:
        args.dry_run = False
        
    run_migration(args.apply, args.dry_run)
