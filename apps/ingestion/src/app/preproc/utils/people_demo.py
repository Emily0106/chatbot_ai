from __future__ import annotations

import re
import os
import logging
import json
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from core_shared.canonical_models import (
    Citation,
    EmbeddedPoint,
    PersonPointPayload,
    SourceRef,
)

# ... (rest of file) ...

def upsert_person_rows_to_postgres(payloads: List[PersonPointPayload]):
    db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        print("Warning: No DB_URL found, skipping Postgres upsert.")
        return

    # Force sync driver for this script
    if "+asyncpg" in db_url:
        db_url = db_url.replace("+asyncpg", "")
    
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            # 1. Insert parent document (once)
            if payloads:
                first_p = payloads[0]
                doc_id_str = str(first_p.doc_id)
                source_uri = first_p.citation.source.source_uri if first_p.citation else "unknown"
                
                doc_stmt = text("""
                    INSERT INTO documents (doc_id, scope, doc_category, title, source_uri, mime_type, checksum)
                    VALUES (:doc_id, :scope, :doc_category, :title, :source_uri, :mime_type, :checksum)
                    ON CONFLICT (doc_id) DO NOTHING;
                """)
                conn.execute(doc_stmt, parameters={
                    "doc_id": doc_id_str,
                    "scope": "public",
                    "doc_category": "people",
                    "title": "People Demo Data",
                    "source_uri": source_uri,
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "checksum": "demo_checksum"
                })

            # 2. Insert rows
            for p in payloads:
                # Merge search_text_ascii into data_content for SQL search
                data_for_db = p.data_content.copy()
                if p.search_text_ascii:
                    data_for_db["search_text_ascii"] = p.search_text_ascii
                
                sql_str = """
                    INSERT INTO structured_rows (row_id, doc_id, doc_category, row_index, data_content, citation, commune_id, search_text)
                    VALUES (:row_id, :doc_id, :doc_category, :row_index, :data_content, :citation, :commune_id, :search_text)
                    ON CONFLICT (row_id) DO UPDATE SET
                        doc_id = EXCLUDED.doc_id,
                        row_index = EXCLUDED.row_index,
                        data_content = EXCLUDED.data_content,
                        citation = EXCLUDED.citation,
                        commune_id = EXCLUDED.commune_id,
                        search_text = EXCLUDED.search_text;
                """
                stmt = text(sql_str)
                
                # Handle citation serialization safely
                cit_json = p.citation.model_dump_json() if p.citation else "{}"
                row_idx = p.citation.source.row_index if p.citation and p.citation.source.row_index is not None else 0
                
                conn.execute(stmt, parameters={
                    "row_id": str(p.row_id),
                    "doc_id": str(p.doc_id),
                    "doc_category": "people",
                    "row_index": row_idx,
                    "data_content": json.dumps(data_for_db, ensure_ascii=False),
                    "citation": cit_json,
                    "commune_id": None,
                    "search_text": ""
                })
            conn.commit()
        print(f"Upserted {len(payloads)} rows to Postgres structured_rows.")
    except Exception as e:
        print(f"Error upserting to Postgres: {e}")
        import traceback
        traceback.print_exc()

def import_json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)

# -----------------------------
# (A) Normalize helpers (demo)
# -----------------------------
_VN_SPACES = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)

def normalize_name_vi(s: str) -> str:
    """
    Demo normalize: lowercase + strip punctuation + collapse spaces.
    (Bạn có thể thay bằng normalize tiếng Việt chuẩn trong core_shared.text_utils sau.)
    """
    s = (s or "").strip().lower()
    s = _NON_WORD.sub(" ", s)
    s = _VN_SPACES.sub(" ", s).strip()
    return s


# --------------------------------
# (B) Chunking -> embed text
# --------------------------------
def row_to_embed_text(row: Dict[str, Any]) -> str:
    """
    1 row (Excel/CSV) => 1 'chunk' embed_text.
    """
    def g(k: str) -> str:
        v = row.get(k)
        return "" if v is None else str(v).strip()

    parts = [
        f"Họ tên: {g('full_name')}",
        f"Mã: {g('code')}",
        f"CCCD: {g('cccd')}",
        f"Ngày sinh: {g('dob')}",
        f"Giới tính: {g('gender')}",
        f"Điện thoại: {g('phone')}",
        f"Email: {g('email')}",
        f"Địa chỉ: {g('address')}",
        f"Đơn vị: {g('ward_commune')}",
        f"Chức danh: {g('occupation')}",
        f"Ghi chú: {g('note')}",
    ]
    # giữ ngắn gọn, loại phần rỗng
    parts = [p for p in parts if not p.endswith(": ")]
    return "; ".join(parts)


