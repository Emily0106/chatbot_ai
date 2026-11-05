# Benchmark: Query Expansion Phase-1 — Runner Guide

> **Purpose:** Measure retrieval latency P50/P95/P99 with and without Query Expansion.
> **Script:** `scripts/load/load_test_retrieval_qe.py` (Locust)
> **Go/No-Go:** See `docs/GO_NO_GO_QE.md`

## Prerequisites

```bash
pip install locust           # if not installed
```

Ensure backend is running:
```bash
cd infra/compose && docker compose up -d backend
```

## Quick Smoke (10 seconds)

```bash
locust -f scripts/load/load_test_retrieval_qe.py \
  --headless -u 2 -r 1 --run-time 10s \
  --host http://localhost:8000
```

## Full Benchmark (60 seconds)

```bash
locust -f scripts/load/load_test_retrieval_qe.py \
  --headless -u 10 -r 2 --run-time 60s \
  --host http://localhost:8000 \
  --csv=benchmark_qe
```

This produces:
- `benchmark_qe_stats.csv` — per-endpoint summary (p50/p95/p99)
- `benchmark_qe_stats_history.csv` — time-series
- `benchmark_qe_failures.csv` — error details
- `benchmark_qe_exceptions.csv` — exception traces

## Phase Comparison: QE OFF vs ON

### Phase 1 — Baseline (QE disabled)

```bash
# Ensure ENABLE_QUERY_EXPANSION=0 in backend env
ENABLE_QUERY_EXPANSION=0 docker compose up -d backend

locust -f scripts/load/load_test_retrieval_qe.py \
  --headless -u 10 -r 2 --run-time 60s \
  --host http://localhost:8000 \
  --csv=benchmark_qe_OFF
```

### Phase 2 — QE enabled

```bash
ENABLE_QUERY_EXPANSION=1 docker compose up -d backend

locust -f scripts/load/load_test_retrieval_qe.py \
  --headless -u 10 -r 2 --run-time 60s \
  --host http://localhost:8000 \
  --csv=benchmark_qe_ON
```

### Compare Results

```bash
# Quick comparison (manual)
echo "=== QE OFF ===" && head -5 benchmark_qe_OFF_stats.csv
echo "=== QE ON ===" && head -5 benchmark_qe_ON_stats.csv

# Or use parser script (PR-12)
python scripts/parse_benchmark_csv.py \
  --baseline benchmark_qe_OFF_stats.csv \
  --experiment benchmark_qe_ON_stats.csv
```

## Extended Run (5 minutes, soak test)

```bash
locust -f scripts/load/load_test_retrieval_qe.py \
  --headless -u 10 -r 2 --run-time 5m \
  --host http://localhost:8000 \
  --csv=benchmark_qe_soak
```

## Query Scenarios

| Tag | Weight | Description |
|-----|--------|-------------|
| `citizen` | 50% | Typical citizen queries (thủ tục, quy trình...) |
| `code` | 25% | Legal code references (nghị định, thông tư...) |
| `pii` | 15% | Queries containing phone/CCCD/email |
| `adversarial` | 10% | Injection attempts, long strings |

Run specific scenario:
```bash
locust ... --tags citizen code   # Only citizen + code queries
```

## Configuration

| Env Variable | Default | Description |
|-------------|---------|-------------|
| `BASE_URL` | `http://localhost:8000` | Backend URL |
| `AUTH_TOKEN` | empty | Bearer token for auth |
| `AGENT_ID` | `gov_assistant` | Agent to test |
| `TENANT_ID` | `test-tenant` | Tenant header |
