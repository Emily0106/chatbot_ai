"""
Gov-Grade Query Expansion - Schemas (PR-01).

This module intentionally contains *only* foundational data structures.
No business logic should live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class QueryExpansionConfig:
    """Configuration for the Query Expansion pipeline.

    Fail-closed philosophy: defaults should be safe, explicit, and bounded.
    """

    enable_llm_rewrite: bool = True
    llm_timeout_ms: int = 300

    max_variants_total: int = 6
    max_lexicon_variants: int = 2
    max_rule_variants: int = 1
    max_llm_variants: int = 2

    max_query_chars: int = 256

    # Safety guard: if injection heuristics trigger, do not call LLM rewrite.
    disable_llm_if_injection_suspected: bool = True


class QueryVariant(BaseModel):
    """A single rewritten/expanded query variant."""

    model_config = ConfigDict(extra="forbid")

    text: str
    source: Literal["ORIGINAL", "LEXICON", "RULE", "LLM"]
    weight: float
    meta: Dict[str, Any] = Field(default_factory=dict)


class QueryPack(BaseModel):
    """Container that holds the expanded query set and associated metadata."""

    model_config = ConfigDict(extra="forbid")

    original_query: str
    normalized_query: str
    redacted_query: str

    # Flags are intentionally a dict at this stage to keep PR-01 minimal.
    # Expected keys: contains_pii, pii_types, is_code_query, injection_suspected
    flags: Dict[str, Any]

    must_keep_tokens: List[str]
    variants: List[QueryVariant]

    # Debug / telemetry fields
    # Expected keys: lexicon_version, llm_used, llm_timeout
    debug: Dict[str, Any]

    # Audit fields
    # Expected keys: expansion_applied, variants_count
    audit: Dict[str, Any]
