# GitLab CI/CD Variables Reference

## Required Variables for D4.2 Deployment

Configure these in **Settings → CI/CD → Variables** (all should be **Protected** and **Masked** where applicable).

### SSH Access
| Variable | Type | Protected | Masked | Example | Description |
|----------|------|-----------|--------|---------|-------------|
| `PROD_SSH_HOST` | Variable | ✅ | ❌ | `prod.example.com` | Production server hostname or IP |
| `PROD_SSH_USER` | Variable | ✅ | ❌ | `deploy` | SSH user for deployment |
| `PROD_SSH_PRIVATE_KEY` | Variable | ✅ | ✅ | `-----BEGIN...` | SSH private key (full content) |
| `PROD_SSH_PORT` | Variable | ✅ | ❌ | `22` | SSH port (optional, defaults to 22) |
| `PROD_SSH_KNOWN_HOSTS` | Variable | ✅ | ❌ | `prod.example.com ssh-ed25519 AAAA...` | Pinned SSH host key (run `ssh-keyscan -H <host>` once) |

### Deployment Paths
| Variable | Type | Protected | Masked | Example | Description |
|----------|------|-----------|--------|---------|-------------|
| `PROD_DEPLOY_PATH` | Variable | ✅ | ❌ | `/srv/govai` | Absolute path on server containing compose files |
| `PROD_PUBLIC_BASE_URL` | Variable | ✅ | ❌ | `https://api.example.com` | Public URL for health checks |

### Container Registry
| Variable | Type | Protected | Masked | Example | Description |
|----------|------|-----------|--------|---------|-------------|
| `PROD_REGISTRY` | Variable | ✅ | ❌ | `registry.gitlab.com` | Container registry URL |
| `PROD_REGISTRY_USER` | Variable | ✅ | ❌ | `gitlab+deploy-token-1` | Deploy token user |
| `PROD_REGISTRY_PASSWORD` | Variable | ✅ | ✅ | `token-password` | Deploy token password |

## Production Server Prerequisites

### One-Time Setup
```bash
# Create deployment directory
mkdir -p /srv/govai/ops
cd /srv/govai

# Copy compose files and configurations
# (via rsync or manual upload)

# Ensure docker compose is available
docker compose version

# Test registry login
echo "$REGISTRY_PASSWORD" | docker login registry.gitlab.com -u "$REGISTRY_USER" --password-stdin
```

### Required Files on Server
- `${PROD_DEPLOY_PATH}/infra/compose/docker-compose.prod.yml`
- `${PROD_DEPLOY_PATH}/.env.prod` (with production secrets)
- `${PROD_DEPLOY_PATH}/ops/` (directory for rollback markers)

## Built-in GitLab Variables Used
- `$CI_COMMIT_SHA` - Git commit SHA (for image tagging)
- `$CI_REGISTRY_IMAGE` - GitLab container registry path
- `$CI_REGISTRY_USER` / `$CI_REGISTRY_PASSWORD` - Built-in registry auth
- `$CI_COMMIT_BRANCH` - Git branch name

## Security Notes
- All secrets should be **Masked** to prevent exposure in logs
- SSH key should be **Protected** to main branch only
- Use dedicated **Deploy Tokens** (not personal access tokens)
- Set **Environment protection** on production environment
