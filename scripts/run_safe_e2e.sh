#!/bin/bash
set -e

# ========================================================================================
# Safe E2E Sandbox Wrapper
# Spans up isolated stack, runs tests with Prod Mode, and tears down.
# ========================================================================================

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
REPORT_FILE="REPORT_E2E_${TIMESTAMP}.md"
COMPOSE_FILE="infra/docker-compose.e2e.yml"

echo "🚀 [1/5] Cleaning up old sandbox state..."
docker compose -f "$COMPOSE_FILE" down -v

echo "🚀 [2/5] Starting E2E Sandbox (Postgres:5433, Qdrant:6334, Redis:6380)..."
docker compose -f "$COMPOSE_FILE" up -d --wait

# Prepare Environment for Backend (TestClient mode)
# NOTE: ci_smoke.py uses TestClient(app) which imports the FastAPI app in-process.
# ENV_MODE=prod would trigger runtime_validate() which rejects dummy secrets.
# Use ENV_MODE=ci for TestClient-based tests (services are still isolated in sandbox).
export ENV_MODE="ci"
export CI_MODE="1"
export APP_MODE="prod"

# Auto-detect host: inside container → use gateway; local dev → localhost
if [ -z "${E2E_HOST:-}" ] || [ "$E2E_HOST" = "localhost" ]; then
  # Check if we're inside a container (/.dockerenv exists)
  if [ -f /.dockerenv ] && command -v ip >/dev/null 2>&1; then
    E2E_HOST="$(ip route | awk '/default/ {print $3}')"
    echo "   Detected container environment, using gateway: $E2E_HOST"
  else
    E2E_HOST="localhost"
  fi
fi
export E2E_HOST
echo "   E2E_HOST=$E2E_HOST"

# 2. Config & Secrets for E2E
# ---------------------------------------------------------
export DB_URL="postgresql+asyncpg://e2e_user:e2e_pass@${E2E_HOST}:5433/gov_chat_e2e"
export POSTGRES_HOST=$E2E_HOST
export POSTGRES_PORT=5433
export POSTGRES_DB=gov_chat_e2e
export POSTGRES_USER=e2e_user
export POSTGRES_PASSWORD=e2e_pass

export QDRANT_URL="http://${E2E_HOST}:6334"
export REDIS_URL="redis://${E2E_HOST}:6380/0"

# Preflight: verify services are reachable
echo "🚀 [2.5/5] Preflight connectivity check..."
for i in $(seq 1 30); do
  if curl -fsS "http://${E2E_HOST}:6334/healthz" >/dev/null 2>&1; then
    echo "   ✅ Qdrant reachable"
    break
  fi
  sleep 1
done

echo "   DB_URL=$DB_URL"
echo "   QDRANT_URL=$QDRANT_URL"
echo "   REDIS_URL=$REDIS_URL"

# Mock Keys for Isolation Test
export API_KEYS_JSON='{
  "sk-citizen-key": {"role": "citizen", "tenant_id": "default", "security_level": 1, "allowed_agents": ["citizen"], "geo_code": "VN-HN"},
  "sk-admin-key": {"role": "admin", "tenant_id": "default", "security_level": 5, "allowed_agents": ["citizen"], "geo_code": "VN-HN", "department_id": "DEPT_01"},
  "sk-tenant-b-key": {"role": "citizen", "tenant_id": "tenant_b", "security_level": 1, "allowed_agents": ["citizen"], "geo_code": "VN-HCM"}
}'

# Override CI Script to use these keys
export CI_SMOKE_CITIZEN_KEY="sk-citizen-key"
export CI_SMOKE_ADMIN_KEY="sk-admin-key"
export CI_SMOKE_OFFICER_KEY="sk-admin-key"

echo "🚀 [3/5] Executing Test Suite (TestClient Mode)..."
echo "# E2E Sandbox Report (${TIMESTAMP})" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# 1. CI Smoke (tee stderr to console so CI log shows errors)
echo "## 1. Traceability & Smoke Test" >> "$REPORT_FILE"
if python3 scripts/ci_smoke.py >> "$REPORT_FILE" 2> >(tee -a "$REPORT_FILE" >&2); then
    echo "   ✅ Smoke Test PASSED"
else
    echo "   ❌ Smoke Test FAILED"
    echo "   --- Last 30 lines of report ---"
    tail -30 "$REPORT_FILE"
    docker compose -f "$COMPOSE_FILE" down -v
    exit 1
fi

# 2. Advanced E2E Flow (tee stderr to console)
echo "" >> "$REPORT_FILE"
echo "## 2. Advanced E2E Flow (Isolation & Policy)" >> "$REPORT_FILE"
if python3 scripts/verify_e2e_prod.py >> "$REPORT_FILE" 2> >(tee -a "$REPORT_FILE" >&2); then
    echo "   ✅ Advanced Flow PASSED"
else
    echo "   ❌ Advanced Flow FAILED"
    echo "   --- Last 30 lines of report ---"
    tail -30 "$REPORT_FILE"
    docker compose -f "$COMPOSE_FILE" down -v
    exit 1
fi

# Clean up
echo "🚀 [5/5] Teardown..."
docker compose -f "$COMPOSE_FILE" down -v

echo "✅ DONE. Report at $REPORT_FILE"
cat "$REPORT_FILE"
