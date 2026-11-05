#!/bin/bash
set -e

# Usage: ./smoke_test.sh <BASE_URL> <BASIC_AUTH_USER:PASS>
# Example: ./smoke_test.sh https://localhost:8443 admin:admin

BASE_URL=${1:-"https://localhost:8443"}
AUTH=${2:-"admin:admin"}

echo "🔥 Starting Smoke Tests against $BASE_URL..."

# 1. Check Root (Health)
echo "---------------------------------------------------"
echo "[1/4] Checking Root / Health..."
HTTP_CODE=$(curl -k -s -o /dev/null -w "%{http_code}" "$BASE_URL/")
if [ "$HTTP_CODE" -eq 200 ]; then
    echo "✅ Root Endpoint OK (200)"
else
    echo "❌ Root Endpoint FAILED ($HTTP_CODE)"
    exit 1
fi

# 2. Check Backend API (Docs/Health)
echo "---------------------------------------------------"
echo "[2/4] Checking Backend API (Docs)..."
HTTP_CODE=$(curl -k -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/docs")
if [ "$HTTP_CODE" -eq 200 ]; then
    echo "✅ Backend Docs OK (200)"
else
    echo "❌ Backend Docs FAILED ($HTTP_CODE)"
    exit 1
fi

# 3. Check Metrics (Protected)
echo "---------------------------------------------------"
echo "[3/4] Checking Metrics (Protected)..."
HTTP_CODE=$(curl -k -u "$AUTH" -s -o /dev/null -w "%{http_code}" "$BASE_URL/metrics")
if [ "$HTTP_CODE" -eq 200 ]; then
    echo "✅ Metrics Endpoint OK (200) - Auth Successful"
else
    echo "❌ Metrics Endpoint FAILED ($HTTP_CODE)"
    exit 1
fi

# 4. Check Grafana (Protected)
echo "---------------------------------------------------"
echo "[4/4] Checking Grafana Login Page..."
HTTP_CODE=$(curl -k -u "$AUTH" -s -o /dev/null -w "%{http_code}" "$BASE_URL/grafana/login")
if [ "$HTTP_CODE" -eq 200 ]; then
    echo "✅ Grafana Login OK (200)"
else
    echo "❌ Grafana Login FAILED ($HTTP_CODE)"
    exit 1
fi

echo "---------------------------------------------------"
echo "🚀 All Smoke Tests Passed!"
