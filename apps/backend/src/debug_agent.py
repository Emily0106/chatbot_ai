import os
from qdrant_client import QdrantClient
from app.core.retrieval_structured import scroll_exact_person
from core_shared.text_utils import ascii_norm

client = QdrantClient("http://qdrant:6333")
collection = "people_demo"

print("--- Checking scroll_exact_person ---")
try:
    print("Collections:", client.get_collections())
    print("Info:", client.get_collection(collection_name=collection))
    print("Count:", client.count(collection_name=collection))
    
    pts, _ = client.scroll(collection_name=collection, limit=10, with_payload=True)
    print(f"Found {len(pts)} points")
    for p in pts:
        payload = p.payload or {}
        print(f"ID: {p.id}")
        print(f"Entity Type: {payload.get('entity_type')}")
        print(f"Name ASCII: {payload.get('name_ascii')}")
        print(f"Full Name: {payload.get('data_content', {}).get('full_name')}")
        print("-" * 20)
except Exception as e:
    print(f"Error: {e}")

print("\n--- Checking ascii_norm ---")
q = "Tìm thông tin về ông Nguyễn Văn A"
q_norm = ascii_norm(q)
print(f"Query: {q} -> Norm: {q_norm}")

target = "nguyen van a"
if target in q_norm:
    print(f"'{target}' is in '{q_norm}'")
else:
    print(f"'{target}' is NOT in '{q_norm}'")
