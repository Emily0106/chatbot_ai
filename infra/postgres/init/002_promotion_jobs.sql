-- infra/postgres/init/002_promotion_jobs.sql

CREATE TABLE IF NOT EXISTS promotion_jobs (
    job_id UUID PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    temp_doc_id VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING', -- PENDING, RUNNING, DONE, FAILED
    content_hash VARCHAR(64) NOT NULL, -- SHA256 for idempotency
    
    filename VARCHAR(512),
    kb_doc_id VARCHAR(255), -- Populated when DONE
    
    attempt_count INT DEFAULT 0,
    next_retry_at TIMESTAMP,
    last_error_message TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Idempotency: Same tenant + same content = same job
    CONSTRAINT uq_promotion_idempotency UNIQUE (tenant_id, content_hash)
);

CREATE INDEX idx_promotion_jobs_tenant ON promotion_jobs(tenant_id);
CREATE INDEX idx_promotion_jobs_status ON promotion_jobs(status);
