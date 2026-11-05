-- Add job metadata payload for tenant-safe worker processing.
ALTER TABLE IF EXISTS ingestion_jobs
  ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;
