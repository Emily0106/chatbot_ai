from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence
from uuid import UUID

from core_shared.contracts import RecordPayload
from qdrant_client.http import models as qm

@dataclass
class RecordPoint:
    """
    Adapter object để QdrantRepo upsert.
    QdrantRepo của bạn dùng chunk_id/doc_id, nên ta fake field chunk_id = row_id.
    """
    chunk_id: UUID
    doc_id: UUID
    data_content: dict
    entity_type: str
    code: str | None
    name_ascii: str | None
    citation: dict

    def qdrant_payload(self) -> dict:
        # payload filterable + nested citation
        return {
            "entity_type": self.entity_type,
            "doc_id": str(self.doc_id),
            "row_id": str(self.chunk_id),
            "code": self.code,
            "name_ascii": self.name_ascii,
            "data_content": self.data_content,
            "citation": self.citation,
        }

def to_record_points(payloads: Sequence[RecordPayload]) -> List[RecordPoint]:
    pts: List[RecordPoint] = []
    for p in payloads:
        pts.append(
            RecordPoint(
                chunk_id=p.row_id,
                doc_id=p.doc_id,
                data_content=p.data_content,
                entity_type=p.entity_type,
                code=p.code,
                name_ascii=p.name_ascii,
                citation=p.citation.model_dump() if p.citation else {},
            )
        )
    return pts
