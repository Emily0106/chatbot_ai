# Production Cutover & Rollback Plan (D3)

## Pre-Cutover Checklist

### Infrastructure
- [ ] All containers healthy (Postgres, Redis, Qdrant, Backend, Caddy)
- [ ] Monitoring stack operational (Prometheus, Grafana)
- [ ] Network isolation verified (internal/edge networks)
- [ ] TLS certificates valid

### Security
- [ ] `ENV_MODE=prod`, `CI_MODE=false`
- [ ] `API_KEYS_JSON` properly configured
- [ ] `ALLOW_DEFAULT_TENANT=false`
- [ ] `/metrics` blocked from public access
- [ ] RBAC policies tested

### Data
- [ ] Database backup completed
- [ ] Qdrant collections verified
- [ ] Backup restoration tested

## Cutover Procedure

### 1. DNS & Firewall
1. Update `DOMAIN_NAME` in `.env.prod`
2. Update port mapping to `80:80` and `443:443` in `docker-compose.prod.yml`
3. Ensure firewall allows ports 80/443
4. Point DNS A record to server IP

### 2. Deploy
```bash
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml up -d --build
```

### 3. Verify
```bash
# Health check
curl -I https://<your-domain>/health

# Metrics blocked
curl -I https://<your-domain>/metrics

# Auth working
curl -X POST https://<your-domain>/api/chat \
  -H "X-API-Key: <key>" \
  -d '{"message":"test","agent_id":"gov_assistant","stream":false}'
```

## Backup Procedures

### Postgres Backup
```bash
# Create backup
docker exec gov-postgres-prod sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > /tmp/backup.sql'
docker cp gov-postgres-prod:/tmp/backup.sql ./backups/govai_prod_$(date +%F_%H%M).sql

# Restore
cat ./backups/govai_prod_<timestamp>.sql | docker exec -i gov-postgres-prod psql -U $POSTGRES_USER -d $POSTGRES_DB
```

### Qdrant Verification
```bash
docker exec gov-qdrant-prod sh -c 'ls -la /qdrant/storage'
```

## Rollback Plan

### App-Only Rollback (5-10 minutes)
If code issues detected, rollback to previous image tag:
```bash
# Set to previous stable commit SHA
export BACKEND_IMAGE="registry.gitlab.com/<group>/<repo>/backend:<previous-sha>"

# Pull and deploy (backend only, no deps restart)
docker login registry.gitlab.com -u <user> -p <token>
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml pull backend
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml up -d --no-deps backend

# Verify
docker inspect gov-backend-prod --format '{{.Config.Image}}'
docker logs --tail=100 gov-backend-prod
curl -kI https://<domain>/health
```

**Note:** Image tags are immutable (commit SHA), enabling instant rollback without code checkout.

### Full Stack Rollback
If config/network issues:
```bash
docker compose -f infra/compose/docker-compose.prod.yml down
git checkout <stable-tag>
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml up -d
```

### Data Rollback (Emergency Only)
```bash
# Stop backend
docker compose -f infra/compose/docker-compose.prod.yml stop backend

# Restore database
cat ./backups/govai_prod_<timestamp>.sql | docker exec -i gov-postgres-prod psql -U $POSTGRES_USER -d $POSTGRES_DB

# Restart
docker compose -f infra/compose/docker-compose.prod.yml start backend
```

## Post-Cutover Verification

### Immediate (T+0)
- [ ] All containers healthy
- [ ] Health endpoint returns 200
- [ ] Metrics blocked (403)
- [ ] Sample chat request succeeds

### T+15 minutes
- [ ] Prometheus scraping successfully
- [ ] No error rate spikes
- [ ] Latency within SLO (p95 < 3s)
- [ ] No container restarts

### T+1 hour
- [ ] Load test passes (safe profile)
- [ ] AuthZ denials tracked correctly
- [ ] No memory leaks (check docker stats)
- [ ] Grafana dashboards operational

## Known Issues & Fixes

### Qdrant Healthcheck
**Issue**: Qdrant container doesn't include `wget` or `curl`
**Fix**: Use TCP test instead:
```yaml
healthcheck:
  test: ["CMD-SHELL", "timeout 5 sh -c ':> /dev/tcp/127.0.0.1/6333' || exit 1"]
```
