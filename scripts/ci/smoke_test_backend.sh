#!/bin/sh
# CI smoke test for backend image
# Called from GitLab CI smoke-backend-image job
set -e

echo "=== Backend Smoke Test ==="
echo "Image: $IMAGE_BACKEND:$CI_COMMIT_SHA"

# Step 1: Create env file
echo "[1/5] Creating env file..."
cat > /tmp/backend.env << 'ENVEOF'
ENV_MODE=dev
CI_MODE=true
ALLOW_DEFAULT_TENANT=true
API_KEYS_JSON={"dev-key-123":{"tenant_id":"default","roles":["admin"],"security_level":5}}
EMBEDDING_PROVIDER=mock
RERANK_ENABLED=0
DB_URL=postgresql+asyncpg://mock:mock@localhost/mock
QDRANT_URL=http://localhost:6333
REDIS_URL=redis://localhost:6379
OPENAI_API_KEY=dummy
ENVEOF
echo "  ✓ Env file created"

# Step 2: Run container (no port map needed for network check)
echo "[2/5] Starting backend container..."
CONTAINER_ID=$(docker run -d --name backend-smoke --env-file /tmp/backend.env "$IMAGE_BACKEND:$CI_COMMIT_SHA")
echo "  ✓ Container started: $CONTAINER_ID"

# Step 3: Wait for startup
echo "[3/5] Waiting 5 seconds for app startup..."
sleep 5
echo "  ✓ Wait complete"

# Step 4: Health checks
echo "[4/5] Running health checks (via sidecar)..."
SUCCESS=0
for i in $(seq 1 30); do
  echo "  Attempt $i/30: Check health via sidecar"
  if docker run --rm --network container:backend-smoke curlimages/curl:8.5.0 -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo "  ✅ Health check PASSED!"
    SUCCESS=1
    break
  fi
  echo "    Failed, retrying..."
  sleep 1
done

if [ "$SUCCESS" -eq 0 ]; then
  echo "  ❌ All health checks FAILED"
  echo ""
  echo "=== Diagnostics ==="
  docker ps -a
  echo ""
  echo "=== Container Logs ==="
  docker logs backend-smoke
  exit 1
fi

# Step 5: Success
echo "[5/5] Smoke test COMPLETE"
echo "✅ All checks passed!"
exit 0
