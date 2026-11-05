#!/usr/bin/env bash
set -euo pipefail

# Create a release bundle containing ONLY production config / monitoring config (no code).
# Usage:
#   bash scripts/deploy/make_release_bundle.sh <commit-sha>
# Output:
#   dist/release_<sha>.tgz

SHA="${1:-}"
if [ -z "$SHA" ]; then
  echo "Usage: $0 <commit-sha>"
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="${ROOT}/dist"
STAGE_DIR="${OUT_DIR}/release_${SHA}"

mkdir -p "$OUT_DIR"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

# Paths to include (edit if you add more prod config files later)
INCLUDE_PATHS=(
  "infra/compose/docker-compose.prod.yml"
  "infra/compose/Caddyfile"
  "infra/monitoring/docker-compose.monitoring.prod.yml"
  "monitoring/prometheus/prometheus.yml"
  "monitoring/prometheus/alerts"
  "monitoring/grafana/provisioning"
  "monitoring/grafana/dashboards"
  "docs/PROD_RUNBOOK.md"
  "docs/CUTOVER_ROLLBACK.md"
  "docs/MONITORING_RUNBOOK.md"
  "docs/LOADTEST_RUNBOOK.md"
  "docs/CICD_VARIABLES.md"
)

echo "==> Staging files into: $STAGE_DIR"
pushd "$ROOT" >/dev/null

for p in "${INCLUDE_PATHS[@]}"; do
  if [ -e "$p" ]; then
    mkdir -p "${STAGE_DIR}/$(dirname "$p")"
    cp -a "$p" "${STAGE_DIR}/$p"
  else
    echo "WARN: missing path (skipping): $p"
  fi
done

# Create manifest with hashes (helpful for audit + diff)
MANIFEST="${STAGE_DIR}/release_manifest.txt"
{
  echo "release_sha=${SHA}"
  echo "created_utc=$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  echo
  echo "files:"
  find "$STAGE_DIR" -type f ! -name "release_manifest.txt" -print0 \
    | sort -z \
    | while IFS= read -r -d '' f; do
        rel="${f#${STAGE_DIR}/}"
        if command -v sha256sum >/dev/null 2>&1; then
          h="$(sha256sum "$f" | awk '{print $1}')"
        elif command -v shasum >/dev/null 2>&1; then
          h="$(shasum -a 256 "$f" | awk '{print $1}')"
        else
          h="(no_sha256_tool)"
        fi
        echo "  - ${rel}  ${h}"
      done
} > "$MANIFEST"

BUNDLE="${OUT_DIR}/release_${SHA}.tgz"
echo "==> Creating bundle: $BUNDLE"
tar -C "$STAGE_DIR" -czf "$BUNDLE" .

popd >/dev/null

echo "✅ Bundle created: $BUNDLE"
