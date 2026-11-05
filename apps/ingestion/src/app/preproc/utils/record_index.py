from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID, uuid4, uuid5

from core_shared.text_utils import ascii_norm, build_search_text_ascii, extract_keywords_ascii
from core_shared.contracts import Citation, RecordPayload, SourceRef


# Tạo namespace UUID cố định cho project (tùy bạn đặt)
_UUID_NS = UUID("12345678-1234-5678-1234-567812345678")


def _deterministic_row_id(
    *,
    doc_id: UUID,
    sheet_name: Optional[str],
    row_index: Optional[int],
    code: Optional[str],
    full_name: Optional[str],
) -> UUID:
    # row_index ưu tiên cao nhất, vì stable khi re-ingest same file
    key = f"{doc_id}:{sheet_name or ''}:{row_index if row_index is not None else ''}:{code or ''}:{full_name or ''}"
    return uuid5(_UUID_NS, key)


def build_person_record_payload(
    row: Dict[str, Any],
    *,
    doc_id: UUID,  # <-- bắt buộc truyền vào từ orchestrator (1 doc_id cho cả file)
    source_uri: str,
    sheet_name: Optional[str] = None,
    row_index: Optional[int] = None,
) -> RecordPayload:
    full_name = str(row.get("full_name") or "").strip()
    code = (str(row.get("code")).strip().upper() if row.get("code") is not None else None)

    # deterministic row_id để re-ingest không nhân bản
    row_id = _deterministic_row_id(
        doc_id=doc_id,
        sheet_name=sheet_name,
        row_index=row_index,
        code=code,
        full_name=full_name,
    )

    name_ascii = ascii_norm(full_name) if full_name else None

    occupation = str(row.get("occupation") or "")
    note = str(row.get("note") or "")
    unit = str(row.get("ward_commune") or "")
    address = str(row.get("address") or "")

    # nên đưa thêm CCCD/phone/email vào search_text_ascii để lookup semantic fallback tốt hơn
    cccd = str(row.get("cccd") or "")
    phone = str(row.get("phone") or "")
    email = str(row.get("email") or "")

    search_text_ascii = build_search_text_ascii(
        full_name, code or "", cccd, phone, email, occupation, note, unit, address
    )
    search_tokens = extract_keywords_ascii(search_text_ascii)

    cit = Citation(
        source=SourceRef(
            source_uri=source_uri,
            sheet_name=sheet_name,
            row_index=row_index,
        )
    )

    return RecordPayload(
        entity_type="person",
        doc_id=doc_id,
        row_id=row_id,
        code=code,
        name=full_name,
        name_ascii=name_ascii,
        search_text_ascii=search_text_ascii,
        search_tokens=search_tokens,
        data_content=dict(row),
        citation=cit,
    )
