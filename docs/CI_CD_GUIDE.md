# CI/CD Gatekeeper Guide

## Overview
This repository uses GitLab CI/CD to enforce strict quality gates on every Merge Request (MR). The pipeline ensures that no configuration drift (Vector Dim, Collection Name) occurs and that critical Agent flows remain functional.

## Pipeline Stages

### 1. Guardrails (`guardrails`)
- **Job**: `parity-check`
- **Purpose**: Prevents configuration drift.
- **Checks**:
  - `VECTOR_DIM` == 768
  - `QDRANT_COLLECTION` matches default
  - `EMBEDDING_MODEL_ID` is consistent
- **Failure**: Immediate pipeline stop. Fix `config.py` or `.env`.

### 2. Unit Tests (`unit-tests`)
- **Job**: `backend-unit`
- **Purpose**: Validates logic without external dependencies.
- **Scope**: `apps/backend/src` (Pytest)

### 3. Integration Smoke (`integration-smoke`)
- **Job**: `smoke-test`
- **Purpose**: Verifies end-to-end system Health with ephemeral services.
- **Services**: Postgres + Qdrant (Docker Services in CI).
- **Steps**:
  1. **Fast Setup**: Resets CI DB schemas (`dev_fast_setup.py`).
  2. **Agent Verification**: Runs `verify_agent_flow.py` (Legal, Citizen agents).
  3. **System Smoke**: Runs `dev_smoke.py`.

## Local Verification (Developers)

Before pushing code, run the local CI simulation script. This closely mirrors the CI pipeline using your local docker services.

### Prerequisites
- Docker services running (Postgres, Qdrant, Redis).
- `env/.env.ci` exists (template provided).

### Command
```bash
./scripts/test_ci_local.sh
```

### Troubleshooting
- **Parity Fail**: Check if you changed `VECTOR_DIM` or Collection Name in `apps/backend/src/app/config.py`.
- **Smoke Fail**: Ensure your local Qdrant/Postgres are healthy. The script performs a **destructive reset** on the database defined in `.env.ci` (default: `gov_chat_ci`).
- **Missing Deps**: Run `pip install -r apps/backend/src/requirements.txt`.

## Environment Variables
- **`env/.env.ci`**: The source of truth for CI execution. **DO NOT commit secrets** here.
- **`env/.env.example`**: Copy this to `.env` for local development.
