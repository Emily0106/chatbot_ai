# apps/ingestion/src/app/preproc/normalizers/llm_column_mapper.py
from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, Field

# Reuse the helper from backend (assuming shared lib or copy)
# For now, we'll assume we can import from core_shared or similar if available
# But since ingestion and backend are separate, we might need to duplicate the helper
# or put it in libs/core_shared. 
# To keep it simple as per plan, I will duplicate the minimal helper here or assume it's available.
# Actually, let's put the helper in libs/core_shared to be clean.

# Wait, the plan said "put file apps/ingestion/src/app/preproc/normalizers/llm_column_mapper.py"
# and "copy helper or use shared".
# I will implement the helper inline here to avoid cross-service dependency issues for now, 
# or better, I should have put structured_outputs in core_shared.
# Let's implement the mapper class and assume the caller provides the extraction logic 
# OR implement a minimal extractor here.

import os
import json
from openai import AsyncOpenAI

def pydantic_to_strict_json_schema(model):
    schema = model.model_json_schema()
    schema.setdefault("additionalProperties", False)
    return schema

async def aextract_pydantic_ingest(
    *,
    response_model,
    llm_model: str,
    system: str,
    user: str,
    schema_name: str,
):
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None # Fail silently or raise

    client = AsyncOpenAI(api_key=api_key)
    schema = pydantic_to_strict_json_schema(response_model)

    resp = await client.chat.completions.create(
        model=llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    )
    raw = resp.choices[0].message.content
    data = json.loads(raw)
    return response_model.model_validate(data)


class ColumnMapItem(BaseModel):
    header: str
    canonical_key: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

class ColumnMapResult(BaseModel):
    items: List[ColumnMapItem]
    missing_required: List[str] = Field(default_factory=list)


async def map_headers_to_canonical(
    *,
    headers: List[str],
    canonical_fields: List[str],
    required_fields: List[str],
    llm_model: str,
) -> ColumnMapResult:
    system = (
        "Bạn là hệ thống mapping cột Excel/CSV sang schema chuẩn.\n"
        "Chỉ chọn canonical_key trong danh sách canonical_fields.\n"
        "Nếu không chắc thì để canonical_key = null và confidence thấp.\n"
    )
    user = (
        f"headers={headers}\n"
        f"canonical_fields={canonical_fields}\n"
        f"required_fields={required_fields}\n"
        "Hãy map từng header sang canonical_key phù hợp."
    )

    res = await aextract_pydantic_ingest(
        response_model=ColumnMapResult,
        llm_model=llm_model,
        system=system,
        user=user,
        schema_name="column_map_result",
    )
    
    if not res:
        return ColumnMapResult(items=[])

    mapped = {it.canonical_key for it in res.items if it.canonical_key}
    missing = [k for k in required_fields if k not in mapped]
    res.missing_required = missing
    return res
