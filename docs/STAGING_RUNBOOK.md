# Staging Deployment Runbook

**Goal**: Deploy Gov-AI Backend to a staging environment in <15 minutes with full validation.

## Prerequisites

- Docker Engine 24.0+ & Docker Compose V2
- Minimum 4GB RAM, 10GB disk space
- Ports available: 5432 (Postgres), 6333 (Qdrant), 6379 (Redis), 8000 (Backend)
- Valid secrets (see below)

## Required Environment Variables

Create a `.env.staging` file in the project root:

```bash
# Environment
ENV_MODE=staging
CI_MODE=false

# Security (REQUIRED - C0 validation will fail without these)
API_KEYS_JSON='{"staging-key-abc123":"tenant-staging-1","staging-key-xyz789":"tenant-staging-2"}'
ALLOW_DEFAULT_TENANT=false

# Database
POSTGRES_USER=staging
POSTGRES_PASSWORD=<strong-password-here>
POSTGRES_DB=govai_staging
DB_URL=postgresql+asyncpg://staging:<strong-password-here>@postgres:5432/govai_staging

# Vector DB
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=gov_knowledge
QDRANT_READONLY_API_KEY=
QDRANT_WRITE_API_KEY=

# Cache
REDIS_URL=redis://redis:6379/0

# LLM & Embeddings
OPENAI_API_KEY=<your-openai-api-key>
EMBEDDING_BACKEND=local
EMBED_MODEL_PATH=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DEVICE=cpu

# Feature Flags (optional)
ENABLE_RATE_LIMITING=true
ENABLE_STREAMING_CHAT=true
RERANK_ENABLED=false
```

> **⚠️ Security Notes:**
> - `.env.staging` is gitignored - never commit secrets
> - `API_KEYS_JSON` format: `{"<api-key>": "<tenant-id>", ...}`
> - In staging/prod, `CI_MODE` must be `false` (enforced by C0 validation)
> - No dev-key fallback works in staging (enforced by C0 validation)

## Deployment Commands

### Preflight Validation (REQUIRED before deployment)

Before starting the staging environment, run the preflight validation script to catch configuration errors early:

```bash
# Load your .env.staging (or export variables manually)
export $(cat .env.staging | grep -v '^#' | xargs)

# Run preflight validation
python3 scripts/preflight_env.py
```

**Expected output (PASS):**
```
============================================================
Gov-AI Backend - Preflight Environment Validation
============================================================

Environment Mode: STAGING

✅ CI_MODE: Correct (false in STAGING)

Required Secrets:
✅ API_KEYS_JSON: Valid (2 key(s))
✅ ALLOW_DEFAULT_TENANT: Correct (false)

Infrastructure:
✅ DB_URL: Present (postgresql://***@prodhost...)
✅ QDRANT_URL: Present (http://qdrant-staging...)
✅ REDIS_URL: Present (redis://redis-staging...)

LLM Configuration:
✅ OPENAI_API_KEY: Present (sk-s...123)

============================================================
✅ ALL CHECKS PASSED
Environment is ready for deployment
============================================================
```

> **⚠️ Do NOT proceed** if preflight validation fails. Fix errors first.

### Start Staging Environment

```bash
cd /path/to/AI_chat
docker compose -f infra/compose/docker-compose.staging.yml up -d
```

**What happens:**
1. Pulls/builds images (first time: ~5-10 min)
2. Starts Postgres, Qdrant, Redis with healthchecks
3. Backend waits for dependencies, then runs **C0 runtime validation**
4. If validation passes → backend starts on port 8000
5. If validation fails → backend exits with clear error

### View Logs

```bash
# All services
docker compose -f infra/compose/docker-compose.staging.yml logs -f

# Backend only
docker compose -f infra/compose/docker-compose.staging.yml logs -f backend

# Check for validation errors
docker compose -f infra/compose/docker-compose.staging.yml logs backend | grep "Runtime validation"
```

### Stop Staging Environment

```bash
docker compose -f infra/compose/docker-compose.staging.yml down
```

### Reset and Clean

```bash
# Stop and remove containers + volumes (full reset)
docker compose -f infra/compose/docker-compose.staging.yml down -v

# Remove images
docker compose -f infra/compose/docker-compose.staging.yml down --rmi all
```

