# Monitoring Deployment Runbook

## 1. Prerequisites
- **Production Stack** must be running (`docker-compose.prod.yml`).
- Network `govai_prod_internal` must exist (created by Prod stack).

## 2. Deployment
Start the monitoring stack:
```bash
docker compose -f infra/monitoring/docker-compose.monitoring.prod.yml up -d
```

## 3. Verification
### A. Check Containers
```bash
docker compose -f infra/monitoring/docker-compose.monitoring.prod.yml ps
```

### B. Verify Prometheus Scraping
Prometheus should reach Backend on internal network:
```bash
docker exec -it gov-prometheus-prod wget -qO- http://backend:8000/metrics | head
```

Verify Targets Status:
```bash
docker exec -it gov-prometheus-prod wget -qO- http://localhost:9090/api/v1/targets | grep "health"
```

### C. Grafana Access
Grafana is listening on `127.0.0.1:3000`.
- **Method 1 (Tunnel)**: SSH tunnel to server: `ssh -L 3000:127.0.0.1:3000 user@server`
- **Method 2 (Browser)**: Open `http://localhost:3000`.
- **Login**: `admin` / `admin` (or value of `GRAFANA_PASSWORD`).

## 4. Configuration
- **Alerts**: Defined in `monitoring/prometheus/alerts/govai_alerts.yml`.
- **Dashboards**: Provisioned in `monitoring/grafana/dashboards/`.
