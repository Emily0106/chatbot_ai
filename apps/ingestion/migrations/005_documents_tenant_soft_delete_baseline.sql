-- Migration: 005_documents_tenant_soft_delete_baseline.sql
-- Purpose:
--   1) Close schema drift for tenant-safe delete/reindex and ops list endpoints.
--   2) Keep migration idempotent for both fresh and existing volumes.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS ingestion_profiles (
  profile_id UUID PRIMARY KEY,
  tenant_id  TEXT NOT NULL,
  name       TEXT NOT NULL,
  description TEXT NULL,
  config     JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS registered_sources (
  id               UUID PRIMARY KEY,
  tenant_id        TEXT NOT NULL,
  server_id        TEXT NOT NULL,
  path             TEXT NOT NULL,
  profile_id       UUID NOT NULL REFERENCES ingestion_profiles(profile_id),
  enabled          BOOLEAN NOT NULL DEFAULT true,
  last_seen_at     TIMESTAMPTZ NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, server_id, path)
);

CREATE TABLE IF NOT EXISTS audit_logs (
  log_id           UUID PRIMARY KEY,
  tenant_id        TEXT NOT NULL,
  user_id          TEXT NOT NULL,
  action           TEXT NOT NULL,
  resource_id      TEXT NOT NULL,
  details          JSONB NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at DESC);

ALTER TABLE ingestion_jobs
  ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE ingestion_jobs
  ADD COLUMN IF NOT EXISTS profile_id UUID NULL;

ALTER TABLE ingestion_jobs
  ADD COLUMN IF NOT EXISTS approved_by TEXT NULL;

ALTER TABLE ingestion_jobs
  ADD COLUMN IF NOT EXISTS approver_role TEXT NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.table_constraints
    WHERE table_schema = 'public'
      AND table_name = 'ingestion_jobs'
      AND constraint_name = 'fk_ingestion_jobs_profile_id'
  ) THEN
    NULL;
  ELSE
    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'ingestion_jobs'
        AND column_name = 'profile_id'
    ) THEN
      ALTER TABLE ingestion_jobs
        ADD CONSTRAINT fk_ingestion_jobs_profile_id
        FOREIGN KEY (profile_id) REFERENCES ingestion_profiles(profile_id);
    END IF;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status
  ON ingestion_jobs(status);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_doc_id
  ON ingestion_jobs(doc_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_meta_tenant
  ON ingestion_jobs ((COALESCE(meta->>'tenant_id', '')));

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = 'documents'
  ) THEN
    ALTER TABLE documents
      ADD COLUMN IF NOT EXISTS tenant_id TEXT;

    ALTER TABLE documents
      ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;

    ALTER TABLE documents
      ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL;

    ALTER TABLE documents
      ADD COLUMN IF NOT EXISTS security_level INTEGER NULL;

    UPDATE documents
    SET tenant_id = 'default'
    WHERE tenant_id IS NULL OR btrim(tenant_id) = '';

    ALTER TABLE documents
      ALTER COLUMN tenant_id SET DEFAULT 'default';

    ALTER TABLE documents
      ALTER COLUMN tenant_id SET NOT NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_documents_tenant_id
  ON documents(tenant_id);

CREATE INDEX IF NOT EXISTS idx_documents_tenant_deleted
  ON documents(tenant_id, is_deleted);

CREATE INDEX IF NOT EXISTS idx_documents_doc_id_tenant
  ON documents(doc_id, tenant_id);