# --------------------------------
# (C) Local embedding (SentenceTransformers)
# --------------------------------
def _local_embed(texts: List[str], model_name: str = "all-MiniLM-L6-v2") -> List[List[float]]:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)
    embeddings = model.encode(texts)
    return embeddings.tolist()

def _vector_size_for_model(model: str) -> int:
    if "MiniLM" in model:
        return 384
    if "text-embedding-3-small" in model:
        return 1536
    if "text-embedding-3-large" in model:
        return 3072
    if "vietnamese" in model or "sbert" in model:
        return 768
    return 384  # default fallback


# --------------------------------
# (D) Upsert people rows to Qdrant
# --------------------------------
# --------------------------------
# (D) Upsert people rows to Qdrant
# --------------------------------

def _openai_embed(texts: List[str], api_key: str, model: str) -> List[List[float]]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    resp = client.embeddings.create(input=texts, model=model)
    return [d.embedding for d in resp.data]

# --------------------------------
# (D) Upsert people rows to Qdrant
# --------------------------------
def upsert_person_rows_to_qdrant(
    rows: Iterable[Dict[str, Any]],
    *,
    qdrant_url: str,
    collection_name: str,
    openai_api_key: str,
    openai_embed_model: str = "text-embedding-3-small",
    doc_id: Optional[UUID] = None,
    source_uri: str = "storage/raw_files/people_demo.xlsx",
    sheet_name: Optional[str] = None,
    start_row_index: int = 2,
    recreate_collection: bool = False,
    batch_size: int = 64,
) -> Dict[str, Any]:
    """
    - rows: list/dict từ extractor table (csv/xlsx)
    - 1 row => 1 point
    - payload chuẩn: core_shared.contracts.RecordPayload
    """
    from app.preproc.utils.record_index import build_person_record_payload
    from app.preproc.utils.record_upsert import to_record_points
    from app.preproc.stores.qdrant_repo import QdrantRepo, QdrantRepoConfig

    doc_id = doc_id or uuid4()
    
    # Use QdrantRepo for consistent collection setup
    repo_cfg = QdrantRepoConfig(
        url=qdrant_url,
        collection_name=collection_name,
        vector_size=_vector_size_for_model(openai_embed_model),
        recreate_if_exists=recreate_collection,
    )
    repo = QdrantRepo(repo_cfg)

    rows_list = list(rows)
    embed_texts = [row_to_embed_text(r) for r in rows_list]

    embeddings: List[List[float]] = []
    for i in range(0, len(embed_texts), batch_size):
        chunk = embed_texts[i : i + batch_size]
        if "text-embedding" in openai_embed_model:
            embeddings.extend(_openai_embed(chunk, openai_api_key, openai_embed_model))
        else:
            # Local model (path or name)
            embeddings.extend(_local_embed(chunk, openai_embed_model))




    # Build payloads using new logic
    payloads = []
    for idx, row in enumerate(rows_list):
        full_name = str(row.get("full_name", "")).strip()
        if not full_name:
            continue
            
        p = build_person_record_payload(
            row,
            doc_id=doc_id,  # Use the single doc_id generated at start of function
            source_uri=source_uri,
            sheet_name=sheet_name,
            row_index=start_row_index + idx,
        )
        payloads.append(p)

    # Convert to points and upsert
    # Note: we filter embeddings to match valid payloads
    valid_indices = [i for i, r in enumerate(rows_list) if str(r.get("full_name", "")).strip()]
    valid_embeddings = [embeddings[i] for i in valid_indices]
    
    points = to_record_points(payloads)
    
    # QdrantRepo.upsert expects chunks (points) and vectors
    repo.upsert(chunks=points, vectors=valid_embeddings)

    # --------------------------------
    # (E) Upsert to Postgres (Sync)
    # --------------------------------
    upsert_person_rows_to_postgres(payloads)

    return {
        "collection_name": collection_name,
        "doc_id": str(doc_id),
        "inserted_points": len(points),
        "vector_size": repo_cfg.vector_size,
        "embed_model": openai_embed_model,
    }


