from __future__ import annotations

import sys
import os
import traceback
from uuid import UUID
from typing import List, Optional, Dict, Any

from celery import Celery
from celery.signals import worker_process_init

from app.workers.bootstrap import get_orchestrator, get_pg_repo, get_qdrant_client
from app.preproc.pipeline.interfaces import IngestMeta
from app.core.canonical_models import Scope

from app.preproc.utils.ids import make_doc_id
from app.core.qdrant_setup import ensure_qdrant_schema
from app.core.config import settings


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "ingestion_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


def _tenant_epoch_key(tenant_id: str) -> str:
    tid = str(tenant_id or "").strip()
    if not tid:
        raise ValueError("tenant_id is required for epoch key")
    return f"rag:tenant_epoch:{tid}"


def _bump_tenant_epoch(tenant_id: str) -> Optional[int]:
    """
    Best-effort cache invalidation signal for backend RAG cache.
    Uses Redis INCR on tenant epoch key.
    """
    redis_url = os.getenv("REDIS_URL", REDIS_URL) or ""
    if not redis_url:
        return None

    try:
        import redis

        client = redis.Redis.from_url(
            redis_url,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            decode_responses=True,
        )
        try:
            return int(client.incr(_tenant_epoch_key(tenant_id)))
        finally:
            try:
                client.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[worker_cache] failed to bump tenant epoch tenant={tenant_id}: {e}")
        return None


@worker_process_init.connect
def _on_worker_start(**kwargs):
    """
    Zombie job cleanup (safer): only fail jobs 'running' that haven't updated in N minutes.
    """
    stale_minutes = int(os.getenv("JOB_ZOMBIE_MINUTES", "30"))
    pg = get_pg_repo()
    # Ensure fail_stale_running_jobs is implemented in Repo
    if hasattr(pg, "fail_stale_running_jobs"):
        n = pg.fail_stale_running_jobs(stale_minutes=stale_minutes)
        if n:
            print(f"[worker_init] Marked {n} stale running job(s) as failed (zombie cleanup).")
    else:
        print("[worker_init] PostgresRepo missing fail_stale_running_jobs method.")

    # Schema Enforcement (Self-Healing)
    try:
        orch = get_orchestrator()
        # Orchestrator lazy loads repo, but accessing qdrant_repo property should trigger init if needed,
        # or we might need to access the client safely.
        # QdrantRepo __init__ creates client. 
        client = orch.qdrant_repo.client
        collection = orch.qdrant_repo.cfg.collection_name
        ensure_qdrant_schema(client, collection)
        
        # PR-A1: Parity Check (Fail-Closed)
        EXPECTED_DIM = settings.VECTOR_SIZE
        vectors_cfg = None
        try:
            coll_info = client.get_collection(collection)
            vectors_cfg = coll_info.config.params.vectors
            actual_dim = _extract_vector_size(vectors_cfg)
            if actual_dim != EXPECTED_DIM:
                print(f"[FATAL] Qdrant Vector Dimension Mismatch! Expected: {EXPECTED_DIM}, Actual: {actual_dim}")
                print(f"[FATAL] System assumes {EXPECTED_DIM}. Please reset Qdrant collection.")
                sys.exit(1)
            print(f"[worker_init] Parity Verified: {collection} has dim {actual_dim}.")
        except Exception as e:
            # If we just created it using ensure_qdrant_schema, it should be fine.
            # But if ensure_qdrant_schema used default which was 768 (as per qdrant_setup.py default), we are good.
            # But we double check here to be sure.
            print(f"[worker_init] Parity check warning ({type(vectors_cfg)}): {e}")
            # We don't exit here to avoid loop if qdrant is down, let ensure_qdrant_schema handle that?
            # But ensure_qdrant_schema succeeded.
            pass
            
        print("[worker_init] Qdrant schema enforced.")
    except Exception as e:
         print(f"[worker_init] Failed to enforce Qdrant schema: {e}")
         traceback.print_exc()


