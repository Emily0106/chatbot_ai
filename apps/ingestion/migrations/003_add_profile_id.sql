ALTER TABLE ingestion_jobs
ADD COLUMN IF NOT EXISTS profile_id UUID;
