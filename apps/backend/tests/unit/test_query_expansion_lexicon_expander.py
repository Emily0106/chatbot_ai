from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the src/ directory is importable when running tests from repo root.
SRC_DIR = Path(__file__).resolve().parents[4] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.core.rag.query_expansion.lexicon_expander import build_lexicon_variants
from app.core.rag.query_expansion.preprocess import PreprocessResult
from app.core.rag.query_expansion.schemas_lexicon import LexiconMatch


def test_expander_basic_rewrite() -> None:
    pre = PreprocessResult(
        original_query="xe máy lệ phí trước bạ",
        normalized_query="xe máy lệ phí trước bạ",
        normalized_no_diacritic="xe may le phi truoc ba",
        redacted_query="xe máy lệ phí trước bạ",
        flags={},
        must_keep_tokens=[],
    )
    
    matches = [
        LexiconMatch(alias="xe máy", canonical="xe mô tô", term_type="synonym", weight=100)
    ]
    
    variants = build_lexicon_variants(pre, matches)
    
    assert len(variants) == 1
    assert variants[0].text == "xe mô tô lệ phí trước bạ"
    assert variants[0].source == "LEXICON"
    assert "xe mô tô" in variants[0].text


def test_expander_prefer_longer_alias() -> None:
    pre = PreprocessResult(
        original_query="xe máy màu xanh",
        normalized_query="xe máy màu xanh",
        normalized_no_diacritic="xe may mau xanh",
        redacted_query="xe máy màu xanh",
        flags={},
        must_keep_tokens=[],
    )
    
    # Intentionally disordered, the module must re-sort
    matches = [
        LexiconMatch(alias="xe", canonical="phương tiện", term_type="synonym", weight=100),
        LexiconMatch(alias="xe máy", canonical="xe mô tô", term_type="synonym", weight=100)
    ]
    
    variants = build_lexicon_variants(pre, matches, max_n=1)
    
    assert len(variants) == 1
    assert variants[0].text == "xe mô tô màu xanh"


def test_expander_dedupe_drops_identical() -> None:
    pre = PreprocessResult(
        original_query="đi bộ an toàn",
        normalized_query="đi bộ an toàn",
        normalized_no_diacritic="di bo an toan",
        redacted_query="đi bộ an toàn",
        flags={},
        must_keep_tokens=[],
    )
    
    # Matches a word that isn't in query
    matches = [
        LexiconMatch(alias="ô tô", canonical="xe hơi", term_type="synonym", weight=100)
    ]
    
    variants = build_lexicon_variants(pre, matches)
    # The output is identical to original, it must be deduped
    assert len(variants) == 0


def test_expander_max_n_cap_respected() -> None:
    pre = PreprocessResult(
        original_query="a b c d e",
        normalized_query="a b c d e",
        normalized_no_diacritic="a b c d e",
        redacted_query="a b c d e",
        flags={},
        must_keep_tokens=[],
    )
    
    matches = [
        LexiconMatch(alias="a", canonical="alpha", term_type="synonym", weight=100),
        LexiconMatch(alias="b", canonical="beta", term_type="synonym", weight=90),
        LexiconMatch(alias="c", canonical="gamma", term_type="synonym", weight=80),
        LexiconMatch(alias="d", canonical="delta", term_type="synonym", weight=70),
    ]
    
    variants = build_lexicon_variants(pre, matches, max_n=2)
    assert len(variants) == 2
    assert variants[0].text == "alpha b c d e"
    assert variants[1].text == "a beta c d e"
