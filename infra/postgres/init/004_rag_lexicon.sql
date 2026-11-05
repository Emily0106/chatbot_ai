-- Gov-Grade Query Expansion (PR-03): Global Lexicon 

CREATE TABLE IF NOT EXISTS rag_lexicon (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NULL,
    alias TEXT NOT NULL,
    alias_norm TEXT NOT NULL,
    canonical TEXT NOT NULL,
    canonical_norm TEXT NOT NULL,
    term_type TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    updated_by TEXT NULL,
    note TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_lexicon_alias_norm ON rag_lexicon (alias_norm);
CREATE INDEX IF NOT EXISTS idx_rag_lexicon_term_type ON rag_lexicon (term_type);

-- Unique partial index for global (tenant_id IS NULL)
CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_lexicon_global_uniq 
    ON rag_lexicon (alias_norm, canonical_norm, term_type) 
    WHERE tenant_id IS NULL;

-- Unique partial index for tenant (tenant_id IS NOT NULL)
CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_lexicon_tenant_uniq 
    ON rag_lexicon (tenant_id, alias_norm, canonical_norm, term_type) 
    WHERE tenant_id IS NOT NULL;


CREATE TABLE IF NOT EXISTS rag_lexicon_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Seed global_lexicon_version
INSERT INTO rag_lexicon_meta (key, value, updated_at)
VALUES ('global_lexicon_version', '1', now())
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at;
