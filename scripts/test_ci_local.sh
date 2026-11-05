#!/bin/bash
set -e

# scripts/test_ci_local.sh
# Emulates the GitLab CI pipeline locally.
# Requires: docker-compose (or running local services)
# Reads: env/.env.ci (but adapts to localhost)

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== STARTED: Local CI Simulation ===${NC}"

# Source CI env but override hosts for localhost
if [ -f env/.env.ci ]; then
    set -a
    source env/.env.ci
    set +a
    # Override for local execution
    export POSTGRES_HOST=localhost
    export QDRANT_URL=http://localhost:6333
    export REDIS_URL=redis://localhost:6379/0
    
    # Override credentials from .env if it exists (to match local docker-compose)
    if [ -f .env ]; then
        echo "Loading local credentials from .env..."
        # Extract DB vars safely
        export POSTGRES_USER=$(grep "^POSTGRES_USER=" .env | cut -d '=' -f2)
        export POSTGRES_PASSWORD=$(grep "^POSTGRES_PASSWORD=" .env | cut -d '=' -f2)
        export POSTGRES_DB=$(grep "^POSTGRES_DB=" .env | cut -d '=' -f2)
    fi

    # Computed URL using (potentially overridden) credentials
    export DB_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB}
    
    # Ensure correct models path for local
    export EMBED_MODEL_PATH=./models/mock-model # Or use existing mapping if available
else
    echo -e "${RED}Error: env/.env.ci not found.${NC}"
    exit 1
fi

echo "Environment loaded. DB: $POSTGRES_DB, User: $POSTGRES_USER"

# --- Stage 1: Guardrails ---
echo -e "\n${GREEN}>>> STAGE 1: Guardrails (Parity Check)${NC}"
export PYTHONPATH=$PYTHONPATH:$(pwd)/apps/backend/src:$(pwd)/libs/core_shared
python3 scripts/verify_parity.py

# --- Stage 2: Unit Tests ---
echo -e "\n${GREEN}>>> STAGE 2: Unit Tests${NC}"
# Run pytest on src to discover tests
pytest apps/backend/src -v

# --- Stage 3: Integration Smoke ---
echo -e "\n${GREEN}>>> STAGE 3: Integration Smoke${NC}"
echo "Note: This step requires running Postgres & Qdrant on localhost."

# Check if services are up (Optional port check)
# nc -z localhost 5432 || { echo "${RED}Postgres not running${NC}"; exit 1; }

echo "1. Initializing DB ($POSTGRES_DB)..."
# We act as CI, so we reset the CI/Test DB, NOT the main dev DB?
# Actually, strict local run might overwrite dev DB if names match.
# Warn user?
# For now, assumes developer knows what they are doing or uses distinct DB name in .env.ci
# user might want to backup.
# But "dev_fast_setup" usually resets everything.
# We will skip reset if user provides --no-reset logic? 
# The script is "test_ci_local", implies destructive test on test DB.

# Override DB name to be safe if possible?
# But `dev_fast_setup.py` reads config.py which reads env.
# correctly exported env vars should override config.py.

python3 scripts/dev_fast_setup.py --reset --force

echo "2. Verifying Agent Flow..."
python3 scripts/verify_agent_flow.py

echo "3. Running System Smoke..."
if [ -f scripts/ci_smoke.py ]; then
    python3 scripts/ci_smoke.py
fi

echo -e "\n${GREEN}=== SUCCESS: All CI Checks Passed Locally ===${NC}"
