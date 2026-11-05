-- migrations/001_init.sql
-- Run once (dev/test):
--   psql "$DATABASE_URL" -f migrations/001_init.sql


-- Extensions
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =========================
-- documents
-- =========================
CREATE TABLE IF NOT EXISTS documents (
  doc_id           UUID PRIMARY KEY,
  scope            TEXT NOT NULL,
  commune_id        TEXT NULL,
  doc_category      TEXT NOT NULL,
  title            TEXT NOT NULL,
  source_uri       TEXT NOT NULL,
  mime_type        TEXT NOT NULL,
  checksum         TEXT NOT NULL,
  pipeline_version TEXT NOT NULL DEFAULT 'v1',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_scope_commune_cat
  ON documents(scope, commune_id, doc_category);

CREATE INDEX IF NOT EXISTS idx_documents_checksum
  ON documents(checksum);

-- =========================
-- chunks
-- =========================
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id        UUID PRIMARY KEY,
  doc_id          UUID NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  parent_chunk_id UUID NULL,

  scope        TEXT NOT NULL,
  commune_id   TEXT NULL,
  doc_category TEXT NOT NULL,
  chunk_kind   TEXT NOT NULL,
  order_index  INTEGER NOT NULL DEFAULT 0,

  display_text TEXT NOT NULL,
  embed_text   TEXT NULL,

  citation JSONB NOT NULL,

  source_uri TEXT NOT NULL,
  mime_type  TEXT NOT NULL,
  checksum   TEXT NOT NULL,

  page_start INTEGER NULL,
  page_end   INTEGER NULL,
  sheet_name TEXT NULL,
  row_start  INTEGER NULL,
  row_end    INTEGER NULL,
  anchor     TEXT NULL,

  law_ref      TEXT NULL,
  section_path TEXT NULL,

  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT chk_chunks_order_index_nonneg CHECK (order_index >= 0),
  CONSTRAINT chk_chunks_page_range CHECK (
    page_start IS NULL OR page_end IS NULL OR page_end >= page_start
  ),
  CONSTRAINT chk_chunks_row_range CHECK (
    row_start IS NULL OR row_end IS NULL OR row_end >= row_start
  )
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id
  ON chunks(doc_id);

CREATE INDEX IF NOT EXISTS idx_chunks_filter
  ON chunks(scope, commune_id, doc_category, chunk_kind);

CREATE INDEX IF NOT EXISTS idx_chunks_parent
  ON chunks(parent_chunk_id);

CREATE INDEX IF NOT EXISTS idx_chunks_citation_gin
  ON chunks USING GIN (citation);

-- =========================
-- structured_rows
-- =========================
CREATE TABLE IF NOT EXISTS structured_rows (
  row_id      UUID PRIMARY KEY,
  doc_id      UUID NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,

  commune_id   TEXT NULL,
  doc_category TEXT NOT NULL,

  sheet_name TEXT NULL,
  row_index  INTEGER NOT NULL,

  data_content JSONB NOT NULL,
  search_text  TEXT NOT NULL DEFAULT '',
  citation     JSONB NOT NULL,

  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (doc_id, sheet_name, row_index),

  CONSTRAINT chk_structured_rows_row_index_nonneg CHECK (row_index >= 0)
);

CREATE INDEX IF NOT EXISTS idx_structured_rows_doc_id
  ON structured_rows(doc_id);

CREATE INDEX IF NOT EXISTS idx_structured_rows_filter
  ON structured_rows(commune_id, doc_category);

-- JSON containment (fast for @> and existence queries)
CREATE INDEX IF NOT EXISTS idx_structured_rows_data_gin
  ON structured_rows USING GIN (data_content jsonb_path_ops);

-- Full-text search (simple)
CREATE INDEX IF NOT EXISTS idx_structured_rows_search_fts
  ON structured_rows USING GIN (to_tsvector('simple', coalesce(search_text, '')));

-- Entity search (fast ILIKE '%...%')
-- CREATE INDEX IF NOT EXISTS idx_rows_search_text_trgm
--   ON structured_rows USING GIN (search_text gin_trgm_ops);


-- =========================
-- ingestion_jobs
-- =========================
CREATE TABLE IF NOT EXISTS ingestion_jobs (
  job_id           UUID PRIMARY KEY,
  job_type         TEXT NOT NULL,
  
  scope            TEXT NOT NULL,
  commune_id       TEXT NULL,
  
  source_uri       TEXT NOT NULL,
  mime_type        TEXT NOT NULL,
  checksum         TEXT NOT NULL,
  title            TEXT NOT NULL,
  
  pipeline_version TEXT NOT NULL DEFAULT 'v1',
  doc_category_hint TEXT NULL,
  
  doc_id           UUID NULL,
  
  status           TEXT NOT NULL DEFAULT 'queued',
  progress         INTEGER NOT NULL DEFAULT 0,
  
  started_at       TIMESTAMPTZ NULL,
  finished_at      TIMESTAMPTZ NULL,
  error            TEXT NULL,
  
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status
  ON ingestion_jobs(status);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_doc_id
  ON ingestion_jobs(doc_id);
