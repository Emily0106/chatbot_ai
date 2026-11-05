
import os
import pytest

LEGACY_KEYS = ["doc_category", "commune_id"]
RAG_DIR = "apps/backend/src/app/core/rag"
EXCLUDE_FILES = ["contract_validator.py"] # Allow in validator as it detects them

def test_no_legacy_keys_in_rag():
    """
    Scan app/core/rag for legacy keys. Violations imply broken strict contract.
    """
    violations = []
    
    base_path = os.path.abspath(RAG_DIR)
    if not os.path.exists(base_path):
        pytest.skip(f"RAG dir not found at {base_path}")
        
    for root, dirs, files in os.walk(base_path):
        for file in files:
            if not file.endswith(".py"):
                continue
            if file in EXCLUDE_FILES:
                continue
                
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                for key in LEGACY_KEYS:
                    # check for quoted key usage
                    if f'"{key}"' in content or f"'{key}'" in content:
                        violations.append(f"{file}: Found usage of legacy key '{key}'")
                        
    assert not violations, f"Legacy keys found in RAG core:\n{chr(10).join(violations)}"
