from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.db_lexical import _safe_fts_config, search_lexical_chunks


def test_safe_fts_config_allowlist():
    assert _safe_fts_config("english") == "english"
    assert _safe_fts_config("SIMPLE") == "simple"
    assert _safe_fts_config("vi_vn") == "simple"


@pytest.mark.asyncio
async def test_lexical_query_uses_cast_for_cfg_binding():
    db = AsyncMock()
    with patch("app.core.db_lexical._execute_sql", new_callable=AsyncMock) as mock_sql:
        mock_sql.return_value = []
        await search_lexical_chunks(
            db,
            query="hello world",
            tenant_id="tenant_a",
            variants=[{"query": "hello world", "weight": 1.0}],
        )

        sql_query = mock_sql.call_args[0][1]
        params = mock_sql.call_args[0][2]

        assert "websearch_to_tsquery(CAST(:cfg AS regconfig), :q0)" in sql_query
        assert ":cfg::regconfig" not in sql_query
        assert params["cfg"] in {"simple", "english"}