@celery_app.task(name="ingestion.run_job")
def run_job(job_id: str) -> dict:
    pg = get_pg_repo()
    job_uuid = UUID(job_id)
    job = pg.get_job(job_uuid)
    if not job:
        return {"ok": False, "job_id": job_id, "error": "job_not_found"}

    try:
        pg.update_job(job_uuid, status="running", progress=5, started=True)

        job_type = job["job_type"]
        orch = get_orchestrator()
        meta_json: Dict[str, Any] = job.get("meta") or {}

        # Priority: Meta JSONB > Legacy Columns > Defaults
        tenant_id = meta_json.get("tenant_id") or job.get("tenant_id")
        if not tenant_id:
             # FAIL-CLOSED: Do not process. Do not use default.
             # Mark job as failed in PG? The worker_wrapper usually handles exceptions and updates status.
             raise RuntimeError("CRITICAL: Missing tenant_id in job metadata. Job rejected (Fail-Closed).")

        # --- DELETE job ---
        if job_type == "delete":
            # doc_id must exist for delete
            if not job.get("doc_id"):
                return {"ok": False, "job_id": job_id, "error": "delete_job_missing_doc_id"}

            doc_id = job["doc_id"]

            if not hasattr(pg, "get_document_for_tenant"):
                raise RuntimeError("PostgresRepo missing get_document_for_tenant(doc_id, tenant_id)")
            owned_doc = pg.get_document_for_tenant(doc_id, tenant_id, include_deleted=True)
            if not owned_doc:
                return {"ok": False, "job_id": job_id, "error": "delete_job_tenant_mismatch"}

            pg.update_job(job_uuid, progress=30)

            if hasattr(pg, "soft_delete_document_for_tenant"):
                affected = int(pg.soft_delete_document_for_tenant(doc_id, tenant_id) or 0)
                if affected == 0:
                    current_doc = owned_doc
                    if not bool(current_doc.get("is_deleted")):
                        current_doc = pg.get_document_for_tenant(doc_id, tenant_id, include_deleted=True)
                    if not current_doc or not bool(current_doc.get("is_deleted")):
                        return {"ok": False, "job_id": job_id, "error": "delete_job_tenant_mismatch"}
            else:
                raise RuntimeError("PostgresRepo missing soft_delete_document_for_tenant(doc_id, tenant_id)")

            if hasattr(pg, "delete_chunks_rows_for_doc"):
                pg.delete_chunks_rows_for_doc(doc_id)
            else:
                raise RuntimeError("PostgresRepo missing delete_chunks_rows_for_doc(doc_id)")

            pg.update_job(job_uuid, progress=60)
            
            # Qdrant delete points by doc_id+tenant_id filter
            if hasattr(orch.qdrant_repo, "delete_by_doc_id_and_tenant"):
                orch.qdrant_repo.delete_by_doc_id_and_tenant(doc_id, tenant_id)
            else:
                raise RuntimeError("QdrantRepo missing delete_by_doc_id_and_tenant(doc_id, tenant_id)")

            pg.update_job(job_uuid, status="done", progress=100, finished=True)
            _bump_tenant_epoch(str(tenant_id))
            return {"ok": True, "job_id": job_id, "doc_id": str(doc_id), "job_type": "delete"}

        if job_type == "reindex":
            if not job.get("doc_id"):
                return {"ok": False, "job_id": job_id, "error": "reindex_job_missing_doc_id"}

            if not hasattr(pg, "get_document_for_tenant"):
                raise RuntimeError("PostgresRepo missing get_document_for_tenant(doc_id, tenant_id)")
            owned_doc = pg.get_document_for_tenant(job["doc_id"], tenant_id)
            if not owned_doc:
                return {"ok": False, "job_id": job_id, "error": "reindex_job_tenant_mismatch"}
        
        doc_type = meta_json.get("doc_type") or job.get("doc_type") or job.get("doc_category_hint") or "other"
        
        # Safe Scope extraction (Fail-Closed)
        scope_enum = _parse_scope(meta_json, job)

        security_level = meta_json.get("security_level") 
        if security_level is None:
             security_level = int(job.get("security_level") or 1)
        else:
             security_level = int(security_level)

        meta = IngestMeta(
            tenant_id=tenant_id,
            doc_type=doc_type,
            scope=scope_enum,
            security_level=security_level,
            
            department_id=meta_json.get("department_id") or job.get("department_id"),
            geo_code=meta_json.get("geo_code") or job.get("geo_code") or job.get("commune_id"),
            domain=meta_json.get("domain") or job.get("domain"),
            
            commune_id=job.get("commune_id"),
            
            mime_type=job["mime_type"],
            source_uri=job["source_uri"],
            checksum=job["checksum"],
            title=job["title"],
            pipeline_version=job.get("pipeline_version") or "v1",
            doc_category_hint=None,
            
            # Metadata Propagation for RRF
            metadata={"_score_kind": "cosine"}, # Default kind for dense ingestion
        )

        # Metadata Validation (P1 Security)
        _validate_meta_by_scope(meta)

        pg.update_job(job_uuid, progress=15)
        
        # Runtime Parity Check (P1 Fix)
        # Prevents junk vectors if model/dim changed while worker running.
        collection = settings.QDRANT_COLLECTION # Ensure this exists in settings or config
        _ensure_qdrant_parity(get_qdrant_client(), collection)

        result = orch.process(job["source_uri"], meta)
        _assert_ingest_result_fail_closed(result)

        # doc_id: prefer orchestrator result; fallback deterministic compute
        doc_id = result.get("doc_id")
        if not doc_id:
            try:
                doc_id = make_doc_id(
                    tenant_id=meta.tenant_id,
                    scope=meta.scope,
                    doc_type=meta.doc_type,
                    checksum=meta.checksum,
                    source_uri=meta.source_uri,
                )
            except Exception:
                doc_id = None

        pg.update_job(job_uuid, status="done", progress=100, doc_id=doc_id, finished=True)
        _bump_tenant_epoch(str(tenant_id))

        return {"ok": True, "job_id": job_id, "doc_id": str(doc_id) if doc_id else None, "result": result}

    except Exception as e:
        err = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        pg.update_job(job_uuid, status="failed", progress=100, error=err, finished=True)
        return {"ok": False, "job_id": job_id, "error": str(e)}


