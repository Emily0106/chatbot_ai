#!/bin/bash

# Kill any existing processes on ports 8000, 8001, 8002, 3000
echo "Cleaning up ports..."
# kill $(lsof -t -i:8000) 2>/dev/null
kill $(lsof -t -i:8001) 2>/dev/null
kill $(lsof -t -i:8002) 2>/dev/null
kill $(lsof -t -i:3000) 2>/dev/null

# Start Docker services
echo "Starting Docker services (Postgres, Qdrant, Redis, Ingestion)..."
docker compose -f docker-compose.local.yml up -d --build
echo "Waiting for services to be ready..."
sleep 10

# Start Backend
echo "Starting Backend (Port 8001)..."
export POSTGRES_USER=test
export POSTGRES_PASSWORD=test
export POSTGRES_DB=test
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export QDRANT_URL=http://localhost:6333
export REDIS_URL=redis://localhost:6379
export DB_URL=postgresql+asyncpg://test:test@localhost:5432/test
export OPENAI_API_KEY=sk-test
export QDRANT_READONLY_API_KEY=test
export INGESTION_SERVICE_URL=http://localhost:8010
export STORAGE_TMP_DIR=/tmp/ai_chat_storage
export CORS_ORIGINS="http://localhost:3000"

# Use absolute path for PYTHONPATH to avoid issues when changing directories
ROOT_DIR=$(pwd)
export PYTHONPATH=$ROOT_DIR/libs/core_shared:$ROOT_DIR/apps/backend/src

# Create storage dir
mkdir -p /tmp/ai_chat_storage

cd apps/backend/src
uvicorn app.main:app --host 0.0.0.0 --port 8001 > ../../../backend.log 2>&1 &
BACKEND_PID=$!
cd ../../..

# Start Frontend
echo "Starting Frontend (Port 3000)..."
cd apps/frontend
python3 -m http.server 3000 > ../../frontend.log 2>&1 &
FRONTEND_PID=$!
cd ../..

echo "=================================================="
echo "✅ System is running with GPU Ingestion!"
echo "👉 Frontend: http://localhost:3000/meeting_test.html"
echo "👉 Backend: http://localhost:8001"
echo "👉 Ingestion API: http://localhost:8010"
echo "=================================================="
echo "Logs are being written to backend.log, frontend.log"
echo "Press Ctrl+C to stop everything."

# Wait for user to exit
trap "kill $BACKEND_PID $FRONTEND_PID; docker compose -f docker-compose.local.yml down; exit" INT
wait
