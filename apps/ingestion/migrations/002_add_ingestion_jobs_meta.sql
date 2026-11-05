-- Migration: 002_add_ingestion_jobs_meta.sql
-- Description: Adds JSONB 'meta' column to ingestion_jobs for strict context storage (tenant_id, etc.)

ALTER TABLE ingestion_jobs
ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;
