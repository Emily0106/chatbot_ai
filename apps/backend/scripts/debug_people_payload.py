import os
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLL = os.getenv("QDRANT_COLLECTION_PEOPLE", "people_demo")

print(f"Connecting to {QDRANT_URL}, collection: {COLL}")
client = QdrantClient(url=QDRANT_URL)

try:
    # Filter for entity_type="person"
    flt = qmodels.Filter(must=[qmodels.FieldCondition(key="entity_type", match=qmodels.MatchValue(value="person"))])
    pts, _ = client.scroll(collection_name=COLL, scroll_filter=flt, limit=5, with_payload=True, with_vectors=False)

    if not pts:
        print("No points found with entity_type='person'. Checking all points...")
        pts, _ = client.scroll(collection_name=COLL, limit=5, with_payload=True, with_vectors=False)

    for i, p in enumerate(pts, 1):
        print(f"---- Record {i} ----")
        print(f"Payload keys: {list(p.payload.keys())}")
        print(f"code: {p.payload.get('code')}")
        print(f"name_ascii: {p.payload.get('name_ascii')}")
        dc = p.payload.get("data_content") or {}
        print(f"data_content.full_name: {dc.get('full_name')}")
        print(f"entity_type: {p.payload.get('entity_type')}")

except Exception as e:
    print(f"Error: {e}")
