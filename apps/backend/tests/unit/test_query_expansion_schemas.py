from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

# Ensure the src/ directory is importable when running tests from repo root.
SRC_DIR = Path(__file__).resolve().parents[4] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.core.rag.query_expansion.schemas import (  # noqa: E402
    QueryExpansionConfig,
    QueryPack,
    QueryVariant,
)


def test_query_expansion_config_defaults() -> None:
    cfg = QueryExpansionConfig()

    assert cfg.enable_llm_rewrite is True
    assert cfg.llm_timeout_ms == 300

    assert cfg.max_variants_total == 6
    assert cfg.max_lexicon_variants == 2
    assert cfg.max_rule_variants == 1
    assert cfg.max_llm_variants == 2

    assert cfg.max_query_chars == 256
    assert cfg.disable_llm_if_injection_suspected is True


def test_query_pack_creation_with_variants() -> None:
    variants = [
        QueryVariant(text="xe máy lệ phí trước bạ", source="ORIGINAL", weight=1.0),
        QueryVariant(text="xe mô tô lệ phí trước bạ", source="LEXICON", weight=0.95),
    ]

    pack = QueryPack(
        original_query="xe máy lệ phí trước bạ",
        normalized_query="xe máy lệ phí trước bạ",
        redacted_query="xe máy lệ phí trước bạ",
        flags={
            "contains_pii": False,
            "pii_types": [],
            "is_code_query": False,
            "injection_suspected": False,
        },
        must_keep_tokens=[],
        variants=variants,
        debug={"lexicon_version": "1", "llm_used": False, "llm_timeout": False},
        audit={"expansion_applied": True, "variants_count": 2},
    )

    assert pack.variants[0].source == "ORIGINAL"
    assert pack.variants[1].source == "LEXICON"
    assert pack.audit["variants_count"] == 2


def test_query_variant_source_literal_validation() -> None:
    with pytest.raises(ValidationError):
        QueryVariant(text="abc", source="INVALID", weight=1.0)  # type: ignore[arg-type]
