# Production Deployment Runbook

## 1. Prerequisites
- Docker Engine & Docker Compose (v2+)
- Domain name pointed to server IP (for Caddy TLS)
- Ports 80 and 443 open on firewall.

## 2. Configuration
1. Copy template:
   ```bash
   cp .env.prod.template .env.prod
   ```
2. Edit `.env.prod` and populate secrets:
   - `API_KEYS_JSON`: Define at least one restricted key.
   - Database passwords.
   - `DOMAIN_NAME`: Set your domain (e.g., `api.gov-ai.com`). For testing, use `localhost`.

## 3. Deployment
Run the production stack:
```bash
docker compose -f infra/compose/docker-compose.prod.yml up -d --build
```

## 4. Verification
Check status:
```bash
docker compose -f infra/compose/docker-compose.prod.yml ps
```

Verify TLS and health:
```bash
# -k may be needed if using localhost/self-signed certs
curl -kI https://<your-domain>/health
```

## 5. Maintenance
- **Logs**: `docker compose -f infra/compose/docker-compose.prod.yml logs -f backend`
- **Backup**:
  - Postgres: `docker exec gov-postgres-prod pg_dump -U $POSTGRES_USER $POSTGRES_DB > dump.sql`
  - Qdrant: Snapshot API via port forwarding (or accessible within internal network).

## 6. Deploy by Pinned Image (CI/CD Ready)

Production deployments use pre-built images tagged with commit SHA. **No building on production server.**

### Initial Setup
```bash
# Login to container registry (if using GitLab/private registry)
docker login registry.gitlab.com -u <deploy-token-user> -p <deploy-token>
```

### Deploy Specific Version
```bash
# Set image tag (commit SHA from CI)
export BACKEND_IMAGE="registry.gitlab.com/<group>/<repo>/backend:<commit-sha>"

# Or use local dev image for testing
export BACKEND_IMAGE="gov-backend:prod"

# Pull and deploy
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml pull backend
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml up -d backend

# Verify deployed version
docker inspect gov-backend-prod --format '{{.Config.Image}}'
curl -kI https://${DOMAIN_NAME}/health
```

### Rollback to Previous Version
```bash
# Set to previous stable commit SHA
export BACKEND_IMAGE="registry.gitlab.com/<group>/<repo>/backend:<previous-sha>"

# Fast rollback (no dependencies, backend only)
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml pull backend
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml up -d --no-deps backend

# Verify
docker logs --tail=50 gov-backend-prod
curl -kI https://${DOMAIN_NAME}/health
```

**Rollback time:** < 5 minutes (pull + restart)

## 7. Monitoring
A full monitoring stack (Prometheus/Grafana) is available.
See [MONITORING_RUNBOOK.md](./MONITORING_RUNBOOK.md) for details.

## 7. Load Testing
For load testing and SLO verification, see [LOADTEST_RUNBOOK.md](./LOADTEST_RUNBOOK.md).
