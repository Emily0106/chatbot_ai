import sys
print("Starting import...")
try:
    from app.core.rag.retrieve import retrieve
    print("Import successful!")
except Exception as e:
    print(f"Import failed: {e}")
