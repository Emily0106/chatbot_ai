import sys
from pathlib import Path

# Fix ModuleNotFoundError for unit tests
# repo_root/apps/backend/tests/unit -> parents[3] = repo_root
def pytest_configure(config):
    repo_root = Path(__file__).resolve().parents[3]
    
    backend_src = repo_root / "apps" / "backend" / "src"
    if str(backend_src) not in sys.path:
        sys.path.insert(0, str(backend_src))
        
    core_shared = repo_root / "libs" / "core_shared"
    if str(core_shared) not in sys.path:
        sys.path.insert(0, str(core_shared))
