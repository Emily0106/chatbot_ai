from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

def scroll_exact_person(
    client: QdrantClient,
    *,
    collection: str,
    code: Optional[str] = None,
    name_ascii: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    must = [qmodels.FieldCondition(key="entity_type", match=qmodels.MatchValue(value="person"))]
    should = []
    if code:
        should.append(qmodels.FieldCondition(key="code", match=qmodels.MatchValue(value=code)))
        should.append(qmodels.FieldCondition(key="data_content.code", match=qmodels.MatchValue(value=code)))
    if name_ascii:
        should.append(qmodels.FieldCondition(key="name_ascii", match=qmodels.MatchValue(value=name_ascii)))
    flt = qmodels.Filter(must=must, should=should) if should else qmodels.Filter(must=must)

    pts, _ = client.scroll(
        collection_name=collection,
        scroll_filter=flt,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return [p.payload or {} for p in pts]

def scroll_keyword_person(
    client: QdrantClient,
    *,
    collection: str,
    keywords: List[str],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    must = [qmodels.FieldCondition(key="entity_type", match=qmodels.MatchValue(value="person"))]
    if keywords:
        must.append(qmodels.FieldCondition(
            key="search_tokens",
            match=qmodels.MatchAny(any=keywords),
        ))
    flt = qmodels.Filter(must=must)

    pts, _ = client.scroll(
        collection_name=collection,
        scroll_filter=flt,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return [p.payload or {} for p in pts]

def rank_by_keyword_overlap(payloads: List[Dict[str, Any]], keywords: List[str]) -> List[Dict[str, Any]]:
    if not keywords:
        return payloads
    def score(p: Dict[str, Any]) -> int:
        text = (p.get("search_text_ascii") or "")
        return sum(1 for k in keywords if k in text)
    return sorted(payloads, key=score, reverse=True)
