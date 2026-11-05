# Secrets Management Guide

**Enterprise-grade secrets handling for Gov-AI Backend**

## Table of Contents
1. [Overview](#overview)
2. [Secret Types](#secret-types)
3. [GitLab CI/CD Variables](#gitlab-cicd-variables)
4. [Generating Secrets](#generating-secrets)
5. [Rotation Policy](#rotation-policy)
6. [What NEVER to Commit](#what-never-to-commit)
7. [Emergency Procedures](#emergency-procedures)

## Overview

This guide covers how to securely manage secrets for the Gov-AI Backend across development, staging, and production environments.

**Key Principles:**
- ✅ Secrets in GitLab CI/CD variables (masked + protected)
- ✅ Secrets in environment files (gitignored)
- ✅ Secrets rotated regularly
- ❌ NEVER commit secrets to git
- ❌ NEVER print full secrets in logs

## Secret Types

### Critical Secrets (Must Rotate Regularly)

| Secret | Purpose | Rotation Frequency | Where Used |
|--------|---------|-------------------|------------|
| `API_KEYS_JSON` | Backend authentication | 90 days | All API requests |
| `POSTGRES_PASSWORD` | Database access | 90 days | Backend → Postgres |
| `OPENAI_API_KEY` | LLM/Embedding API | As needed | Backend LLM calls |
| `QDRANT_WRITE_API_KEY` | Vector DB write | 90 days | Ingestion service |

### Infrastructure Secrets

| Secret | Purpose | Notes |
|--------|---------|-------|
| `DB_URL` | Full database connection string | Contains password |
| `REDIS_URL` | Cache connection string | Usually no auth in internal network |
| `S3_SECRET_KEY` | Object storage auth | For ingestion service |

### Configuration (Not Secret, But Environment-Specific)

| Variable | Purpose |
|----------|---------|
| `ENV_MODE` | Environment identifier (dev/staging/prod) |
| `QDRANT_URL` | Vector DB endpoint |
| `INGESTION_BASE_URL` | Internal service URL |

## GitLab CI/CD Variables

### Setting Variables

1. Navigate to **Settings → CI/CD → Variables** in GitLab
2. Click **Add Variable**
3. Configure:
   - **Type**: Variable
   - **Environment**: `staging` or `production`
   - **Flags**:
     - ☑ **Protect variable** (only use in protected branches)
     - ☑ **Mask variable** (hide in logs)
     - ☐ **Expand variable** (usually off)

### Naming Convention

Use environment prefixes to keep variables organized:

**Staging:**
```
STAGING_ENV_MODE=staging
STAGING_API_KEYS_JSON={"key1":"tenant1"}
STAGING_DB_URL=postgresql+asyncpg://...
STAGING_POSTGRES_PASSWORD=...
STAGING_OPENAI_API_KEY=sk-...
```

**Production:**
```
PROD_ENV_MODE=prod
PROD_API_KEYS_JSON={"key1":"tenant1"}
PROD_DB_URL=postgresql+asyncpg://...
PROD_POSTGRES_PASSWORD=...
PROD_OPENAI_API_KEY=sk-...
```

### Example GitLab CI Usage

```yaml
deploy-staging:
  stage: deploy
  environment: staging
  script:
    - export ENV_MODE=$STAGING_ENV_MODE
    - export API_KEYS_JSON=$STAGING_API_KEYS_JSON
    - export DB_URL=$STAGING_DB_URL
    - export OPENAI_API_KEY=$STAGING_OPENAI_API_KEY
    - python3 scripts/preflight_env.py  # Validate before deploy
    - docker compose -f infra/compose/docker-compose.staging.yml up -d
  only:
    - main
```

## Generating Secrets

### API Keys (API_KEYS_JSON)

**Format:**
```json
{
  "<api-key>": "<tenant-id>",
  "<api-key>": "<tenant-id>",
  ...
}
```

**Generate Strong API Keys:**

```bash
# Generate a random 32-character API key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Example output: Xk7mP9vQwRtYuI2oLpKjH3gFdS8aZ1bN4cV6xM

# Or using openssl
openssl rand -base64 32
```

**Example API_KEYS_JSON:**
```json
{
  "Xk7mP9vQwRtYuI2oLpKjH3gFdS8aZ1bN4cV6xM": "tenant-gov-hanoi",
  "A5bC8dE1fG2hJ3kL4mN6pQ7rS9tU0vW2xY4zA": "tenant-gov-hcm"
}
```

**⚠️ Security Notes:**
- Minimum 32 characters
- Use cryptographically secure random generation
- Different keys for each environment
- Never reuse keys across environments

### Database Passwords

```bash
# Generate strong password (20+ characters)
python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters + string.digits + '!@#$%^&*') for _ in range(24)))"
```

Requirements:
- Minimum 20 characters
- Mix of uppercase, lowercase, digits, symbols
- Different for each environment
- Avoid special shell characters in automated scripts

### OpenAI API Key

- Obtain from https://platform.openai.com/api-keys
- Create separate keys for staging and production
- Set usage limits to prevent unexpected charges
- Name keys clearly (e.g., "Gov-AI-Staging", "Gov-AI-Production")

## Rotation Policy

### Regular Rotation Schedule

| Secret Type | Frequency | Process |
|-------------|-----------|---------|
| API Keys | 90 days | See [API Key Rotation](#api-key-rotation) |
| Database Password | 90 days | See [Database Password Rotation](#database-password-rotation) |
| OpenAI API Key | As needed | Rotate if compromised or annually |

### API Key Rotation

**Zero-downtime rotation:**

1. **Generate new keys** (keep old keys active)
   ```json
   {
     "old-key-abc123": "tenant-1",
     "new-key-xyz789": "tenant-1"
   }
   ```

2. **Update clients** to use new keys (gradual rollout)

3. **Monitor usage** of old keys (check metrics/logs)

4. **Remove old keys** after grace period (7-14 days)
   ```json
   {
     "new-key-xyz789": "tenant-1"
   }
   ```

5. **Update GitLab variable** `STAGING_API_KEYS_JSON` or `PROD_API_KEYS_JSON`

6. **Restart backend** to load new keys

### Database Password Rotation

**Requires brief downtime or connection pool restart:**

1. **Update password in database:**
   ```sql
   ALTER USER staging_user WITH PASSWORD 'new-password';
   ```

2. **Update environment variable** immediately

3. **Restart backend** with new credentials

4. **Verify** connection via health check

### Emergency Rotation (Compromise Detected)

1. **Immediately revoke** compromised credentials
2. **Generate new secrets** using guides above
3. **Update all environments** ASAP
4. **Audit access logs** to assess impact
5. **Document incident** for post-mortem

## What NEVER to Commit

### ❌ NEVER Commit These Files

```
.env
.env.staging
.env.production
.env.*.local
*.pem
*.key
*.p12
id_rsa*
*.secret
secrets.yaml
credentials.json
```

**Verify `.gitignore` includes:**
```gitignore
.env
.env.staging
.env.production
.env.*.local
```

### ❌ NEVER Commit These Values

- API keys, tokens, passwords
- Database connection strings with passwords
- Private keys, certificates
- OAuth client secrets
- Service account credentials

### ✅ Safe to Commit (Templates)

- `.env.example` (with placeholders, no real values)
- `.env.staging.template` (with placeholders)
- Documentation referencing secret names (not values)

## Security Best Practices

### 1. Principle of Least Privilege

- Backend: read-only database access where possible
- Ingestion: write access to vector DB, read-only to metadata DB
- Different credentials for each service

### 2. Audit Secret Access

**Monitor:**
- API key usage in metrics (`govai_chat_requests_total` by `tenant_id`)
- Database connection attempts in Postgres logs
- Failed authentication attempts

**Alert on:**
- Unusual access patterns
- Failed authentication spikes
- Access from unexpected IPs (if available)

### 3. Secret Storage

**Development:**
- `.env` file (gitignored, local only)
- Never in application code

**Staging/Production:**
- GitLab CI/CD variables (masked + protected)
- Environment variables in deployment scripts
- OR external secret managers (Vault, AWS Secrets Manager, GCP Secret Manager)

### 4. Code Review Checklist

Before merging:
- [ ] No hardcoded secrets
- [ ] No secrets in logs/debug output
- [ ] Secrets properly referenced from environment
- [ ] New secrets documented in this guide

## Emergency Procedures

### Key Compromise Detected

1. **Assess Scope:**
   - Which secret(s) compromised?
   - Which environments affected?
   - When did compromise occur?

2. **Immediate Actions:**
   - Revoke compromised credentials
   - Generate and deploy new credentials
   - Monitor for unauthorized access

3. **Investigation:**
   - Review application logs
   - Check GitLab audit logs
   - Identify root cause

4. **Remediation:**
   - Fix vulnerability
   - Update procedures
   - Document lessons learned

### Accidental Commit of Secrets

1. **DO NOT** just delete the file and commit again (secret remains in git history)

2. **Revoke the secret immediately**

3. **Rewrite git history** (dangerous, coordinate with team):
   ```bash
   # Use git-filter-branch or BFG Repo-Cleaner
   # This is complex - see https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
   ```

4. **Force push** (if history rewritten)

5. **Rotate all potentially exposed secrets**

6. **Force re-clone** for all team members

**Prevention:**
- Use pre-commit hooks (e.g., `detect-secrets`, `git-secrets`)
- Enable GitLab push protection for secrets

## Tools & Automation

### Recommended Tools

- **detect-secrets**: Pre-commit hook to prevent secret commits
- **git-secrets**: AWS tool to prevent committing secrets
- **env-lint**: Use `scripts/preflight_env.py` before deployment

### Pre-commit Hook (Optional)

```bash
# Install detect-secrets
pip install detect-secrets

# Initialize baseline
detect-secrets scan > .secrets.baseline

# Add to .pre-commit-config.yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

## References

- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [GitLab CI/CD Variables Documentation](https://docs.gitlab.com/ee/ci/variables/)
- [NIST SP 800-63B: Digital Identity Guidelines](https://pages.nist.gov/800-63-3/sp800-63b.html)

## Support

For questions or to report security issues:
- Internal: Contact security team
- Email: security@example.com
- Urgent: PagerDuty security oncall
