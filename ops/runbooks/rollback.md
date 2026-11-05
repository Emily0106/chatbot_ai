# Rollback Runbook for Gov-AI Backend

## 🚨 Emergency Trigger
Use this runbook when a deployment failure has occurred, critical bugs are found in production, or the smoke tests have failed post-deployment.

## Prerequisites
- Access to the target server (SSH).
- Docker and Docker Compose installed.
- Access to the previous working Docker image tag (or local build context integrity).

## Procedure

### 1. Identify the Previous Stable Version
Check `CHANGELOG.md` or git history to identify the last known good version tag (e.g., `v1.1.0`).

### 2. Revert Configuration (If changed)
If environment variables or config files were changed, revert them to the previous state.
```bash
# Example: Restore backup of env file
cp ops/env/.env.backend.prod.bak ops/env/.env.backend.prod
```

### 3. Deploy Previous Version
Edit `ops/docker-compose.prod.yml` to point to the previous image tag, OR checkout the git tag for the previous version.

**Option A: Git Checkout (Recommended for Code Rollback)**
```bash
git checkout v1.1.0
```

**Option B: Docker Image Revert**
Update `docker-compose.prod.yml`:
```yaml
services:
  backend:
    image: ghcr.io/org/gov-ai-backend:v1.1.0 # Change from v1.2.0
```

### 4. Restart Services
Force recreation of containers to ensure the old version is running.
```bash
docker compose -f ops/docker-compose.prod.yml up -d --force-recreate
```

### 5. Verify Rollback
Run the smoke tests to confirm the system has stabilized.
```bash
./ops/tests/smoke_test.sh https://localhost:8443 admin:admin
```

### 6. Post-Incident
- Notify stakeholders that rollback is complete.
- Create a post-mortem to analyze why the deployments failed.
