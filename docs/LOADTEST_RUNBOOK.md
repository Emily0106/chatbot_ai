# Load Test Runbook

## Overview
This runbook guides you through running load tests against the production stack to verify SLO compliance and system stability.

## Prerequisites
1. Production stack running (`docker-compose.prod.yml`)
2. Monitoring stack running (`docker-compose.monitoring.prod.yml`)
3. Python 3.10+ with `httpx` installed

## Safety Profiles

### Profile 1: Safe Validation (Recommended for first run)
Low resource usage, suitable for verification:
```bash
# Blocking
python3 scripts/load/prod_load_test.py \
  --base-url https://localhost:8443 \
  --api-key '<YOUR_KEY>' \
  --mode blocking \
  --rps 2 \
  --concurrency 5 \
  --duration-s 300 \
  --insecure-tls

# Streaming
python3 scripts/load/prod_load_test.py \
  --base-url https://localhost:8443 \
  --api-key '<YOUR_KEY>' \
  --mode streaming \
  --concurrency 3 \
  --duration-s 180 \
  --stream-events 10 \
  --insecure-tls
```

### Profile 2: Soak Test (Production readiness)
Higher load, longer duration:
```bash
# Blocking
python3 scripts/load/prod_load_test.py \
  --base-url https://localhost:8443 \
  --api-key '<YOUR_KEY>' \
  --mode blocking \
  --rps 5 \
  --concurrency 15 \
  --duration-s 900 \
  --insecure-tls
```

## Interpreting Results

### Success Criteria (SLO)
- **Error Rate**: < 1% (5xx + errors / total)
- **P95 Latency**: < 3 seconds
- **AuthZ Denials**: No unexpected spikes
- **Streams**: No leaks (returns to ~0 after test)

### Prometheus Verification
Use the helper script to query metrics:
```bash
# RPS
./scripts/load/prom_query.sh 'sum(rate(govai_chat_requests_total[1m]))'

# Error rate
./scripts/load/prom_query.sh 'sum(rate(govai_chat_requests_total{status="error"}[5m])) / sum(rate(govai_chat_requests_total[5m]))'

# P95 Latency
./scripts/load/prom_query.sh 'histogram_quantile(0.95, sum(rate(govai_chat_latency_seconds_bucket{stage="total"}[5m])) by (le))'

# Active streams
./scripts/load/prom_query.sh 'sum(govai_streams_active)'
```

## Stop Conditions
The load test will auto-stop if:
- 5xx error rate > 5% for 30+ seconds

## Post-Test Verification
```bash
# Check containers healthy
docker compose -f infra/compose/docker-compose.prod.yml ps
docker compose -f infra/monitoring/docker-compose.monitoring.prod.yml ps

# Check Prometheus target still up
./scripts/load/prom_query.sh 'up{job="govai-backend"}'
```