def _parse_scope(meta_json: Dict[str, Any], job: Dict[str, Any]) -> Scope:
    """
    Parse scope with FAIL-CLOSED logic.
    Ref: Security Audit P0-ING-01.
    """
    # 1. Try meta_json (Priority)
    if "scope" in meta_json:
        val = meta_json["scope"]
        try:
            return Scope(val)
        except ValueError:
             raise RuntimeError(f"CRITICAL: Invalid scope in meta '{val}'. Job rejected (Fail-Closed).")

    # 2. Try job["scope"] (Legacy)
    if "scope" in job:
        val = job["scope"]
        try:
            return Scope(val)
        except ValueError:
            # Legacy aliases
            if val == "local_gov":
                return Scope.INTERNAL
            elif val == "global_law":
                return Scope.PUBLIC
            
            # BLOCK EVERYTHING ELSE
            raise RuntimeError(f"CRITICAL: Invalid legacy scope '{val}'. Job rejected (Fail-Closed).")

    # 3. Missing scope
    raise RuntimeError("CRITICAL: Missing scope in job/meta. Job rejected (Fail-Closed).")


# -------------------------------------------------------------------------
# Runtime Parity Guard (Single Point of Truth)
# -------------------------------------------------------------------------

_LAST_PARITY_CHECK = 0.0
_PARITY_CHECK_INTERVAL = 60.0  # seconds

def _extract_vector_size(vectors_cfg: Any) -> int:
    """
    Extract vector dimension from Qdrant vectors config across client versions/shapes:
      1) VectorParams-like object with .size
      2) plain dict with {"size": ...}
      3) named vectors dict, e.g. {"default": VectorParams(...)} or {"default": {"size": ...}}
    """
    # Case 1: VectorParams-like object
    obj_size = getattr(vectors_cfg, "size", None)
    if obj_size is not None:
        try:
            return int(obj_size)
        except (TypeError, ValueError):
            pass

    # Case 2 / 3: dict-like shapes
    if isinstance(vectors_cfg, dict):
        direct_size = vectors_cfg.get("size")
        if direct_size is not None:
            try:
                return int(direct_size)
            except (TypeError, ValueError):
                pass

        # Named vectors: use first entry that exposes a valid size.
        for cfg in vectors_cfg.values():
            named_obj_size = getattr(cfg, "size", None)
            if named_obj_size is not None:
                try:
                    return int(named_obj_size)
                except (TypeError, ValueError):
                    pass

            if isinstance(cfg, dict):
                nested_size = cfg.get("size")
                if nested_size is not None:
                    try:
                        return int(nested_size)
                    except (TypeError, ValueError):
                        pass

    raise RuntimeError(f"Unsupported Qdrant vectors config shape: {type(vectors_cfg)}")

