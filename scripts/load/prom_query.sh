#!/bin/bash
# Helper script to query Prometheus metrics
# Usage: ./prom_query.sh "sum(rate(govai_chat_requests_total[1m]))"

QUERY="$1"

if [ -z "$QUERY" ]; then
    echo "Usage: $0 '<prometheus_query>'"
    echo ""
    echo "Examples:"
    echo "  $0 'sum(rate(govai_chat_requests_total[1m]))'"
    echo "  $0 'histogram_quantile(0.95, sum(rate(govai_chat_latency_seconds_bucket{stage=\"total\"}[5m])) by (le))'"
    exit 1
fi

docker exec gov-prometheus-prod wget -qO- "http://localhost:9090/api/v1/query?query=${QUERY}" | python3 -m json.tool
