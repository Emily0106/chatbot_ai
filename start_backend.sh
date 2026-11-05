#!/bin/bash
export POSTGRES_USER=test
export POSTGRES_PASSWORD=test
export POSTGRES_DB=test
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export QDRANT_URL=http://localhost:6333
export REDIS_URL=redis://localhost:6379
export DB_URL=postgresql+asyncpg://test:test@localhost:5432/test
: "${OPENAI_API_KEY:?Set OPENAI_API_KEY in your shell or .env (never commit it)}"
export OPENAI_API_KEY
export INGESTION_SERVICE_URL=http://localhost:8010
export STORAGE_TMP_DIR=/tmp/ai_chat_storage
export CORS_ORIGINS="http://localhost:3000"

ROOT_DIR=$(pwd)
export PYTHONPATH=$ROOT_DIR/libs/core_shared:$ROOT_DIR/apps/backend/src

mkdir -p /tmp/ai_chat_storage

cd apps/backend/src
nohup uvicorn app.main:app --host 0.0.0.0 --port 8001 > ../../../backend_manual.log 2>&1 &
echo "Backend started with PID $!"
