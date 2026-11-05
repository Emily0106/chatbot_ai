#!/bin/bash
# Monorepo Test Runner
# Runs backend and ingestion tests with correct PYTHONPATH isolation
# to avoid `app` namespace collision.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=========================================="
echo "🧪 MONOREPO TEST SUITE"
echo "=========================================="
echo ""

# Clear pycache to avoid import mismatches
echo "[1/4] Clearing __pycache__..."
find . -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

# Backend Tests
echo ""
echo "[2/4] Running Backend Unit Tests..."
echo "     PYTHONPATH=apps/backend/src"
PYTHONPATH=apps/backend/src python3 -m pytest -q apps/backend/tests/unit --import-mode=importlib "$@"
echo "✅ Backend unit tests passed"

# Ingestion Tests  
echo ""
echo "[3/4] Running Ingestion Unit Tests..."
echo "     PYTHONPATH=apps/ingestion/src"
PYTHONPATH=apps/ingestion/src python3 -m pytest -q apps/ingestion/tests/unit --import-mode=importlib "$@"
echo "✅ Ingestion unit tests passed"

# Security E2E
echo ""
echo "[4/4] Running Security E2E Verification..."
python3 scripts/verify_security_e2e.py
echo "✅ Security E2E passed"

echo ""
echo "=========================================="
echo "🎉 ALL TESTS PASSED"
echo "=========================================="
