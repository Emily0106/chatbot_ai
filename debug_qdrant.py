import requests
import json

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "gov_knowledge" # Correct collection name

def inspect_qdrant():
    for name in ["gov_knowledge", "ingestion_chunks"]:
        print(f"--- Inspecting Collection: {name} ---")
        
        # Get Collection Info
        url = f"{QDRANT_URL}/collections/{name}"
        try:
            resp = requests.get(url)
            if resp.status_code == 200:
                print(json.dumps(resp.json(), indent=2))
            else:
                print(f"Collection {name} not found or error: {resp.status_code}")
        except Exception as e:
            print(f"Connection failed for {name}: {e}")

if __name__ == "__main__":
    inspect_qdrant()
