# Ingestion Ownership Backfill Runbook

## Current behavior (fail-closed)
- Documents with `documents.tenant_id IS NULL` are treated as unowned.
- API ownership checks for `DELETE /docs/{doc_id}` and `/docs/{doc_id}/reindex` return `404` for these records.
- Worker ownership checks also fail closed, so destructive cross-tenant actions are blocked.

## Backfill options
1. Manual mapping file
- Prepare `doc_id -> tenant_id` mapping from audited business records.
- Apply with an explicit SQL update in controlled batches.

2. Recover from ingestion job metadata
- Use `ingestion_jobs.meta->>'tenant_id'` for jobs linked to each `doc_id`.
- Only backfill rows where mapping is unique and non-empty.

3. Admin-assisted reconciliation tool
- Build an internal-only admin workflow to review unresolved docs and assign tenant ownership.
- Every assignment must be audited with actor and timestamp.

## Safe procedure
1. Snapshot unresolved rows.
```sql
SELECT doc_id, source_uri, created_at, updated_at
FROM documents
WHERE tenant_id IS NULL
ORDER BY created_at;
```

2. Generate candidate mapping (preferred: jobs metadata), then review conflicts.
```sql
SELECT
  j.doc_id,
  j.meta->>'tenant_id' AS tenant_id,
  COUNT(*) AS seen
FROM ingestion_jobs j
WHERE j.doc_id IS NOT NULL
  AND COALESCE(j.meta->>'tenant_id', '') <> ''
GROUP BY j.doc_id, j.meta->>'tenant_id'
ORDER BY j.doc_id, seen DESC;
```

3. Backfill only verified mappings inside a transaction.
```sql
BEGIN;
UPDATE documents d
SET tenant_id = m.tenant_id,
    updated_at = now()
FROM backfill_doc_tenant_map m
WHERE d.doc_id = m.doc_id
  AND d.tenant_id IS NULL;
COMMIT;
```

4. Verify completion.
```sql
SELECT COUNT(*) AS unresolved_docs
FROM documents
WHERE tenant_id IS NULL;
```

## Ownership verification query
```sql
SELECT tenant_id, COUNT(*) AS doc_count
FROM documents
GROUP BY tenant_id
ORDER BY doc_count DESC;
```

## Rollback note
- Keep a pre-backfill export of `(doc_id, tenant_id, updated_at)` for rollback.
- If reconciliation quality is uncertain, stop after batch 1 and verify endpoint behavior before continuing.
