#!/usr/bin/env bash
# Remote-side script to apply config bundle with atomic updates and rollback
# Called from GitLab CI sync-config-prod job via SSH
# Environment: RELEASE_SHA, PROD_DEPLOY_PATH, PROD_PUBLIC_BASE_URL

set -euo pipefail

RELEASE_SHA="${RELEASE_SHA:?missing RELEASE_SHA}"
PROD_DEPLOY_PATH="${PROD_DEPLOY_PATH:?missing PROD_DEPLOY_PATH}"
PROD_PUBLIC_BASE_URL="${PROD_PUBLIC_BASE_URL:?missing PROD_PUBLIC_BASE_URL}"

cd "$PROD_DEPLOY_PATH"

# --- simple lock to prevent concurrent config syncs
mkdir -p ops/locks
LOCK_DIR="ops/locks/config_sync.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "❌ Another config sync is running (lock exists): $LOCK_DIR"
  exit 1
fi
trap 'rmdir "$LOCK_DIR" >/dev/null 2>&1 || true' EXIT

BUNDLE_PATH="ops/releases/${RELEASE_SHA}/bundle.tgz"
RELEASE_DIR="ops/releases/${RELEASE_SHA}/extracted"
test -f "$BUNDLE_PATH"

rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
tar -xzf "$BUNDLE_PATH" -C "$RELEASE_DIR"

# Required baseline files in bundle
test -f "$RELEASE_DIR/infra/compose/docker-compose.prod.yml"
test -f "$RELEASE_DIR/infra/compose/Caddyfile"

# Helper: sha256 for file
file_hash() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$f" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$f" | awk '{print $2}'
  else
    echo "nohash"
  fi
}

# Items to sync (from extracted -> live)
SYNC_ITEMS=(
  "infra/compose/docker-compose.prod.yml"
  "infra/compose/Caddyfile"
  "infra/monitoring/docker-compose.monitoring.prod.yml"
  "monitoring/prometheus/prometheus.yml"
  "monitoring/prometheus/alerts"
  "monitoring/grafana/provisioning"
  "monitoring/grafana/dashboards"
)

TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="ops/backups/config_${TS}"
mkdir -p "$BACKUP_DIR"

changed_prod_compose="0"
changed_caddy="0"
changed_monitoring="0"
changed_any="0"

backup_path() {
  local rel="$1"
  local src="$2"
  local dest="${BACKUP_DIR}/${rel}"
  mkdir -p "$(dirname "$dest")"
  cp -a "$src" "$dest"
}

install_file_atomic() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "$dst")"
  local tmp="${dst}.tmp.${TS}"
  cp -a "$src" "$tmp"
  mv -f "$tmp" "$dst"
}

sync_one_file() {
  local rel="$1"
  local new="${RELEASE_DIR}/${rel}"
  local cur="${PROD_DEPLOY_PATH}/${rel}"

  if [ ! -f "$new" ]; then
    # Not in bundle - skip silently
    return 0
  fi

  local new_h cur_h
  new_h="$(file_hash "$new")"
  cur_h="absent"
  if [ -f "$cur" ]; then
    cur_h="$(file_hash "$cur")"
  fi

  if [ "$new_h" != "$cur_h" ]; then
    echo "CHANGED file: $rel"
    changed_any="1"
    if [ -f "$cur" ]; then
      backup_path "$rel" "$cur"
    fi
    install_file_atomic "$new" "$cur"

    case "$rel" in
      infra/compose/docker-compose.prod.yml) changed_prod_compose="1" ;;
      infra/compose/Caddyfile) changed_caddy="1" ;;
      infra/monitoring/docker-compose.monitoring.prod.yml) changed_monitoring="1" ;;
      monitoring/prometheus/*|monitoring/grafana/*) changed_monitoring="1" ;;
    esac
  fi
}

sync_one_dir() {
  local rel="$1"
  local new_dir="${RELEASE_DIR}/${rel}"
  local cur_dir="${PROD_DEPLOY_PATH}/${rel}"
  [ -d "$new_dir" ] || return 0

  # Compare each file inside new_dir
  while IFS= read -r -d '' f; do
    local sub="${f#${new_dir}/}"
    sync_one_file "${rel}/${sub}"
  done < <(find "$new_dir" -type f -print0)
}

echo "[1/6] Sync config files (diff + backup + atomic install)"
for item in "${SYNC_ITEMS[@]}"; do
  if [ -f "${RELEASE_DIR}/${item}" ]; then
    sync_one_file "$item"
  elif [ -d "${RELEASE_DIR}/${item}" ]; then
    sync_one_dir "$item"
  fi
done

if [ "$changed_any" -eq 0 ]; then
  echo "✅ No changes detected. Nothing to apply."
  exit 0
fi

echo "[2/6] Validate docker compose config"
# Validate prod compose
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml config -q
# Validate monitoring compose if present on server
if [ -f infra/monitoring/docker-compose.monitoring.prod.yml ]; then
  docker compose -f infra/monitoring/docker-compose.monitoring.prod.yml config -q
fi

echo "[3/6] Apply monitoring stack if changed"
if [ "$changed_monitoring" -eq 1 ] && [ -f infra/monitoring/docker-compose.monitoring.prod.yml ]; then
  docker compose -f infra/monitoring/docker-compose.monitoring.prod.yml up -d
fi

echo "[4/6] Reconcile prod stack if compose changed"
if [ "$changed_prod_compose" -eq 1 ]; then
  docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml up -d
fi

echo "[5/6] Zero-downtime reload Caddy if Caddyfile changed"
if [ "$changed_caddy" -eq 1 ]; then
  # Caddyfile is mounted into container; reload picks it up
  docker exec gov-caddy-prod caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
fi

echo "[6/6] Post-apply smoke (health + metrics blocked)"
smoke() {
  local ok=0
  for i in $(seq 1 45); do
    if curl -kfsS "${PROD_PUBLIC_BASE_URL}/health" >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 1
  done
  [ "$ok" -eq 1 ] || return 1

  # metrics must be blocked by caddy: expect 403
  code="$(curl -k -s -o /dev/null -w "%{http_code}" "${PROD_PUBLIC_BASE_URL}/metrics" || true)"
  [ "$code" = "403" ] || return 1
  return 0
}

if smoke; then
  echo "✅ CONFIG SYNC OK"
  echo "Backup (if needed): $BACKUP_DIR"
  exit 0
fi

echo "❌ SMOKE FAILED -> ROLLBACK CONFIG from: $BACKUP_DIR"
# Restore only what we backed up
# (files absent previously won't be removed; acceptable for config sync)
if [ -d "$BACKUP_DIR" ]; then
  (cd "$BACKUP_DIR" && find . -type f -print0) | while IFS= read -r -d '' f; do
    rel="${f#./}"
    src="${BACKUP_DIR}/${rel}"
    dst="${PROD_DEPLOY_PATH}/${rel}"
    echo "RESTORE: $rel"
    mkdir -p "$(dirname "$dst")"
    cp -a "$src" "$dst"
  done
fi

# Re-apply runtime actions (compose reconcile + caddy reload) after restore
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml up -d || true
if [ -f infra/monitoring/docker-compose.monitoring.prod.yml ]; then
  docker compose -f infra/monitoring/docker-compose.monitoring.prod.yml up -d || true
fi
docker exec gov-caddy-prod caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile || true

if smoke; then
  echo "✅ ROLLBACK OK (config restored)"
else
  echo "❌ ROLLBACK ALSO FAILED (manual intervention required)"
fi

exit 1
