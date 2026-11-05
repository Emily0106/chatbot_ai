"""
Schemas for Lexicon data structures.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LexiconMatch(BaseModel):
    """Represents a matched lexicon term for query expansion."""

    model_config = ConfigDict(extra="forbid")

    alias: str
    canonical: str
    term_type: str
    weight: int
