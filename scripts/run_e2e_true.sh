#!/bin/bash
set -e

PROJECT_NAME="gov-ai-test"
export COMPOSE_PROJECT_NAME=$PROJECT_NAME

# 0. Cleanup Potential Conflicts
echo ">>> Cleaning up..."
docker compose -p $PROJECT_NAME -f infra/docker-compose.lite.yml down -v || true
# Also try to remove any container with the hardcoded name if it exists from other projects
docker rm -f gov-lite-qdrant gov-lite-postgres || true

# 1. Start Lite Infrastructure
echo ">>> Starting Infrastructure..."
docker compose -p $PROJECT_NAME -f infra/docker-compose.lite.yml up -d

# 2. Wait for Health
echo ">>> Waiting for storage..."
sleep 5

# 3. Setup Schema & Qdrant (Host)
echo ">>> Initializing Schema & Collection..."
PYTHONPATH=$(pwd)/apps/backend/src:$(pwd)/libs/core_shared \
DB_URL=postgresql://app:app_password@localhost:5432/rag_db \
QDRANT_URL=http://localhost:6333 \
python3 scripts/dev_fast_setup.py --reset --force --embed mock

# 4. Seed Data
echo ">>> Seeding Data..."
PYTHONPATH=$(pwd)/apps/backend/src:$(pwd)/libs/core_shared \
QDRANT_READONLY_API_KEY=mock_key \
EMBED_MODEL_PATH=sentence-transformers/all-MiniLM-L6-v2 \
DB_URL=postgresql+asyncpg://app:app_password@localhost:5432/rag_db \
python3 scripts/seed_agent_cert_e2e.py --force

# 5. Run Test
echo ">>> Running Pytest in Container..."
docker compose -p $PROJECT_NAME -f infra/docker-compose.lite.yml -f infra/docker-compose.e2e.yml run --rm \
  backend-e2e \
  sh -c "pip install pytest pytest-asyncio && echo '>>> ENV CHECK:' && env | grep DB_URL && echo '>>> END ENV CHECK' && pytest apps/backend/tests/integration/test_agent_certification_e2e.py -v --asyncio-mode=auto"

echo ">>> True E2E Complete."
