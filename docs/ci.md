# CI/CD & Smoke Tests Guide

This document outlines the CI/CD pipeline configuration, smoke testing strategy, and how to reproduce/debug issues locally.

## CI Workflow
The pipeline is defined in `.gitlab-ci.yml` and consists of 3 stages:

1.  **guardrails** (`parity-check`):
    *   Verifies configuration parity between Backend, Ingestion, and Vector DB.
    *   Ensures critical constants (Dimension=768, Collection Name, etc.) are aligned.
    *   **Env**: `python:3.10-slim`, installs system deps (`libpq-dev`) and runs Qdrant service.

2.  **unit-tests** (`backend-unit`):
    *   Runs fast, isolated unit tests.
    *   **Scope**: `apps/backend/src/test_agent_certification.py` and strictly unit-scoped tests.
    *   **Excluded**: E2E integration tests requiring full environment.

3.  **integration-smoke** (`smoke-test`):
    *   Runs full system integration verification.
    *   **Services**: Postgres 15, Qdrant.
    *   **Steps**:
        1.  Wait for DB services (socket/curl checks).
        2.  Initialize DB & Seed Data (`dev_fast_setup.py --embed mock`).
        3.  Verify Agent Flows (`verify_agent_flow.py`).
        4.  Run API Smoke Check (`ci_smoke.py`).
    *   **Key CI Variables**:
        *   `EMBEDDING_PROVIDER="mock"`: Forces mock embeddings to avoid OpenAI dependency.
        *   `RERANK_ENABLED="0"`: Disables heavy reranker to prevent CPU timeouts.
        *   `CI_SMOKE_LOG_CHARS="4000"`: Increases failure log verbosity.

## Local Debugging
### 1. Prerequisites
Ensure you have the required dependencies and services running (or mocked).

### 2. Running Smoke Tests Locally
To reproduce CI behavior locally:

```bash
# 1. Export CI-like environment variables
export EMBEDDING_PROVIDER=mock
export RERANK_ENABLED=0
export PYTHONPATH=$(pwd)/apps/backend/src:$(pwd)/libs/core_shared

# 2. Run the smoke script
python3 scripts/ci_smoke.py
```

### 3. Verify System Parity
```bash
python3 scripts/verify_parity.py
```
*Note: Requires running Qdrant instance.*

## CI Contract & Design Principles
*   **Fail Fast**: Guardrails run first.
*   **Offline First**: Smoke tests use Mock Embeddings and do not call external LLM APIs (OpenAI/Anthropic).
*   **Robustness**: Tests validate **Schema** and **Refusal Codes**, not specific dynamic content strings.
*   **Isolation**: Each job sets up its own environment (no side effects).

## Troubleshooting
*   **YAML Errors**: Use block scalar (`|`) for multi-line scripts in `.gitlab-ci.yml`.
*   **Dependency Failures**: Check `apt-get install` in `before_script` for compiled libs like `psycopg2`.
*   **Connection Refused**: Ensure explicit wait loops for Postgres/Qdrant are present before testing.
