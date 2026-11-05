import os
import sys
import pandas as pd
from pathlib import Path

# Add src and libs to path
# In container: /app/src and /app/libs/core_shared
sys.path.append("/app/src")
sys.path.append("/app/libs/core_shared")

from app.preproc.utils.people_demo import upsert_person_rows_to_qdrant

def main():
    # Configuration
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    # openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    collection_name = os.getenv("QDRANT_COLLECTION_PEOPLE", "people_demo")
    
    # if not openai_api_key:
    #     print("Error: OPENAI_API_KEY not set")
    #     return

    # File paths
    # In container: /app/storage/people_demo.xlsx (mapped from ../../storage/raw_files)
    if os.path.exists("/app/storage"):
        base_path = Path("/app/storage")
    else:
        base_path = Path("storage/raw_files")
    excel_path = base_path / "people_demo.xlsx"
    
    print(f"Reading from: {excel_path}")
    
    # Read Excel
    try:
        df = pd.read_excel(excel_path, sheet_name="people")
        rows = df.to_dict("records")
        print(f"Found {len(rows)} rows")
    except Exception as e:
        print(f"Error reading excel: {e}")
        return

    # Upsert
    print("Upserting to Qdrant...")
    result = upsert_person_rows_to_qdrant(
        rows=rows,
        qdrant_url=qdrant_url,
        collection_name=collection_name,
        openai_api_key="dummy",
        openai_embed_model="/models/vietnamese-sbert",
        source_uri=f"storage/raw_files/people_demo.xlsx",
        sheet_name="people",
        recreate_collection=True
    )
    
    print("Done!")
    print(result)

if __name__ == "__main__":
    main()
