#!/bin/bash
set -e

# Helper script to verify Production Gates
# Usage: export PROD_SSH_USER=... PROD_SSH_HOST=... && ./verify_prod_gates.sh

echo "========================================================"
echo "🔍 VERIFYING PRODUCTION GATES"
echo "========================================================"

# check vars
if [ -z "$PROD_SSH_USER" ] || [ -z "$PROD_SSH_HOST" ] || [ -z "$PROD_DEPLOY_PATH" ]; then
    echo "❌ ERROR: Missing required environment variables."
    echo "Please export: PROD_SSH_USER, PROD_SSH_HOST, PROD_DEPLOY_PATH"
    echo "(and ensure SSH key is added to agent)"
    exit 1
fi

SSH_CMD="ssh -p ${PROD_SSH_PORT:-22} ${PROD_SSH_USER}@${PROD_SSH_HOST}"

echo ""
echo ">>> [Gate 2] Checking Disk Space (Target: >40GB Free)"
$SSH_CMD 'set -e; df -h /; echo ""; docker system df' || echo "❌ Failed to connect or check disk"

echo ""
echo ">>> [Gate 3] Checking DB_URL in .env.prod"
$SSH_CMD "set -e; cd \"${PROD_DEPLOY_PATH}\"; echo \"PWD=\$(pwd)\"; grep -n \"^DB_URL=\" .env.prod || echo '❌ DB_URL NOT FOUND'"

echo ""
echo "========================================================"
echo "✅ Verification Commands Sent. Review Output Above."
echo "   - Disk / Avail > 40GB?"
echo "   - DB_URL exists and is correct?"
echo "========================================================"
