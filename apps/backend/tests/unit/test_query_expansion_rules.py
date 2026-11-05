from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the src/ directory is importable when running tests from repo root.
SRC_DIR = Path(__file__).resolve().parents[4] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.core.rag.query_expansion.rules import build_rule_variants
from app.core.rag.query_expansion.preprocess import PreprocessResult

def test_rule_r1_code_query() -> None:
    pre = PreprocessResult(
        original_query="123/2024/NĐ-CP",
        normalized_query="123/2024/NĐ-CP",
        normalized_no_diacritic="123/2024/nd-cp",
        redacted_query="123/2024/NĐ-CP",
        flags={},
        must_keep_tokens=["123/2024/NĐ-CP"]
    )
    
    variants = build_rule_variants(pre, max_n=3)
    assert len(variants) == 1
    assert variants[0].text == "Tra cứu 123/2024/NĐ-CP"
    assert variants[0].meta["rule_id"] == "CODE_QUERY_FORMAT"


def test_rule_r2_penalty() -> None:
    pre = PreprocessResult(
        original_query="mức phạt vượt đèn đỏ",
        normalized_query="mức phạt vượt đèn đỏ",
        normalized_no_diacritic="muc phat vuot den do",
        redacted_query="mức phạt vượt đèn đỏ",
        flags={},
        must_keep_tokens=[]
    )
    
    variants = build_rule_variants(pre, max_n=3)
    assert len(variants) == 1
    assert "xử phạt vi phạm hành chính" in variants[0].text
    assert variants[0].meta["rule_id"] == "PENALTY_VPHC"


def test_rule_r3_reissue() -> None:
    pre = PreprocessResult(
        original_query="mất CCCD làm lại thế nào",
        normalized_query="mất CCCD làm lại thế nào",
        normalized_no_diacritic="mat cccd lam lai the nao",
        redacted_query="mất CCCD làm lại thế nào",
        flags={},
        must_keep_tokens=[]
    )
    
    variants = build_rule_variants(pre, max_n=3)
    assert len(variants) == 1
    assert "cấp lại mất CCCD làm lại thế nào" in variants[0].text
    assert variants[0].meta["rule_id"] == "REISSUE_NORMALIZE"


def test_rule_max_n_and_dedupe() -> None:
    # A query that triggers multiple paths
    pre = PreprocessResult(
        original_query="mất giấy tờ và bị mức phạt",
        normalized_query="mất giấy tờ và bị mức phạt",
        normalized_no_diacritic="mat giay to va bi muc phat",
        redacted_query="mất giấy tờ và bị mức phạt",
        flags={},
        must_keep_tokens=[]
    )
    
    # Test Max N = 1 (Should only return the penalty rule due to evaluation order)
    variants_1 = build_rule_variants(pre, max_n=1)
    assert len(variants_1) == 1
    assert variants_1[0].meta["rule_id"] == "PENALTY_VPHC"
    
    # Test Max N = 3 (Should return both penalty and reissue variants)
    variants_all = build_rule_variants(pre, max_n=3)
    assert len(variants_all) == 2
    assert variants_all[0].meta["rule_id"] == "PENALTY_VPHC"
    assert variants_all[1].meta["rule_id"] == "REISSUE_NORMALIZE"

def test_rule_dedupe_returns_empty_if_no_change() -> None:
    pre = PreprocessResult(
        original_query="xử phạt vi phạm hành chính",
        normalized_query="xử phạt vi phạm hành chính",
        normalized_no_diacritic="xu phat vi pham hanh chinh",
        redacted_query="xử phạt vi phạm hành chính",
        flags={},
        must_keep_tokens=[]
    )
    
    variants = build_rule_variants(pre, max_n=3)
    # The penalty rule triggers, but attempts to add the same text resulting in a deduplicated empty array
    assert len(variants) == 0
