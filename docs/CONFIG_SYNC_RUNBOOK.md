# Config Sync Runbook (D4.3)

## Purpose
Safely sync production infra configs (compose/caddy/monitoring) from GitLab CI to the production server
without requiring git checkout on the server, and with zero-downtime reload for Caddy.

## How it works
1. CI builds `dist/release_<sha>.tgz` containing only config files.
2. Manual job `sync-config-prod` uploads to:
   `/srv/govai/ops/releases/<sha>/bundle.tgz`
3. Server extracts and diffs, backs up changed files into:
   `/srv/govai/ops/backups/config_<timestamp>/`
4. Applies changes:
   - Caddyfile change → `caddy reload` (no downtime)
   - compose change → `docker compose up -d` reconcile
   - monitoring change → monitoring compose `up -d`
5. Smoke test:
   - `GET /health` must be 200
   - `GET /metrics` must be 403

## Rollback
If smoke test fails, job restores backed up files and re-runs reload/reconcile.

## Files Synced
- `infra/compose/docker-compose.prod.yml`
- `infra/compose/Caddyfile`
- `infra/monitoring/docker-compose.monitoring.prod.yml`
- `monitoring/prometheus/prometheus.yml`
- `monitoring/prometheus/alerts/*`
- `monitoring/grafana/provisioning/**`
- `monitoring/grafana/dashboards/**`
- Documentation (optional): `docs/*RUNBOOK*.md`

## Prerequisites
Server must have:
- `.env.prod` exists with production secrets
- `infra/compose/docker-compose.prod.yml` exists (initial version)
- Container names: `gov-caddy-prod`, `gov-backend-prod`
- `docker compose` installed and working
- Caddy container can run `caddy reload`

## Manual Config Sync

If CI is unavailable, manually sync configs:

```bash
# On your workstation
cd /path/to/repo
bash scripts/deploy/make_release_bundle.sh $(git rev-parse HEAD)
scp dist/release_*.tgz prod-server:/srv/govai/ops/releases/<sha>/bundle.tgz

# On prod server
cd /srv/govai
tar -xzf ops/releases/<sha>/bundle.tgz -C ops/releases/<sha>/extracted/

# Backup and apply manually
cp -a infra/compose/Caddyfile ops/backups/Caddyfile.bak
cp ops/releases/<sha>/extracted/infra/compose/Caddyfile infra/compose/Caddyfile
docker exec gov-caddy-prod caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

## Notes
- The server does not need git checkout capability
- The job does not modify secrets in `.env.prod`
- Lock mechanism prevents concurrent config syncs
- Backup directory: `/srv/govai/ops/backups/config_<timestamp>/`
