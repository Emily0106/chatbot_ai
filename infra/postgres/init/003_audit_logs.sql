-- 003_audit_logs.sql
CREATE TABLE IF NOT EXISTS audit_log_events (
    event_id UUID PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    tenant_id VARCHAR(255) NOT NULL,
    actor_type VARCHAR(50) NOT NULL, -- 'user', 'system'
    actor_id VARCHAR(255), -- user_id or system component name
    action VARCHAR(100) NOT NULL, -- e.g., 'TEMP_UPLOAD_CREATED', 'PROMOTION_JOB_CREATED'
    entity_type VARCHAR(50), -- 'temp_doc', 'promotion_job', 'kb_doc'
    entity_id VARCHAR(255),
    trace_id VARCHAR(255),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant_id ON audit_log_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log_events(action);
