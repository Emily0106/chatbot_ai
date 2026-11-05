from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

# Ensure the src/ directory is importable when running tests from repo root.
SRC_DIR = Path(__file__).resolve().parents[4] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.core.rag.query_expansion.llm_rewriter import LLMRewriter
from app.core.rag.query_expansion.llm_schema import GovGradeQueryRewriteOutput, VariantItem

@pytest.fixture
def rewriter():
    return LLMRewriter(timeout=0.3)


@pytest.mark.asyncio
async def test_llm_valid_json_returns_output(rewriter):
    mock_out = GovGradeQueryRewriteOutput(
        canonical_query="thủ tục cấp lại căn cước công dân cccd",
        variants=[
            VariantItem(
                text="xin cấp lại cccd",
                type="SYNONYM",
                used_terms=["cccd"],
                must_keep_ok=True
            )
        ],
        notes=None
    )
    
    with patch("app.core.rag.query_expansion.llm_rewriter.aextract_pydantic", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = mock_out
        
        result = await rewriter.rewrite(
            redacted_query="làm lại cccd",
            allowed_terms=["cccd", "làm lại"],
            must_keep_tokens=["cccd"],
            max_variants=2
        )
        
        assert result is not None
        assert result.canonical_query == "thủ tục cấp lại căn cước công dân cccd"


@pytest.mark.asyncio
async def test_llm_invalid_schema_mismatch_returns_none(rewriter):
    # aextract_pydantic raises ValidationError on strict parsing failure
    with patch("app.core.rag.query_expansion.llm_rewriter.aextract_pydantic", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = ValidationError.from_exception_data("Mock Error", line_errors=[])
        
        result = await rewriter.rewrite(
            redacted_query="làm lại cccd",
            allowed_terms=["cccd"],
            must_keep_tokens=["cccd"],
            max_variants=2
        )
        assert result is None


@pytest.mark.asyncio
async def test_llm_used_terms_contains_disallowed_returns_none(rewriter):
    mock_out = GovGradeQueryRewriteOutput(
        canonical_query="thủ tục cấp lại căn cước",
        variants=[
            VariantItem(
                text="làm lại cmnd",
                type="SYNONYM",
                used_terms=["cmnd"],  # Disallowed term here
                must_keep_ok=True
            )
        ]
    )
    
    with patch("app.core.rag.query_expansion.llm_rewriter.aextract_pydantic", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = mock_out
        
        result = await rewriter.rewrite(
            redacted_query="làm lại cmnd",
            allowed_terms=["căn cước"], # "cmnd" not in allowed_terms
            must_keep_tokens=[],
            max_variants=2
        )
        assert result is None


@pytest.mark.asyncio
async def test_llm_must_keep_token_missing_returns_none(rewriter):
    mock_out = GovGradeQueryRewriteOutput(
        canonical_query="cấp lại cccd", # Missing "123/2024"
        variants=[
            VariantItem(
                text="cấp lại căn cước 123/2024",
                type="SYNONYM",
                used_terms=["cccd"],
                must_keep_ok=True
            )
        ]
    )
    
    with patch("app.core.rag.query_expansion.llm_rewriter.aextract_pydantic", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = mock_out
        
        result = await rewriter.rewrite(
            redacted_query="cấp lại cccd 123/2024",
            allowed_terms=["cccd"],
            must_keep_tokens=["123/2024"],
            max_variants=2
        )
        assert result is None  # Fails because "123/2024" missing from canonical_query


@pytest.mark.asyncio
async def test_llm_simulated_timeout_returns_none(rewriter):
    async def slow_mock(*args, **kwargs):
        await asyncio.sleep(0.5) # Exceeds 0.3s timeout
        return None
        
    with patch("app.core.rag.query_expansion.llm_rewriter.aextract_pydantic", side_effect=slow_mock):
        result = await rewriter.rewrite(
            redacted_query="test timeout",
            allowed_terms=[],
            must_keep_tokens=[],
            max_variants=2
        )
        assert result is None
