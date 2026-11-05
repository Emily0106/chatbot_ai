"""
GovGrade LLM Query Expansion Schema.
"""
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class VariantItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    text: str = Field(..., min_length=1, max_length=256)
    type: Literal["CANONICAL", "FORMAL", "SYNONYM"]
    used_terms: List[str] = Field(..., max_length=16)
    must_keep_ok: bool


class GovGradeQueryRewriteOutput(BaseModel):
    """Strict structured output model for LLM query rewriting."""
    model_config = ConfigDict(extra="forbid")
    
    canonical_query: str = Field(..., min_length=1, max_length=256)
    variants: List[VariantItem] = Field(..., max_length=3)
    notes: Optional[str] = Field(None, max_length=256)
