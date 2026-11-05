# Epic Closeout: Gov-Grade Query Expansion

> **Status:** Phase-1 Complete (PR-01 → PR-10)
> **Date:** 2026-02-25
> **Branch lineage:** `main` ← PR-01..09 merged sequentially

---

## 1. Objective

Improve retrieval recall for Vietnamese government document search by expanding user queries through deterministic (lexicon + rules) and constrained LLM rewriting, while maintaining **fail-closed security**, **no PII leakage**, and **< 800ms retrieval budget**.

## 2. Deliverables

| PR | Component | Key Files | Tests |
|----|-----------|-----------|-------|
| 01 | Schemas (`QueryExpansionConfig`, `QueryPack`, `VariantItem`) | `schemas.py` | `test_query_expansion_schemas.py` |
| 02 | Preprocess (normalize, must-keep tokens, PII redact, injection detect) | `preprocess.py` | `test_query_expansion_preprocess.py` |
| 03 | Lexicon DB + Repo (global synonym table, `match()`, `version()`) | `lexicon_repo.py`, migration | `test_query_expansion_lexicon_repo.py` |
| 04 | Lexicon Expander (deterministic synonym substitution) | `lexicon_expander.py` | `test_query_expansion_lexicon_expander.py` |
| 05 | Rule-based Rewriter (code-query, penalty, reissue patterns) | `rule_rewriter.py` | `test_query_expansion_rules.py` |
| 06 | LLM Rewriter (constrained, 300ms hard timeout, strict JSON schema) | `llm_rewriter.py`, `llm_schema.py` | `test_query_expansion_llm_rewriter.py` |
| 07 | Engine Orchestration (preprocess → lexicon → rules → LLM → dedupe → clamp) | `engine.py` | `test_query_expansion_engine.py` |
| 08 | Retrieval Integration (concurrent Qdrant multi-search, OR tsquery Postgres) | `retrieve.py`, `db_lexical.py` | `test_query_expansion_retrieval_integration.py` |
| 09 | Audit Enrichment (`rag.access` with expansion metrics, no raw query) | `chat.py`, `retrieve.py` | `test_query_expansion_audit_enrichment.py` |
| 10 | Streaming audit parity (`rag.access` QE fields in streaming path) | `qe_meta.py`, `chat.py` | `test_query_expansion_streaming_audit_parity.py` |

**Total:** 10 PRs, ~19 source files, ~11 test files, all green.

## 3. Security & Compliance Controls

| Control | Implementation |
|---------|---------------|
| **Fail-closed defaults** | `ENABLE_QUERY_EXPANSION` env = `"0"` (off). Config `max_*_variants` bounded. |
| **No PII in logs** | Audit payload contains only counts/flags/hashes. Raw query never logged. Tests assert `original_query`/`redacted_query` absent. |
| **No filter relaxation** | Policy `q_filter` applied identically to all variant searches. No privilege escalation. |
| **Injection guard** | `disable_llm_if_injection_suspected=True`. Heuristic regex blocks LLM call on suspicious input. |
| **LLM timeout** | Hard 300ms. On timeout → drop LLM variants, keep deterministic only. |
| **SQL injection prevention** | All FTS queries use bind params (`:q0`, `:q1`, `:cfg`). No string concatenation. |

## 4. Risk Register

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| LLM rewrite latency pushes retrieval > 800ms | Medium | Hard timeout 300ms + asyncio semaphore(6) | ⚠️ Needs P95 benchmark |
| Vector weight scaling drifts ranking vs lexical | Low | Phase-2 RRF weighted fusion | Accepted |
| Streaming path missing audit enrichment | Medium | PR-10 (streaming audit parity) | ✅ Mitigated |
| Lexicon staleness (global only, no per-tenant) | Low | Phase-2 per-tenant lexicon | Accepted |
| LLM hallucinated variants bypass must-keep | Low | `must_keep_ok` validation strips non-compliant variants | ✅ Mitigated |

## 5. Benchmark Plan (Latency P95 < 800ms)

### Metrics to capture

| Metric | Source | Target |
|--------|--------|--------|
| `qe.preprocess_ms` | `retrieve.py` debug | < 5ms |
| `qe.engine_total_ms` | `retrieve.py` debug | < 350ms |
| `qe.llm_timeout_rate` | audit log `llm_timeout` | < 10% |
| `qe.qdrant_multi_ms` | per-variant timing | < 200ms (P95) |
| `qe.lexical_or_ms` | `db_lexical` timing | < 100ms |
| **retrieval_total_ms** | end-to-end | **< 800ms (P95)** |

### Load test scenarios

1. **Citizen queries** — "thủ tục đăng ký khai sinh", "quy trình cấp sổ đỏ" (typical 3-5 variants)
2. **Code queries** — "nghị định 43/2014/NĐ-CP", "thông tư 24/2014" (rule-based expansion)
3. **PII queries** — queries containing phone/CCCD (redacted before expansion)
4. **Adversarial** — injection attempts, > 256 char queries (should be rejected at preprocess)

### Execution

```bash
# Suggested load test with wrk or locust
# Target: 10 concurrent users, 60s duration
locust -f scripts/load_test_retrieval.py --headless \
  -u 10 -r 2 --run-time 60s \
  --csv=benchmark_qe_phase1
```

## 6. Phase-2 Roadmap

| Feature | Priority | Effort | Description |
|---------|----------|--------|-------------|
| Streaming audit parity | ✅ Done | 1 day | Emit `rag.access` with expansion fields in streaming path |
| **Weighted RRF fusion** | P1 | 2 days | Replace concat+sort with reciprocal rank fusion matrix |
| **Per-tenant lexicon** | P1 | 2 days | `tenant_id` filter on lexicon table, tenant-specific synonyms |
| **HyDE (Hypothetical Document Embeddings)** | P2 | 3 days | LLM generates hypothetical answer → embed → search |
| **Click/used tracking** | P2 | 1 day | Add `clicked_chunk_ids` to audit for precision@k offline eval |
| **Offline eval dashboard** | P2 | 2 days | Query audit logs, segment by variant sources, compute hit_rate@k |
| **Multi-language expansion** | P3 | 3 days | English query support for bilingual documents |

## 7. Offline Eval Bootstrap (Available Now)

With PR-09 audit enrichment, proxy evaluation is possible without click tracking:

```sql
-- Compare hit rates before/after expansion
SELECT
  expansion_applied,
  COUNT(*) as total_queries,
  AVG(citations_count) as avg_citations,
  COUNT(*) FILTER (WHERE citations_count = 0) as zero_hit_queries,
  ROUND(100.0 * COUNT(*) FILTER (WHERE citations_count = 0) / COUNT(*), 1) as zero_hit_pct
FROM audit_events
WHERE event_name = 'rag.access'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY expansion_applied;

-- Segment by variant source pattern
SELECT
  variant_sources::text,
  COUNT(*) as queries,
  AVG(citations_count) as avg_citations
FROM audit_events
WHERE event_name = 'rag.access'
  AND expansion_applied = true
GROUP BY variant_sources::text
ORDER BY queries DESC;
```
