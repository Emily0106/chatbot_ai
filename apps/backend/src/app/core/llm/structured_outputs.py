# apps/backend/src/app/core/llm/structured_outputs.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

from openai import AsyncOpenAI


def pydantic_to_strict_json_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    """
    Convert Pydantic model -> JSON Schema (OpenAI Structured Outputs format).
    Lưu ý: schema phải tương thích subset JSON Schema mà Structured Outputs hỗ trợ.
    """
    schema = model.model_json_schema()
    # harden a bit
    schema.setdefault("additionalProperties", False)
    return schema


async def aextract_structured(
    *,
    model: str,
    system: str,
    user: str,
    schema_name: str,
    schema: Dict[str, Any],
    temperature: float = 0.0,
    max_output_tokens: int = 400,
) -> Dict[str, Any]:
    """
    Returns a parsed dict that must match schema (strict).
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing")

    client = AsyncOpenAI(api_key=api_key)

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_output_tokens,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    )

    # structured output thường nằm ở output_text dạng JSON string
    raw = resp.choices[0].message.content
    if not raw:
        raise RuntimeError("Empty structured output from model")

    return json.loads(raw)


async def aextract_pydantic(
    *,
    response_model: Type[T],
    llm_model: str,
    system: str,
    user: str,
    schema_name: str,
) -> T:
    schema = pydantic_to_strict_json_schema(response_model)
    data = await aextract_structured(
        model=llm_model,
        system=system,
        user=user,
        schema_name=schema_name,
        schema=schema,
    )
    return response_model.model_validate(data)
