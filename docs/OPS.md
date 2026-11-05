# Ops Console (Internal MVP)

## Purpose

Internal web console for operations/debug:

- List ingestion jobs (tenant-scoped)
- List documents with filters and counts
- Inspect and bump `tenant_epoch` (`rag:tenant_epoch:{tenant_id}`)
- Trigger delete/reindex actions for a document

## Backend Config

Set environment variables for backend:

```bash
OPS_CONSOLE_ENABLED=true
OPS_ADMIN_KEY=<strong-secret>
INGEST_INTERNAL_TOKEN=<strong-internal-token>
# Optional override (default uses INGESTION_BASE_URL, then fallback http://ingest-api:8010)
OPS_INGESTION_BASE_URL=http://ingest-api:8010
OPS_HTTP_TIMEOUT_S=12
```

`INGEST_INTERNAL_TOKEN` must be set to the same value on:

- backend (for `X-Internal-Token` header to ingestion)
- ingest-api (to validate internal requests)
- ingest-worker (for consistency across worker-side ingestion calls)

## Access

### Header mode (recommended)

```bash
curl -H "X-Admin-Key: <strong-secret>" http://localhost:8000/ops
```

### Login form mode

Open:

`http://localhost:8000/ops/login`

Submit `OPS_ADMIN_KEY` once; backend sets short-lived admin session cookie.

## Frontend Chat UI (MVP)

`frontend` service serves `apps/frontend/index.html` at:

`http://localhost:5173`

UI capabilities:

- Loads agent catalog from `GET /api/agents`
- Selects agent and sends chat requests to `POST /api/chat`
- Supports optional stream mode toggle (`stream: true`)
- Renders citations and API error states (`403`, `429`, `5xx`)

Runtime setup in UI (not committed):

- `API Base URL` (default `http://localhost:8000`)
- `X-API-Key` (stored in browser localStorage only)
- `tenant_id` (optional payload field; backend still enforces tenant from auth claims)

Security note:

- Ops Console admin key is never embedded in FE.
- `/ops` link opens backend route, but still requires separate `X-Admin-Key`.

## Migrations (Ingestion)

Compose includes a one-shot migration service `ingest-migrate` that runs before backend/ingest-api/ingest-worker start:

- command: `python -m app.migrations.apply_migrations --migrations-dir /app/migrations`
- tracking table: `ingestion_schema_migrations`
- migration files: `apps/ingestion/migrations/*.sql`

This removes the need for manual `ALTER TABLE` when reusing old volumes.

## Compose Profiles

Default `infra/compose/docker-compose.yml` does not publish ingest-api host ports.

- Internal access only: `expose: 8010`
- Debug host access (temporary): `infra/compose/docker-compose.debug.yml`

Example:

```bash
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.debug.yml up -d
```

## Actions

From UI buttons or direct HTTP:

- `POST /ops/action/delete` (`tenant_id`, `doc_id`)
- `POST /ops/action/reindex` (`tenant_id`, `doc_id`)
- `POST /ops/action/bump-epoch` (`tenant_id`)

All actions require admin auth and emit structured `audit` logs with:

- `request_id`
- `actor`
- `tenant_id`
- `doc_id` (when applicable)
- `action`
- `status`

## E2E Gate Note

For the destructive cache gate (`warm-cache -> delete -> chat`), run ingestion and worker on the same compose network/filesystem context.

- Recommended: run the gate through compose/internal endpoints (`backend -> ingest-api`).
- Avoid mixing host-run ingestion API with containerized worker for this gate, because file `source_uri` paths can differ between host and container mounts.
