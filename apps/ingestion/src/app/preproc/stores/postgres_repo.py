# preproc/stores/postgres_repo.py
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

# IMPORTANT: In production, psycopg_pool SHOULD be mandatory.
from psycopg_pool import ConnectionPool  # type: ignore

from psycopg.types.json import Jsonb  # type: ignore

from app.preproc.normalizers.vi_search_norm import vi_norm

logger = logging.getLogger(__name__)


# ----------------------------
# Migration helpers (NOT auto-run in workers)
# ----------------------------

DEFAULT_INIT_SQL = r"""
-- Recommended to run ONCE during deploy:
-- psql "$DATABASE_URL" -f migrations/001_init.sql

-- Extensions (optional but recommended)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

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
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id
  ON chunks(doc_id);

CREATE INDEX IF NOT EXISTS idx_chunks_filter
  ON chunks(scope, commune_id, doc_category, chunk_kind);

CREATE INDEX IF NOT EXISTS idx_chunks_parent
  ON chunks(parent_chunk_id);

CREATE INDEX IF NOT EXISTS idx_chunks_citation_gin
  ON chunks USING GIN (citation);


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

  UNIQUE (doc_id, sheet_name, row_index)
);

CREATE INDEX IF NOT EXISTS idx_structured_rows_doc_id
  ON structured_rows(doc_id);

CREATE INDEX IF NOT EXISTS idx_structured_rows_filter
  ON structured_rows(commune_id, doc_category);

-- JSON containment index (good for @> / jsonpath existence)
CREATE INDEX IF NOT EXISTS idx_structured_rows_data_gin
  ON structured_rows USING GIN (data_content jsonb_path_ops);

-- FTS index (simple config)
CREATE INDEX IF NOT EXISTS idx_structured_rows_search_fts
  ON structured_rows USING GIN (to_tsvector('simple', coalesce(search_text, '')));

-- TRIGRAM index for fast ILIKE entity search on search_text
CREATE INDEX IF NOT EXISTS idx_rows_search_text_trgm
  ON structured_rows USING GIN (search_text gin_trgm_ops);

CREATE TABLE IF NOT EXISTS ingestion_profiles (
  profile_id UUID PRIMARY KEY,
  tenant_id  TEXT NOT NULL,
  name       TEXT NOT NULL,
  description TEXT NULL,
  config     JSONB NOT NULL DEFAULT '{}',
  
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
  job_id           UUID PRIMARY KEY,
  job_type         TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'queued',
  progress         INTEGER NOT NULL DEFAULT 0,
  error            TEXT NULL,
  
  scope            TEXT NOT NULL,
  commune_id       TEXT NULL,
  
  source_uri       TEXT NOT NULL,
  mime_type        TEXT NOT NULL,
  checksum         TEXT NOT NULL,
  title            TEXT NOT NULL,
  pipeline_version TEXT NOT NULL DEFAULT 'v1',
  doc_category_hint TEXT NULL,
  
  doc_id           UUID NULL,
  
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at       TIMESTAMPTZ NULL,
  finished_at      TIMESTAMPTZ NULL,
  
  -- Cockpit Phase 2
  profile_id       UUID NULL REFERENCES ingestion_profiles(profile_id),
  approved_by      TEXT NULL,  -- user_id (email)
  approver_role    TEXT NULL,  -- e.g. 'admin'
  meta             JSONB NULL  -- Snapshot of context/constraints
);

CREATE TABLE IF NOT EXISTS registered_sources (
  id               UUID PRIMARY KEY,
  tenant_id        TEXT NOT NULL,
  server_id        TEXT NOT NULL,
  path             TEXT NOT NULL,
  profile_id       UUID NOT NULL REFERENCES ingestion_profiles(profile_id),
  enabled          BOOLEAN NOT NULL DEFAULT true,
  last_seen_at     TIMESTAMPTZ NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  UNIQUE (tenant_id, server_id, path)
);

CREATE TABLE IF NOT EXISTS audit_logs (
  log_id           UUID PRIMARY KEY,
  tenant_id        TEXT NOT NULL,
  user_id          TEXT NOT NULL, -- email or role if no auth
  action           TEXT NOT NULL, -- e.g. 'retry_job', 'approve_job'
  resource_id      TEXT NOT NULL, -- job_id or source_id
  details          JSONB NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at DESC);
"""


