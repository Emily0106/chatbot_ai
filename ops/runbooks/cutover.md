# Cutover / Deployment Runbook for Gov-AI Backend

## Scope
This runbook covers the standard deployment process for Staging and Production environments using Docker Compose.

## Prerequisites
- Local machine has `docker` and `docker compose`.
- Secrets are generated and placed in `ops/secrets/`.
- Environment files in `ops/env/` are populated (`.env.backend.prod`, `.env.edge.prod`, etc.).

## Phase 1: Pre-Flight Checks
1.  **Verify Git Status**: Ensure `main` is clean and tagged.
    ```bash
    git status
    git verify-tag v1.2.0
    ```
2.  **Verify Secrets**: Check that critical secrets exist.
    ```bash
    ls -l ops/secrets/tls/
    ls -l ops/secrets/htpasswd
    ```

## Phase 2: Staging Deployment
1.  **Build and Start Staging**
    ```bash
    docker compose -f ops/docker-compose.staging.yml up -d --build
    ```
2.  **Wait for Health**
    Wait 30-60 seconds for services to initialize.
3.  **Run Smoke Tests**
    ```bash
    ./ops/tests/smoke_test.sh https://localhost:8443 admin:admin
    ```
    *If failed, ABORT and debug.*

## Phase 3: Production Cutover
1.  **Backup Current State** (Optional but Recommended)
    ```bash
    cp ops/env/.env.backend.prod ops/env/.env.backend.prod.bak
    ```
2.  **Pull/Build New Version**
    ```bash
    docker compose -f ops/docker-compose.prod.yml pull   # If using registry
    # OR
    docker compose -f ops/docker-compose.prod.yml build  # If building locally
    ```
3.  **Deploy (Rolling Update simulation)**
    Docker compose tries to maximize availability, but there may be brief downtime.
    ```bash
    docker compose -f ops/docker-compose.prod.yml up -d
    ```
4.  **Verify Deployment**
    ```bash
    ./ops/tests/smoke_test.sh https://prod.gov-ai.example.com admin:admin
    ```

## Phase 4: Post-Deployment
- Monitor Grafana Dashboards for:
    - Error Rates (Status 5xx)
    - Latency Spikes
    - Gate Failures
- If issues arise, trigger **Rollback Runbook**.
