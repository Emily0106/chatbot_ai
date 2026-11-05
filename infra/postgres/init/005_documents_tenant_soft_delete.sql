-- 005_documents_tenant_soft_delete.sql
-- Add tenant ownership and soft-delete lifecycle to documents table.

ALTER TABLE documents
ADD COLUMN IF NOT EXISTS tenant_id TEXT;

ALTER TABLE documents
ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE documents
ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_documents_tenant_doc
  ON documents(tenant_id, doc_id);