# ----------------------------
# Serialization helpers
# ----------------------------

def _is_enum(v: Any) -> bool:
    return hasattr(v, "value") and hasattr(v, "name") and not isinstance(v, (str, bytes))


def _sanitize_json(v: Any) -> Any:
    """
    JSON-safe recursively:
    - UUID -> str
    - Enum -> value
    - date/datetime -> isoformat
    - set -> sorted list
    """
    if v is None:
        return None
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if _is_enum(v):
        return getattr(v, "value")
    if isinstance(v, dict):
        return {str(k): _sanitize_json(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_json(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return [_sanitize_json(x) for x in sorted(list(v), key=lambda z: str(z))]
    return v


def _dump_model(obj: Any) -> Dict[str, Any]:
    """
    Supports:
    - Pydantic v2: model_dump()
    - Pydantic v1: dict()
    - dict passthrough
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    raise TypeError(f"Unsupported model type: {type(obj)}")


def _jsonb(v: Any) -> Jsonb:
    return Jsonb(_sanitize_json(v))


def _text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if _is_enum(v):
        return str(v.value)
    return str(v)


# ----------------------------
# Repo config / class
# ----------------------------

@dataclass(frozen=True)
class PostgresRepoConfig:
    conninfo: str
    use_pool: bool = True
    pool_min_size: int = 1
    pool_max_size: int = 10
    pool_timeout: int = 30
    statement_timeout_ms: Optional[int] = 120_000  # 2 minutes


class PostgresRepo:
    """
    Postgres repository (idempotent upsert).
    IMPORTANT:
      - Do NOT auto-run migrations in workers.
      - Run migrations once in deployment step via apply_migration_file() or a proper migration tool.
    """

    def __init__(self, cfg: PostgresRepoConfig) -> None:
        self.cfg = cfg
        if cfg.use_pool:
            # In production, pooling should be mandatory
            self._pool = ConnectionPool(
                conninfo=cfg.conninfo,
                min_size=cfg.pool_min_size,
                max_size=cfg.pool_max_size,
                timeout=cfg.pool_timeout,
            )
        else:
            self._pool = None

    @contextmanager
    def _conn(self):
        if self._pool is not None:
            with self._pool.connection() as conn:
                self._apply_session_settings(conn)
                yield conn
        else:
            with psycopg.connect(self.cfg.conninfo) as conn:
                self._apply_session_settings(conn)
                yield conn

    def _apply_session_settings(self, conn: psycopg.Connection) -> None:
        if self.cfg.statement_timeout_ms is None:
            return
        try:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = %s", (int(self.cfg.statement_timeout_ms),))
        except Exception:
            conn.rollback()
            logger.debug("Could not set statement_timeout; continuing.")

    # ----------------------------
    # Migration APIs (run ONCE in deploy)
    # ----------------------------

    def apply_sql(self, sql_text: str) -> None:
        """
        Apply raw SQL in a single transaction. Use this from a deploy script / init job.
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_text)
            conn.commit()

    def apply_migration_file(self, path: Union[str, Path]) -> None:
        """
        Apply SQL from file (recommended: migrations/001_init.sql).
        """
        p = Path(path)
        sql_text = p.read_text(encoding="utf-8")
        self.apply_sql(sql_text)

    def apply_default_init_sql(self) -> None:
        """
        Convenience for local dev only.
        In production, prefer apply_migration_file('migrations/001_init.sql').
        """
        self.apply_sql(DEFAULT_INIT_SQL)

    # ----------------------------
    # Upserts (idempotent)
    # ----------------------------

    def upsert_document(self, doc: Any) -> None:
        d = _dump_model(doc)
        tenant_id = _text(d.get("tenant_id"))
        if tenant_id is None or not str(tenant_id).strip():
            raise ValueError("tenant_id is required for document upsert")
        payload = {
            "doc_id": str(d["doc_id"]),
            "tenant_id": tenant_id,
            "scope": _text(d.get("scope")),
            "commune_id": d.get("commune_id"),
            "doc_category": _text(d.get("doc_category")),
            "title": d.get("title") or "",
            "source_uri": d.get("source_uri") or "",
            "mime_type": d.get("mime_type") or "",
            "checksum": d.get("checksum") or "",
            "pipeline_version": d.get("pipeline_version") or "v1",
        }

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (
                      doc_id, tenant_id, scope, commune_id, doc_category, title,
                      source_uri, mime_type, checksum, pipeline_version,
                      is_deleted, deleted_at, updated_at
                    ) VALUES (
                      %(doc_id)s, %(tenant_id)s, %(scope)s, %(commune_id)s, %(doc_category)s, %(title)s,
                      %(source_uri)s, %(mime_type)s, %(checksum)s, %(pipeline_version)s,
                      FALSE, NULL, now()
                    )
                    ON CONFLICT (doc_id) DO UPDATE SET
                      tenant_id = EXCLUDED.tenant_id,
                      scope = EXCLUDED.scope,
                      commune_id = EXCLUDED.commune_id,
                      doc_category = EXCLUDED.doc_category,
                      title = EXCLUDED.title,
                      source_uri = EXCLUDED.source_uri,
                      mime_type = EXCLUDED.mime_type,
                      checksum = EXCLUDED.checksum,
                      pipeline_version = EXCLUDED.pipeline_version,
                      is_deleted = FALSE,
                      deleted_at = NULL,
                      updated_at = now()
                    """,
                    payload,
                )
            conn.commit()

    def upsert_chunks(self, chunks: Sequence[Any], batch_size: int = 500) -> None:
        if not chunks:
            return

        rows: List[Dict[str, Any]] = []
        for c in chunks:
            cd = _dump_model(c)

            cit = _dump_model(cd.get("citation"))
            loc = _dump_model(cit.get("locator"))

            rows.append(
                {
                    "chunk_id": str(cd["chunk_id"]),
                    "doc_id": str(cd["doc_id"]),
                    "parent_chunk_id": str(cd["parent_chunk_id"]) if cd.get("parent_chunk_id") else None,
                    "scope": _text(cd.get("scope")),
                    "commune_id": cd.get("commune_id"),
                    "doc_category": _text(cd.get("doc_category")),
                    "chunk_kind": _text(cd.get("chunk_kind")),
                    "order_index": int(cd.get("order_index") or 0),

                    "display_text": cd.get("display_text") or "",
                    "embed_text": cd.get("embed_text"),

                    # Store full citation JSONB (safe)
                    "citation": _jsonb(_sanitize_json(cit)),

                    # Flatten locator fields for convenience
                    "source_uri": loc.get("source_uri") or cd.get("source_uri") or "",
                    "mime_type": loc.get("mime_type") or cd.get("mime_type") or "",
                    "checksum": loc.get("checksum") or cd.get("checksum") or "",
                    "page_start": loc.get("page_start"),
                    "page_end": loc.get("page_end"),
                    "sheet_name": loc.get("sheet_name"),
                    "row_start": loc.get("row_start"),
                    "row_end": loc.get("row_end"),
                    "anchor": loc.get("anchor"),

                    "law_ref": cd.get("law_ref"),
                    "section_path": cd.get("section_path"),
                }
            )

        stmt = """
        INSERT INTO chunks (
          chunk_id, doc_id, parent_chunk_id,
          scope, commune_id, doc_category, chunk_kind, order_index,
          display_text, embed_text,
          citation,
          source_uri, mime_type, checksum,
          page_start, page_end, sheet_name, row_start, row_end, anchor,
          law_ref, section_path,
          updated_at
        ) VALUES (
          %(chunk_id)s, %(doc_id)s, %(parent_chunk_id)s,
          %(scope)s, %(commune_id)s, %(doc_category)s, %(chunk_kind)s, %(order_index)s,
          %(display_text)s, %(embed_text)s,
          %(citation)s,
          %(source_uri)s, %(mime_type)s, %(checksum)s,
          %(page_start)s, %(page_end)s, %(sheet_name)s, %(row_start)s, %(row_end)s, %(anchor)s,
          %(law_ref)s, %(section_path)s,
          now()
        )
        ON CONFLICT (chunk_id) DO UPDATE SET
          doc_id = EXCLUDED.doc_id,
          parent_chunk_id = EXCLUDED.parent_chunk_id,
          scope = EXCLUDED.scope,
          commune_id = EXCLUDED.commune_id,
          doc_category = EXCLUDED.doc_category,
          chunk_kind = EXCLUDED.chunk_kind,
          order_index = EXCLUDED.order_index,
          display_text = EXCLUDED.display_text,
          embed_text = EXCLUDED.embed_text,
          citation = EXCLUDED.citation,
          source_uri = EXCLUDED.source_uri,
          mime_type = EXCLUDED.mime_type,
          checksum = EXCLUDED.checksum,
          page_start = EXCLUDED.page_start,
          page_end = EXCLUDED.page_end,
          sheet_name = EXCLUDED.sheet_name,
          row_start = EXCLUDED.row_start,
          row_end = EXCLUDED.row_end,
          anchor = EXCLUDED.anchor,
          law_ref = EXCLUDED.law_ref,
          section_path = EXCLUDED.section_path,
          updated_at = now()
        """

        with self._conn() as conn:
            with conn.cursor() as cur:
                for i in range(0, len(rows), batch_size):
                    cur.executemany(stmt, rows[i : i + batch_size])
            conn.commit()

    def upsert_rows(self, structured_rows: Sequence[Any], batch_size: int = 1000) -> None:
        if not structured_rows:
            return

        rows: List[Dict[str, Any]] = []
        for r in structured_rows:
            rd = _dump_model(r)
            cit = _dump_model(rd.get("citation"))
            loc = _dump_model(cit.get("locator"))

            sheet_name = loc.get("sheet_name") or rd.get("sheet_name")

            rows.append(
                {
                    "row_id": str(rd["row_id"]),
                    "doc_id": str(rd["doc_id"]),
                    "commune_id": rd.get("commune_id"),
                    "doc_category": _text(rd.get("doc_category")),
                    "sheet_name": sheet_name,
                    "row_index": int(rd.get("row_index") or 0),
                    "data_content": _jsonb(rd.get("data_content") or {}),
                    "data_content": _jsonb(rd.get("data_content") or {}),
                    "search_text": rd.get("search_text") or "",
                    "search_text_norm": rd.get("search_text_norm") or "",
                    "citation": _jsonb(_sanitize_json(cit)),
                }
            )

        stmt = """
        INSERT INTO structured_rows (
          row_id, doc_id,
          commune_id, doc_category,
          sheet_name, row_index,
          data_content, search_text, search_text_norm, citation,
          updated_at
        ) VALUES (
          %(row_id)s, %(doc_id)s,
          %(commune_id)s, %(doc_category)s,
          %(sheet_name)s, %(row_index)s,
          %(data_content)s, %(search_text)s, %(search_text_norm)s, %(citation)s,
          now()
        )
        ON CONFLICT (row_id) DO UPDATE SET
          doc_id = EXCLUDED.doc_id,
          commune_id = EXCLUDED.commune_id,
          doc_category = EXCLUDED.doc_category,
          sheet_name = EXCLUDED.sheet_name,
          row_index = EXCLUDED.row_index,
          data_content = EXCLUDED.data_content,
          search_text = EXCLUDED.search_text,
          search_text_norm = EXCLUDED.search_text_norm,
          citation = EXCLUDED.citation,
          updated_at = now()
        """

        with self._conn() as conn:
            with conn.cursor() as cur:
                for i in range(0, len(rows), batch_size):
                    cur.executemany(stmt, rows[i : i + batch_size])
            conn.commit()

    # ----------------------------
    # Job Management (Ingestion Queue)
    # ----------------------------

    def create_job(
        self,
        *,
        job_id: UUID,
        job_type: str,
        scope: str,
        commune_id: Optional[str],
        source_uri: str,
        mime_type: str,
        checksum: str,
        title: str,
        pipeline_version: str = "v1",
        doc_category_hint: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        sql = """
        INSERT INTO ingestion_jobs (
          job_id, job_type, status, progress,
          scope, commune_id,
          source_uri, mime_type, checksum, title, pipeline_version, doc_category_hint,
          meta
        )
        VALUES (%s,%s,'queued',0,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        meta_json = _jsonb(meta or {})
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    str(job_id), job_type,
                    scope, commune_id,
                    source_uri, mime_type, checksum, title, pipeline_version, doc_category_hint,
                    meta_json
                ))
            conn.commit()

    def get_job(self, job_id: UUID) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM ingestion_jobs WHERE job_id = %s"
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, (str(job_id),))
                row = cur.fetchone()
                return dict(row) if row else None

    def update_job(
        self,
        job_id: UUID,
        *,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        error: Optional[str] = None,
        doc_id: Optional[UUID] = None,
        started: bool = False,
        finished: bool = False,
    ) -> None:
        parts = ["updated_at = now()"]
        params: List[Any] = []

        if status is not None:
            parts.append("status = %s")
            params.append(status)
        if progress is not None:
            parts.append("progress = %s")
            params.append(int(progress))
        if error is not None:
            parts.append("error = %s")
            params.append(error)
        if doc_id is not None:
            parts.append("doc_id = %s")
            params.append(str(doc_id))
        if started:
            parts.append("started_at = COALESCE(started_at, now())")
        if finished:
            parts.append("finished_at = now()")

        sql = f"UPDATE ingestion_jobs SET {', '.join(parts)} WHERE job_id = %s"
        params.append(str(job_id))

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()

    def fail_stale_running_jobs(self, *, stale_minutes: int = 30, reason: str = "Worker crashed/restarted") -> int:
        """
        Zombie-job cleanup: mark running jobs as failed if they haven't updated recently.
        """
        sql = """
        UPDATE ingestion_jobs
        SET status='failed',
            error=%s,
            progress=100,
            finished_at=now(),
            updated_at=now()
        WHERE status='running'
          AND updated_at < (now() - (%s || ' minutes')::interval)
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (reason, int(stale_minutes)))
                affected = cur.rowcount
            conn.commit()
        return int(affected)

    def update_job_approval(
        self,
        job_id: UUID,
        *,
        status: str,
        approved_by: str,
        approver_role: str,
    ) -> None:
        sql = """
        UPDATE ingestion_jobs
        SET status = %s,
            approved_by = %s,
            approver_role = %s,
            updated_at = now()
        WHERE job_id = %s
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (status, approved_by, approver_role, str(job_id)))
            conn.commit()

    def create_job_with_profile(
        self,
        *,
        job_id: UUID,
        job_type: str,
        source_uri: str,
        mime_type: str,
        checksum: str,
        title: str,
        profile_id: UUID,
        status: str = "queued",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Phase 2: Job creation with Profile link and strict status (e.g. pending_approval)
        """
        # We infer scope/commune from meta snapshot to keep table populating relying on legacy cols if needed,
        # but primarily we rely on meta now.
        # Fallback for legacy columns:
        m = meta or {}
        scope = m.get("scope", "internal")
        commune_id = m.get("geo_code") or m.get("commune_id")
        doc_category_hint = m.get("doc_type") or "other"
        pipeline_version = "v2"

        sql = """
        INSERT INTO ingestion_jobs (
          job_id, job_type, status, progress,
          scope, commune_id,
          source_uri, mime_type, checksum, title, pipeline_version, doc_category_hint,
          meta, profile_id
        )
        VALUES (%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        meta_json = _jsonb(meta or {})
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    str(job_id), job_type, status,
                    scope, commune_id,
                    source_uri, mime_type, checksum, title, pipeline_version, doc_category_hint,
                    meta_json, str(profile_id)
                ))
            conn.commit()

    # ----------------------------
    # Ingestion Profiles (Cockpit)
    # ----------------------------

    def create_profile(
        self,
        *,
        profile_id: UUID,
        tenant_id: str,
        name: str,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        sql = """
        INSERT INTO ingestion_profiles (
          profile_id, tenant_id, name, description, config
        ) VALUES (
          %s, %s, %s, %s, %s
        )
        """
        config_json = _jsonb(config or {})
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    str(profile_id), tenant_id, name, description, config_json
                ))
            conn.commit()

    def get_profile(self, profile_id: UUID) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM ingestion_profiles WHERE profile_id = %s"
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, (str(profile_id),))
                return cur.fetchone()

    def list_profiles(self, tenant_id: str) -> List[Dict[str, Any]]:
        sql = """
        SELECT * FROM ingestion_profiles 
        WHERE tenant_id = %s 
        ORDER BY name ASC
        """
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, (tenant_id,))
                return list(cur.fetchall())

    def delete_profile(self, profile_id: UUID) -> None:
        sql = "DELETE FROM ingestion_profiles WHERE profile_id = %s"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (str(profile_id),))
            conn.commit()

    # ----------------------------
    # Query helpers (optional)
    # ----------------------------

    def search_rows_ilike(
        self,
        pattern: str,
        *,
        doc_id: Optional[Union[str, UUID]] = None,
        commune_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Fast entity search using trigram index:
          WHERE search_text_norm ILIKE '%...%'
        """
        # Normalize the query pattern to match the stored normalized text
        norm_pattern = vi_norm(pattern)
        
        where = ["search_text_norm ILIKE %s"]
        params: List[Any] = [norm_pattern]

        if doc_id is not None:
            where.append("doc_id = %s")
            params.append(str(doc_id))
        if commune_id is not None:
            where.append("commune_id = %s")
            params.append(commune_id)

        q = f"""
        SELECT row_id, doc_id, commune_id, doc_category, sheet_name, row_index, data_content, citation
        FROM structured_rows
        WHERE {" AND ".join(where)}
        ORDER BY updated_at DESC
        LIMIT %s
        """
        params.append(int(limit))

        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(q, tuple(params))
                return list(cur.fetchall())

    def get_chunks_by_ids(self, chunk_ids: Sequence[Union[str, UUID]]) -> List[Dict[str, Any]]:
        if not chunk_ids:
            return []
        ids = [str(x) for x in chunk_ids]
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM chunks WHERE chunk_id = ANY(%s)", (ids,))
                return list(cur.fetchall())

    def get_document(self, doc_id: Union[str, UUID]) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM documents WHERE doc_id = %s", (str(doc_id),))
                return cur.fetchone()

    def get_document_for_tenant(
        self,
        doc_id: Union[str, UUID],
        tenant_id: str,
        include_deleted: bool = False,
    ) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM documents WHERE doc_id = %s AND tenant_id = %s"
        if not include_deleted:
            sql += " AND is_deleted = FALSE"

        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, (str(doc_id), str(tenant_id)))
                return cur.fetchone()

    def soft_delete_document_for_tenant(self, doc_id: Union[str, UUID], tenant_id: str) -> int:
        sql = """
        UPDATE documents
        SET is_deleted = TRUE,
            deleted_at = now(),
            updated_at = now()
        WHERE doc_id = %s
          AND tenant_id = %s
          AND is_deleted = FALSE
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (str(doc_id), str(tenant_id)))
                affected = cur.rowcount
            conn.commit()
        return int(affected or 0)

    def delete_chunks_rows_for_doc(self, doc_id: Union[str, UUID]) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM structured_rows WHERE doc_id = %s", (str(doc_id),))
                cur.execute("DELETE FROM chunks WHERE doc_id = %s", (str(doc_id),))
            conn.commit()

    def delete_document(self, doc_id: Union[str, UUID]) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE doc_id = %s", (str(doc_id),))
            conn.commit()

    # ---------------------------
    # Registered Sources (Phase P1)
    # ---------------------------
    def create_source(self, id: UUID, tenant_id: str, server_id: str, path: str, profile_id: UUID) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO registered_sources (id, tenant_id, server_id, path, profile_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, server_id, path) 
                    DO UPDATE SET profile_id = EXCLUDED.profile_id, enabled = true, updated_at = now()
                    """,
                    (str(id), tenant_id, server_id, path, str(profile_id))
                )
            conn.commit()

    def list_sources(self, tenant_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT s.*, p.name as profile_name 
                    FROM registered_sources s
                    JOIN ingestion_profiles p ON s.profile_id = p.profile_id
                    WHERE s.tenant_id = %s
                    ORDER BY s.server_id, s.path
                    """,
                    (tenant_id,)
                )
                return list(cur.fetchall())
    
    def get_source(self, id: UUID) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
             with conn.cursor(row_factory=dict_row) as cur:
                 cur.execute("SELECT * FROM registered_sources WHERE id = %s", (str(id),))
                 return cur.fetchone()

    def delete_source(self, id: UUID) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM registered_sources WHERE id = %s", (str(id),))
            conn.commit()

    def toggle_source(self, id: UUID, enabled: bool) -> None:
         with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE registered_sources SET enabled = %s, updated_at = now() WHERE id = %s", (enabled, str(id)))
            conn.commit()
            
    def update_source_heartbeat(self, id: UUID) -> None:
         with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE registered_sources SET last_seen_at = now() WHERE id = %s", (str(id),))
            conn.commit()

    def get_server_config(self, server_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT path, profile_id, id 
                    FROM registered_sources 
                    WHERE server_id = %s AND enabled = true
                    """,
                    (server_id,)
                )
                return list(cur.fetchall())

    # ---------------------------
    # Phase P2: Ops Maturity (Recovery & Audit)
    # ---------------------------
    def reset_job(self, job_id: UUID) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ingestion_jobs 
                    SET status = 'queued', error = NULL, progress = 0, started_at = NULL, finished_at = NULL, updated_at = now()
                    WHERE job_id = %s
                    """,
                    (str(job_id),)
                )
            conn.commit()

    def list_jobs(self, tenant_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Basic list, order by created_at desc
                cur.execute(
                    """
                    SELECT j.*, p.name as profile_name
                    FROM ingestion_jobs j
                    LEFT JOIN ingestion_profiles p ON j.profile_id = p.profile_id
                    WHERE (
                        j.profile_id IN (SELECT profile_id FROM ingestion_profiles WHERE tenant_id = %s)
                        OR COALESCE(j.meta->>'tenant_id', '') = %s
                    )
                    ORDER BY j.created_at DESC
                    LIMIT %s
                    """,
                    (tenant_id, tenant_id, limit)
                )
                return list(cur.fetchall())

    def list_documents_for_tenant(
        self,
        tenant_id: str,
        *,
        scope: Optional[str] = None,
        doc_type: Optional[str] = None,
        is_deleted: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'documents'
                    """
                )
                doc_cols = {str(r["column_name"]) for r in cur.fetchall()}

                has_security_level = "security_level" in doc_cols
                has_is_deleted = "is_deleted" in doc_cols

                # Backward compatible selects for old schemas.
                security_expr = "d.security_level" if has_security_level else "NULL::int AS security_level"
                deleted_expr = "d.is_deleted" if has_is_deleted else "FALSE AS is_deleted"

                sql = f"""
                    SELECT
                      d.doc_id,
                      d.tenant_id,
                      d.title,
                      d.scope,
                      d.doc_category AS doc_type,
                      d.doc_category,
                      {security_expr},
                      {deleted_expr},
                      d.created_at,
                      d.updated_at,
                      COALESCE(ch.cnt, 0) AS chunks_count,
                      COALESCE(sr.cnt, 0) AS rows_count
                    FROM documents d
                    LEFT JOIN LATERAL (
                      SELECT count(*)::int AS cnt FROM chunks c WHERE c.doc_id = d.doc_id
                    ) ch ON TRUE
                    LEFT JOIN LATERAL (
                      SELECT count(*)::int AS cnt FROM structured_rows s WHERE s.doc_id = d.doc_id
                    ) sr ON TRUE
                    WHERE d.tenant_id = %s
                """
                params: List[Any] = [str(tenant_id)]

                if scope:
                    sql += " AND d.scope = %s"
                    params.append(str(scope))
                if doc_type:
                    sql += " AND d.doc_category = %s"
                    params.append(str(doc_type))
                if is_deleted is not None:
                    # Old schemas have no soft-delete flag; treat all rows as not deleted.
                    if has_is_deleted:
                        sql += " AND d.is_deleted = %s"
                        params.append(bool(is_deleted))
                    elif bool(is_deleted):
                        return []

                sql += " ORDER BY d.created_at DESC LIMIT %s"
                params.append(int(limit))

                cur.execute(sql, params)
                return list(cur.fetchall())

    def insert_audit(self, tenant_id: str, user_id: str, action: str, resource_id: str, details: Dict[str, Any] | None = None) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_logs (log_id, tenant_id, user_id, action, resource_id, details)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (str(uuid4()), tenant_id, user_id, action, resource_id, _jsonb(details))
                )
            conn.commit()

    def list_audit_logs(self, tenant_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM audit_logs 
                    WHERE tenant_id = %s 
                    ORDER BY created_at DESC 
                    LIMIT %s
                    """,
                    (tenant_id, limit)
                )
                return list(cur.fetchall())
    
    def get_dashboard_metrics(self, tenant_id: str) -> Dict[str, Any]:
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Total Jobs Today
                cur.execute("""
                    SELECT count(*) as count FROM ingestion_jobs 
                    WHERE created_at >= current_date
                """)
                today_count = cur.fetchone()['count']
                
                # Failed Rate (All time or today? Let's say all time active window)
                cur.execute("""
                    SELECT 
                        count(*) FILTER (WHERE status = 'failed') as failed,
                        count(*) as total
                    FROM ingestion_jobs
                """)
                stats = cur.fetchone()
                failed_pct = 0
                if stats['total'] > 0:
                    failed_pct = round((stats['failed'] / stats['total']) * 100, 1)

                # Pending
                cur.execute("SELECT count(*) as count FROM ingestion_jobs WHERE status = 'pending_approval'")
                pending_count = cur.fetchone()['count']

                # Active Watchers (seen < 5 mins ago)
                cur.execute("""
                    SELECT count(*) as count FROM registered_sources 
                    WHERE enabled = true AND last_seen_at >= now() - interval '5 minutes'
                """)
                watcher_count = cur.fetchone()['count']
                
                return {
                    "jobs_today": today_count,
                    "failed_rate": failed_pct,
                    "pending_approvals": pending_count,
                    "active_watchers": watcher_count
                }
