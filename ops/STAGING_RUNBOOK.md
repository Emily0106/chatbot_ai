# Staging Runbook (v1.0.0)

**Target Environment:** Staging (Cluster A)
**Version:** v1.0.0 (Gov-AI Core Hardening)

---

## 1. Pre-requisites

Ensure the following environment variables are set in your CD pipeline or `.env` file:

| Variable | Recommended Value (Staging) | Description |
| :--- | :--- | :--- |
| `ENV_MODE` | `staging` | Enables structured logging, disables dangerous debug endpoints. |
| `QDRANT_API_KEY` | `***` | **Critical**: Master key for Vector DB admin. |
| `QDRANT_READONLY_API_KEY` | `***` | For read-only query services/monitoring. |
| `RETRIEVAL_MODE` | `gov` | Enforces stricter retrieval thresholds (0.45 cosine). |
| `MIN_RESTRICTED_LEVEL` | `3` | Minimum level requiring explicit clearance check. |
| `RERANK_ENABLED` | `True` | Must be ON for high-precision gating. |

**Database Backups:**
*   [ ] Take a snapshot of `postgres-main` before applying migrations.
*   [ ] Snapshot `qdrant-data` volume (optional but recommended for large indexes).

---

## 2. Deployment Steps

### Step 2.1: Pull & Build
```bash
# Assuming proper Docker registry login
docker-compose -f docker-compose.staging.yml pull
docker-compose -f docker-compose.staging.yml build
```

### Step 2.2: Database Migration (Critical)
Changes to `ingestion_jobs` metadata require a schema upgrade.

```bash
# Run migration from the backend container
docker-compose -f docker-compose.staging.yml run --rm backend alembic upgrade head
```
*Verify output:* Should show `... -> a1b2c3d4 (head)`.

### Step 2.3: Start Services
```bash
docker-compose -f docker-compose.staging.yml up -d
```

### Step 2.4: Startup Verification
Check logs for "Qdrant Schema Enforced" to ensure the Ingestion service successfully initialized strict collections.

```bash
docker-compose -f docker-compose.staging.yml logs ingestion | grep "Qdrant Schema Enforced"
```
*Expected:* `[INFO] Qdrant Schema Enforced: gov_knowledge (Strict)`

---

## 3. Verification (Smoke Test)

We have a specialized E2E script to verify the pipeline without user intervention.

**Run the Probe:**
```bash
# Execute remotely or from a bastion host with access to Staging API
export BASE_URL="http://staging-api.internal:8000" 
python scripts/verify_e2e_flow.py
```

**Success Criteria:**
1.  **Ingestion Status:** Returns `done` for test document `omega_plan.txt`.
2.  **Query (Auth):** Returns answer containing "2030" (or relevant key fact).
3.  **Query (Unauth):** Returns `403 Forbidden` OR Refusal text ("Xin lỗi...").
4.  **System:** Prints `✅ SYSTEM INTEGRITY VERIFIED`.

---

## 4. Monitoring & Alerting

Monitor these panels in Grafana (Dashboard: `GovAI-Core-Health`):

### A. Ingestion Health
*   **Metric:** `ingest_jobs_total{status="failed"}`
*   **Alert:** If > 5 failures in 10 mins.
*   **Action:** Check `ingestion` logs for OOM or parsing errors.

### B. Gate Rejection Rate
*   **Metric:** `gate_fail_total{reason="gated"}` / `chat_requests_total`
*   **Threshold:** Normal < 20%. If > 40%, user satisfaction is dropping.
*   **Tuning:** Check if `RETRIEVAL_MODE=gov` is too strict. Consider lowering weights or checking ingestion index quality.

### C. Latency (P95)
*   **Metric:** `chat_latency_seconds_bucket`
*   **Threshold:** Target < 3s (Cold), < 1.5s (Warm).

---

## 5. Rollback Plan

If `verify_e2e_flow.py` fails or critical bugs are found:

1.  **Revert Docker Tag:**
    Switch `docker-compose.staging.yml` back to `v0.9.5` (or previous stable hash).
    ```bash
    docker-compose -f docker-compose.staging.yml up -d
    ```

2.  **Restore Database (If Schema Failed):**
    If Alembic migration caused data corruption (rare for this release):
    ```bash
    cat pg_dump_pre_deploy.sql | docker exec -i postgres-main psql -U user gov_db
    ```

3.  **Incident Report:**
    Save logs for analysis:
    ```bash
    docker-compose logs --tail=2000 > incident_v1.0.0_fail.log
    ```
