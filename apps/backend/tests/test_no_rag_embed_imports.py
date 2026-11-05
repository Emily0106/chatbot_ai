import pathlib
import re
import os
import pytest

def test_no_agent_imports_from_rag_embed():
    # Adjust path to point to apps/backend/src/app
    # Current file is in apps/backend/tests
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/app"))
    root = pathlib.Path(base_path)
    
    # Regex to catch the deprecated import
    # Matches: "from app.core.rag.embed" OR "import app.core.rag.embed"
    pattern = re.compile(r"(from|import)\s+app\.core\.rag\.embed")
    
    offenders = []
    # Scan all .py files
    for p in root.rglob("*.py"):
        # Skip the alias file itself
        if p.name == "embed.py" and "rag" in str(p.parent):
            continue
            
        try:
            txt = p.read_text(encoding="utf-8")
            if pattern.search(txt):
                offenders.append(str(p))
        except Exception:
            pass # Skip unreadable files
            
    assert offenders == [], f"Found deprecated imports in: {offenders}. Please use 'from app.core.llm import embed_query'."