def upsert_person_rows_to_postgres(payloads: List[PersonPointPayload]):
    db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        print("Warning: No DB_URL found, skipping Postgres upsert.")
        return

    # Force sync driver for this script
    if "+asyncpg" in db_url:
        db_url = db_url.replace("+asyncpg", "")
    
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            # 1. Insert parent document (once)
            if payloads:
                first_p = payloads[0]
                doc_id_str = str(first_p.doc_id)
                source_uri = first_p.citation.source.source_uri if first_p.citation else "unknown"
                
                doc_stmt = text("""
                    INSERT INTO documents (doc_id, scope, doc_category, title, source_uri, mime_type, checksum)
                    VALUES (:doc_id, :scope, :doc_category, :title, :source_uri, :mime_type, :checksum)
                    ON CONFLICT (doc_id) DO NOTHING;
                """)
                conn.execute(doc_stmt, parameters={
                    "doc_id": doc_id_str,
                    "scope": "public",
                    "doc_category": "people",
                    "title": "People Demo Data",
                    "source_uri": source_uri,
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "checksum": "demo_checksum"
                })

            # 2. Insert rows
            for p in payloads:
                # Merge search_text_ascii into data_content for SQL search
                data_for_db = p.data_content.copy()
                if p.search_text_ascii:
                    data_for_db["search_text_ascii"] = p.search_text_ascii
                
                sql_str = """
                    INSERT INTO structured_rows (row_id, doc_id, doc_category, row_index, data_content, citation, commune_id, search_text)
                    VALUES (:row_id, :doc_id, :doc_category, :row_index, :data_content, :citation, :commune_id, :search_text)
                    ON CONFLICT (row_id) DO UPDATE SET
                        doc_id = EXCLUDED.doc_id,
                        row_index = EXCLUDED.row_index,
                        data_content = EXCLUDED.data_content,
                        citation = EXCLUDED.citation,
                        commune_id = EXCLUDED.commune_id,
                        search_text = EXCLUDED.search_text;
                """
                stmt = text(sql_str)
                
                # Handle citation serialization safely
                cit_json = p.citation.model_dump_json() if p.citation else "{}"
                row_idx = p.citation.source.row_index if p.citation and p.citation.source.row_index is not None else 0
                
                conn.execute(stmt, parameters={
                    "row_id": str(p.row_id),
                    "doc_id": str(p.doc_id),
                    "doc_category": "people",
                    "row_index": row_idx,
                    "data_content": json.dumps(data_for_db, ensure_ascii=False),
                    "citation": cit_json,
                    "commune_id": None,
                    "search_text": p.search_text_ascii or ""
                })

                # 3. Insert into chunks (for RAG)
                # We use the same row_id as chunk_id for simplicity in this demo
                embed_text = row_to_embed_text(p.data_content)
                chunk_sql = """
                    INSERT INTO chunks (chunk_id, doc_id, doc_category, chunk_kind, display_text, embed_text, citation, source_uri, mime_type, checksum, scope, order_index)
                    VALUES (:chunk_id, :doc_id, :doc_category, :chunk_kind, :display_text, :embed_text, :citation, :source_uri, :mime_type, :checksum, :scope, :order_index)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        display_text = EXCLUDED.display_text,
                        embed_text = EXCLUDED.embed_text,
                        citation = EXCLUDED.citation;
                """
                conn.execute(text(chunk_sql), parameters={
                    "chunk_id": str(p.row_id),
                    "doc_id": str(p.doc_id),
                    "doc_category": "people",
                    "chunk_kind": "text",
                    "display_text": embed_text,
                    "embed_text": embed_text,
                    "citation": cit_json,
                    "source_uri": source_uri,
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "checksum": "demo_checksum",
                    "scope": "public",
                    "order_index": row_idx
                })

            conn.commit()
        print(f"Upserted {len(payloads)} rows to Postgres structured_rows.")
    except Exception as e:
        print(f"Error upserting to Postgres: {e}")
        import traceback
        traceback.print_exc()
