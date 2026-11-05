import sys
from pathlib import Path

# Fix ModuleNotFoundError: No module named 'core_shared'
# This allows running pytest locally without setting PYTHONPATH manually.
# It adds:
# 1. repo_root/apps/backend/src (for 'app')
# 2. repo_root/libs/core_shared (for 'core_shared')

def pytest_configure(config):
    # This file is in apps/backend/src/conftest.py
    # So parents[3] is the repo root:
    # src -> backend -> apps -> REPO_ROOT
    repo_root = Path(__file__).resolve().parents[3]
    
    # 1. Add apps/backend/src (so "import app..." works)
    backend_src = repo_root / "apps" / "backend" / "src"
    if str(backend_src) not in sys.path:
        sys.path.insert(0, str(backend_src))
        
    # 2. Add libs/core_shared (so "import core_shared..." works)
    core_shared = repo_root / "libs" / "core_shared"
    if str(core_shared) not in sys.path:
        sys.path.insert(0, str(core_shared))

    # print(f"[conftest] Added paths: {backend_src}, {core_shared}")