def _ensure_qdrant_parity(client: Any, collection_name: str) -> None:
    """
    Check Qdrant params at runtime (per job, throttled).
    Faill-fast if:
      1. Vector dimension mismatch (CRITICAL)
      2. Embedding model ID mismatch (CRITICAL)
    """
    global _LAST_PARITY_CHECK
    import time
    
    now = time.time()
    if now - _LAST_PARITY_CHECK < _PARITY_CHECK_INTERVAL:
        return

    # 1. Dimension Check
    expected_dim = settings.VECTOR_SIZE
    try:
        coll_info = client.get_collection(collection_name)
        vectors_cfg = coll_info.config.params.vectors
        actual_dim = _extract_vector_size(vectors_cfg)
        
        if actual_dim != expected_dim:
             raise RuntimeError(f"CRITICAL: Vector Dimension Mismatch! Expected {expected_dim}, got {actual_dim}. Job rejected.")
        
        # 2. Model ID Check (Sample 1 point)
        # Only if collection is strictly not empty
        if coll_info.points_count > 0:
             # Fast scroll to get 1 point payload
             res = client.scroll(
                 collection_name=collection_name, 
                 limit=1, 
                 with_payload=True, 
                 with_vectors=False
             )
             points = res[0] # Tuple (points, offset)
             if points:
                 payload = points[0].payload or {}
                 # If legacy data key missing, we might warn or ignore. 
                 # Here we enforce strict check IF the key exists.
                 actual_model = payload.get("embedding_model_id")
                 expected_model = getattr(settings, "EMBEDDING_MODEL_ID", "unknown")
                 
                 if actual_model and actual_model != expected_model:
                      raise RuntimeError(f"CRITICAL: Embedding Model Mismatch! Expected '{expected_model}', got '{actual_model}'. Job rejected.")

    except Exception as e:
        # Rethrow RuntimeErrors (our checks), wrap others
        if isinstance(e, RuntimeError):
            raise
        # Safe choice: fail-closed if we can't verify parity.
        raise RuntimeError(f"Parity check failed (Qdrant error): {e}") from e

    # Update cache ts
    _LAST_PARITY_CHECK = now


def _assert_ingest_result_fail_closed(result: Dict[str, Any]) -> None:
    """
    Fail-closed invariant:
      - A successful ingest must produce at least one retrieval unit (chunk or row).
      - If chunks are produced, embedded chunks must be > 0.
    """
    chunks = int(result.get("chunks") or 0)
    rows = int(result.get("rows") or 0)
    embedded_chunks = int(result.get("embedded_chunks") or 0)

    if chunks <= 0 and rows <= 0:
        raise RuntimeError(
            "empty_extracted_text: ingest produced zero chunks and zero rows; job rejected (Fail-Closed)."
        )

    if chunks > 0 and embedded_chunks <= 0:
        raise RuntimeError(
            "vector_index_missing: chunks produced but embedded_chunks is zero; job rejected (Fail-Closed)."
        )

def _validate_meta_by_scope(meta: IngestMeta) -> None:
    """
    Validate metadata completeness based on scope (P1 Security).
    Fail-closed: reject jobs with incomplete metadata to prevent unretrievable docs.
    
    Raises:
        RuntimeError: If metadata is invalid for the given scope
    """
    scope = meta.scope
    
    # PUBLIC: no restrictions
    if scope == Scope.PUBLIC:
        return
    
    # INTERNAL: require department_id
    if scope == Scope.INTERNAL:
        dept = meta.department_id
        if not dept or not str(dept).strip():
            raise RuntimeError(
                "CRITICAL: INTERNAL scope requires non-empty department_id. "
                f"Got: {dept!r}. Job rejected."
            )
        return
    
    # RESTRICTED: require security_level >= 3 AND scoping field
    if scope == Scope.RESTRICTED:
        sec_level = meta.security_level
        if sec_level is None or sec_level < 3:
            raise RuntimeError(
                f"CRITICAL: RESTRICTED scope requires security_level >= 3. "
                f"Got: {sec_level}. Job rejected."
            )
        
        # Require at least one scoping field
        dept = meta.department_id
        geo = meta.geo_code
        has_dept = dept and str(dept).strip()
        has_geo = geo and str(geo).strip()
        
        if not (has_dept or has_geo):
            raise RuntimeError(
                "CRITICAL: RESTRICTED scope requires department_id OR geo_code. "
                f"Got dept={dept!r}, geo={geo!r}. Job rejected."
            )
