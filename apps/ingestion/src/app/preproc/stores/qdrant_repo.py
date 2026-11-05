# preproc/stores/qdrant_repo.py
from __future__ import annotations

import logging
import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
import re
import unicodedata

from app.preproc.utils.pii import detect_pii

logger = logging.getLogger(__name__)

_SPACES = re.compile(r"\s+", re.UNICODE)

def _nfc_lower(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = s.strip().lower()
    s = _SPACES.sub(" ", s)
    return s

def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", s)

def _name_ascii(s: str) -> str:
    return _nfc_lower(_strip_accents(s))


def _is_enum(v: Any) -> bool:
    return hasattr(v, "value") and hasattr(v, "name") and not isinstance(v, (str, bytes))


def _safe(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, UUID):
        return str(v)
    if _is_enum(v):
        return v.value
    return v


def _dump_model(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    raise TypeError(f"Unsupported model type: {type(obj)}")


@dataclass(frozen=True)
class QdrantRepoConfig:
    url: str = "http://localhost:6333"
    api_key: Optional[str] = None
    prefer_grpc: bool = False

    collection_name: str = "ingestion_chunks"
    vector_name: Optional[str] = None  # If set, use named vector
    vector_size: int = 768
    vector_size: int = 768
    distance: str = "Cosine"  # Cosine|Dot|Euclid
    embedding_model_id: str = "unknown" # Parity Check

    on_disk_payload: bool = True
    hnsw_m: int = 16
    hnsw_ef_construct: int = 128
    full_scan_threshold: int = 10_000
    indexing_threshold: int = 20_000
    memmap_threshold: int = 20_000

    recreate_if_exists: bool = False

    upsert_batch_size: int = 256  # avoid huge HTTP payloads
    timeout: int = 60  # default timeout


class QdrantRepo:
    """
    Qdrant repo:
      - point id = chunk_id (deterministic)
      - payload = small/filterable (no big text)
      - batch upsert for stability
    """

    def __init__(self, cfg: QdrantRepoConfig) -> None:
        self.cfg = cfg
        self.client = QdrantClient(url=cfg.url, api_key=cfg.api_key, prefer_grpc=cfg.prefer_grpc, timeout=cfg.timeout)
        self.ensure_collection()

    def ensure_collection(self) -> None:
        name = self.cfg.collection_name
        existing = {c.name for c in self.client.get_collections().collections}

        if name in existing and self.cfg.recreate_if_exists:
            logger.warning("Recreating Qdrant collection=%s", name)
            self.client.delete_collection(name)
            existing.remove(name)

        if name in existing:
            # Skip size check for now if named vectors are used (too complex to check generic)
            return

        dist = getattr(qm.Distance, self.cfg.distance.upper(), qm.Distance.COSINE)
        
        # If vector_name is set, create named vector config
        if self.cfg.vector_name:
            vectors_config = {
                self.cfg.vector_name: qm.VectorParams(size=int(self.cfg.vector_size), distance=dist)
            }
        else:
            vectors_config = qm.VectorParams(size=int(self.cfg.vector_size), distance=dist)

        self.client.create_collection(
            collection_name=name,
            vectors_config=vectors_config,
            hnsw_config=qm.HnswConfigDiff(
                m=int(self.cfg.hnsw_m),
                ef_construct=int(self.cfg.hnsw_ef_construct),
                full_scan_threshold=int(self.cfg.full_scan_threshold),
            ),
            optimizers_config=qm.OptimizersConfigDiff(
                indexing_threshold=int(self.cfg.indexing_threshold),
                memmap_threshold=int(self.cfg.memmap_threshold),
            ),
            on_disk_payload=bool(self.cfg.on_disk_payload),
        )

        # Payload indexes for filters (optional but recommended)
        # Payload indexes for strict production (SSoT)
        INDEX_FIELDS = {
            "tenant_id": qm.PayloadSchemaType.KEYWORD,
            "doc_type": qm.PayloadSchemaType.KEYWORD,
            "scope": qm.PayloadSchemaType.KEYWORD,
            "department_id": qm.PayloadSchemaType.KEYWORD,
            "geo_code": qm.PayloadSchemaType.KEYWORD,
            "domain": qm.PayloadSchemaType.KEYWORD,
            "chunk_kind": qm.PayloadSchemaType.KEYWORD,
            "doc_id": qm.PayloadSchemaType.KEYWORD,
            "entity_type": qm.PayloadSchemaType.KEYWORD,
            "code": qm.PayloadSchemaType.KEYWORD,
            "name_ascii": qm.PayloadSchemaType.KEYWORD,
            # Integer type
            "security_level": qm.PayloadSchemaType.INTEGER,
        }

        for field, schema_type in INDEX_FIELDS.items():
            try:
                self.client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=schema_type,
                )
            except Exception:
                logger.debug("Could not create payload index for '%s' (non-fatal).", field)

    # ----------------------------
    # Upsert / Delete
    # ----------------------------

    def upsert(self, chunks: Sequence[Any], vectors: Sequence[Sequence[float]], wait: bool = True) -> None:
        if not chunks:
            return
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks/vectors mismatch: {len(chunks)} != {len(vectors)}")

        bs = max(1, int(self.cfg.upsert_batch_size))
        for i in range(0, len(chunks), bs):
            sub_chunks = chunks[i : i + bs]
            sub_vecs = vectors[i : i + bs]
            points = self._build_points(sub_chunks, sub_vecs)
            self.client.upsert(collection_name=self.cfg.collection_name, points=points, wait=wait)

    def upsert_chunks(self, chunks: Sequence[Any], vectors: Sequence[Sequence[float]], wait: bool = True) -> None:
        return self.upsert(chunks, vectors, wait=wait)

    def delete_by_doc_id(self, doc_id: Union[str, UUID], wait: bool = True) -> None:
        flt = qm.Filter(
            must=[
                qm.FieldCondition(
                    key="doc_id",
                    match=qm.MatchValue(value=str(doc_id)),
                )
            ]
        )
        self.client.delete(
            collection_name=self.cfg.collection_name,
            points_selector=qm.FilterSelector(filter=flt),
            wait=wait,
        )

    def delete_by_doc_id_and_tenant(
        self,
        doc_id: Union[str, UUID],
        tenant_id: str,
        wait: bool = True,
    ) -> None:
        flt = qm.Filter(
            must=[
                qm.FieldCondition(
                    key="doc_id",
                    match=qm.MatchValue(value=str(doc_id)),
                ),
                qm.FieldCondition(
                    key="tenant_id",
                    match=qm.MatchValue(value=str(tenant_id)),
                ),
            ]
        )
        self.client.delete(
            collection_name=self.cfg.collection_name,
            points_selector=qm.FilterSelector(filter=flt),
            wait=wait,
        )

    # ----------------------------
    # Search helper (optional)
    # ----------------------------

    def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 10,
        score_threshold: Optional[float] = None,
        
        # Strict Filters
        tenant_id: Optional[str] = None,
        doc_type: Optional[str] = None,
        scope: Optional[str] = None,
        geo_code: Optional[str] = None,
        
        # Legacy/Extra Filters
        commune_id: Optional[str] = None,
        doc_category: Optional[str] = None,
        chunk_kind: Optional[str] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        must = []
        
        if tenant_id:
            must.append(qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=tenant_id)))
        if doc_type:
            must.append(qm.FieldCondition(key="doc_type", match=qm.MatchValue(value=doc_type)))
        if scope:
            must.append(qm.FieldCondition(key="scope", match=qm.MatchValue(value=scope)))
        if geo_code:
            must.append(qm.FieldCondition(key="geo_code", match=qm.MatchValue(value=geo_code)))
        
        # Legacy fallback
        if commune_id:
            must.append(qm.FieldCondition(key="commune_id", match=qm.MatchValue(value=commune_id)))
        if doc_category:
            must.append(qm.FieldCondition(key="doc_category", match=qm.MatchValue(value=doc_category)))
            
        if chunk_kind:
            must.append(qm.FieldCondition(key="chunk_kind", match=qm.MatchValue(value=chunk_kind)))

        flt = qm.Filter(must=must) if must else None

        # Handle named vector search
        if self.cfg.vector_name:
            query = qm.NamedVector(name=self.cfg.vector_name, vector=list(query_vector))
        else:
            query = list(query_vector)

        res = self.client.search(
            collection_name=self.cfg.collection_name,
            query_vector=query,
            limit=int(limit),
            with_payload=True,
            score_threshold=score_threshold,
            query_filter=flt,
        )
        out: List[Tuple[str, float, Dict[str, Any]]] = []
        for p in res:
            out.append((str(p.id), float(p.score), p.payload or {}))
        return out

    # ----------------------------
    # Internals
    # ----------------------------

    def _build_points(self, chunks: Sequence[Any], vectors: Sequence[Sequence[float]]) -> List[qm.PointStruct]:
        points: List[qm.PointStruct] = []
        for c, v in zip(chunks, vectors):
            cd = _dump_model(c)

            # Prefer canonical qdrant_payload() if provided by your model
            payload = None
            if hasattr(c, "qdrant_payload") and callable(getattr(c, "qdrant_payload")):
                try:
                    payload = c.qdrant_payload()
                except Exception:
                    payload = None

            if payload is None:
                payload = self._build_payload_from_chunk(cd)
            else:
                # CanonicalChunk.qdrant_payload() may omit PII flags.
                # For strict PUBLIC filters in backend, ensure contains_pii is always present.
                if payload.get("contains_pii") is None:
                    text_to_scan = cd.get("display_text", "") or cd.get("embed_text", "")
                    contains_pii, pii_types = detect_pii(text_to_scan)
                    payload["contains_pii"] = contains_pii
                    payload["pii_types"] = pii_types

            # Handle named vector
            if self.cfg.vector_name:
                vector_data = {self.cfg.vector_name: list(v)}
            else:
                vector_data = list(v)

            points.append(
                qm.PointStruct(
                    id=str(cd["chunk_id"]),
                    vector=vector_data,
                    payload=payload,
                )
            )
        return points

    def _build_payload_from_chunk(self, cd: Dict[str, Any]) -> Dict[str, Any]:
        citation = cd.get("citation")
        loc: Dict[str, Any] = {}
        if citation:
            cit = citation if isinstance(citation, dict) else _dump_model(citation)

            # support both locator and source
            if "source" in cit and isinstance(cit.get("source"), dict):
                src = cit["source"]
                loc = {
                    "source_uri": src.get("source_uri"),
                    "mime_type": src.get("mime_type"),
                    "checksum": src.get("checksum"),
                    "sheet_name": src.get("sheet_name"),
                    "row_start": src.get("row_index"),
                    "row_end": src.get("row_index"),
                    "page_start": src.get("page_index"),
                    "page_end": src.get("page_index"),
                }
            else:
                locator = cit.get("locator")
                if locator:
                    loc = locator if isinstance(locator, dict) else _dump_model(locator)
        
        # PII Detection (P1 Security)
        text_to_scan = cd.get("display_text", "") or cd.get("embed_text", "")
        contains_pii, pii_types = detect_pii(text_to_scan)

        payload: Dict[str, Any] = {
            "chunk_id": str(cd["chunk_id"]),
            "doc_id": str(cd["doc_id"]),
            "parent_chunk_id": str(cd["parent_chunk_id"]) if cd.get("parent_chunk_id") else None,
            
            # Strict Keys (if present in model)
            "tenant_id": cd.get("tenant_id"),
            "embedding_model_id": getattr(self.cfg, "embedding_model_id", "unknown"), # Parity Check (P1)
            "doc_type": cd.get("doc_type"),
            "scope": _safe(cd.get("scope")),
            "security_level": cd.get("security_level"),
            "department_id": cd.get("department_id"),
            "geo_code": cd.get("geo_code"),
            "domain": cd.get("domain"),
            
            # PII Flags (P1 Security)
            "contains_pii": contains_pii,
            "pii_types": pii_types,

            # Legacy/Fallback (only if strictly needed for compat, but plan says remove)
            # "commune_id": cd.get("commune_id"),
            # "doc_category": _safe(cd.get("doc_category")),
            "chunk_kind": _safe(cd.get("chunk_kind")),
            "order_index": int(cd.get("order_index") or 0),

            # flat locator (existing behaviour)
            "source_uri": loc.get("source_uri"),
            "mime_type": loc.get("mime_type"),
            "checksum": loc.get("checksum"),
            "page_start": loc.get("page_start"),
            "page_end": loc.get("page_end"),
            "sheet_name": loc.get("sheet_name"),
            "row_start": loc.get("row_start"),
            "row_end": loc.get("row_end"),
            "anchor": loc.get("anchor"),

            # optional
            "law_ref": cd.get("law_ref"),
            "section_path": cd.get("section_path"),
        }

        # nested citation for backend compatibility
        row_idx = None
        try:
            rs = loc.get("row_start")
            re_ = loc.get("row_end")
            if rs is not None and (re_ is None or rs == re_):
                row_idx = rs
        except Exception:
            row_idx = None

        payload["citation"] = {
            "source": {
                "source_uri": loc.get("source_uri"),
                "sheet_name": loc.get("sheet_name"),
                "row_index": row_idx,
                "page_index": loc.get("page_start"),
            }
        }

        # pass-through if chunk already has these keys (demo/person rows)
        if cd.get("entity_type"):
            payload["entity_type"] = cd.get("entity_type")

        if isinstance(cd.get("data_content"), dict):
            payload["data_content"] = cd["data_content"]

            # best-effort: derive person lookup keys from data_content
            full_name = cd["data_content"].get("full_name") or cd["data_content"].get("name")
            code = cd["data_content"].get("code")

            if full_name:
                payload["name"] = str(full_name)
                payload["name_ascii"] = _name_ascii(str(full_name))
            if code:
                payload["code"] = str(code).strip().upper()

        return payload