## Health Checks & Verification

### 1. Check Service Status

```bash
docker compose -f infra/compose/docker-compose.staging.yml ps
```

All services should show `healthy` or `running`.

### 2. Verify Health Endpoints

```bash
# Basic health
curl http://localhost:8000/health
# Expected: {"status":"ok"}

# Ready check (includes DB connection)
curl http://localhost:8000/health/ready
# Expected: {"status":"ready"}
```

### 3. Verify Metrics

```bash
curl http://localhost:8000/metrics
# Expected: Prometheus format output with govai_* metrics
```

### 4. Test Authentication

```bash
# Without API key (should fail)
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"test","agent_id":"default"}'
# Expected: 401 Unauthorized

# With valid API key (should work)
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-abc123" \
  -d '{"message":"test","agent_id":"gov_assistant"}'
# Expected: 200 OK with JSON response
```

## Troubleshooting

### Backend fails to start

**Symptom**: Backend container exits immediately

**Check logs**:
```bash
docker compose -f infra/compose/docker-compose.staging.yml logs backend
```

**Common causes**:

1. **Missing API_KEYS_JSON**:
   ```
   FATAL: API_KEYS_JSON must be set in STAGING environment
   ```
   **Fix**: Add `API_KEYS_JSON` to `.env.staging`

2. **CI_MODE enabled in staging**:
   ```
   FATAL: CI_MODE cannot be enabled in STAGING environment
   ```
   **Fix**: Set `CI_MODE=false` in `.env.staging`

3. **Using dev/CI defaults**:
   ```
   FATAL: Missing or invalid configuration for STAGING environment:
     - DB_URL (using dev/CI default)
     - OPENAI_API_KEY (using dev/CI default)
   ```
   **Fix**: Set real secrets in `.env.staging`

4. **Database not ready**:
   ```
   asyncpg.exceptions.CannotConnectNowError
   ```
   **Fix**: Wait for Postgres healthcheck, or increase `start_period` in compose

### Services unhealthy

**Check individual service health**:
```bash
# Postgres
docker exec gov-postgres-staging pg_isready -U staging -d govai_staging

# Qdrant
curl http://localhost:6333/health

# Redis
docker exec gov-redis-staging redis-cli ping
```

### Port conflicts

**Symptom**: `bind: address already in use`

**Fix**: Either:
- Stop conflicting services on host
- OR set different ports in `.env.staging`:
  ```bash
  BACKEND_PORT=8001
  POSTGRES_PORT=5433
  QDRANT_PORT=6334
  REDIS_PORT=6380
  ```

## Automated Smoke Tests

Run the automated smoke test suite:

```bash
python3 scripts/staging_smoke.py \
  --base-url http://localhost:8000 \
  --api-key staging-key-abc123 \
  --api-key-2 staging-key-xyz789
```

**Expected output**:
```
✅ A) Health check: PASS
✅ B) Metrics endpoint: PASS
✅ C) Auth validation: PASS
✅ D) Blocking chat: PASS
✅ E) Streaming chat: PASS
✅ F) Tenant isolation: PASS

=== SMOKE TEST SUMMARY ===
PASSED: 6/6
FAILED: 0/6
STATUS: ✅ ALL TESTS PASSED
```

## Security Checklist

Before going to production:

- [ ] `.env.staging` is not committed to git
- [ ] `API_KEYS_JSON` contains strong, random keys
- [ ] `POSTGRES_PASSWORD` is strong and unique
- [ ] `OPENAI_API_KEY` is real (not "dummy" or "mock")
- [ ] `CI_MODE=false` (verified by C0 validation)
- [ ] `ALLOW_DEFAULT_TENANT=false` (verified by C0 validation)
- [ ] All services use `restart: unless-stopped`
- [ ] Healthchecks configured for all services
- [ ] Metrics endpoint is accessible at `/metrics`

## Next Steps

Once staging is verified:

1. **Production Deployment**: Adapt this for prod with:
   - External managed Postgres/Redis
   - HTTPS/TLS termination
   - Separate secrets management (Vault, AWS Secrets Manager)
   - Resource limits and autoscaling

2. **Monitoring**: Connect `/metrics` to Prometheus/Grafana

3. **CI/CD**: Use GitLab CI staging-smoke job for automated verification
