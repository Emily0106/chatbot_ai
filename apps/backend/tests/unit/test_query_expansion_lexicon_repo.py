import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.rag.query_expansion.lexicon_repo import LexiconRepo
from app.core.rag.query_expansion.schemas_lexicon import LexiconMatch

@pytest.fixture
def mock_session():
    return AsyncMock()

@pytest.mark.asyncio
async def test_version_returns_value(mock_session):
    # Setup mock row
    mock_row = MagicMock()
    mock_row.value = "1"
    
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_session.execute.return_value = mock_result
    
    repo = LexiconRepo(mock_session)
    version = await repo.version()
    
    assert version == "1"
    assert mock_session.execute.called
    
    sql_stmt = str(mock_session.execute.call_args[0][0])
    assert "rag_lexicon_meta" in sql_stmt
    assert "global_lexicon_version" in sql_stmt

@pytest.mark.asyncio
async def test_version_returns_0_if_missing(mock_session):
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_session.execute.return_value = mock_result
    
    repo = LexiconRepo(mock_session)
    version = await repo.version()
    
    assert version == "0"

@pytest.mark.asyncio
async def test_version_returns_0_on_exception(mock_session):
    mock_session.execute.side_effect = Exception("DB Connection lost")
    
    repo = LexiconRepo(mock_session)
    version = await repo.version()
    
    assert version == "0"

@pytest.mark.asyncio
async def test_match_returns_active_global_only(mock_session):
    # Mock row returned by DB
    mock_row1 = MagicMock()
    mock_row1.alias = "xe máy"
    mock_row1.canonical = "xe mô tô"
    mock_row1.term_type = "synonym"
    mock_row1.weight = 100
    
    mock_row2 = MagicMock()
    mock_row2.alias = "thuế"
    mock_row2.canonical = "lệ phí"
    mock_row2.term_type = "synonym"
    mock_row2.weight = 50
    
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row1, mock_row2]
    mock_session.execute.return_value = mock_result
    
    repo = LexiconRepo(mock_session)
    matches = await repo.match("xe may thue", "xe may thue")
    
    # Assert return types and data
    assert len(matches) == 2
    assert isinstance(matches[0], LexiconMatch)
    assert matches[0].alias == "xe máy"
    assert matches[0].canonical == "xe mô tô"
    assert matches[1].alias == "thuế"
    
    # Assert SQL structure enforces global and active rules
    assert mock_session.execute.called
    args, kwargs = mock_session.execute.call_args
    sql_stmt = str(args[0])
    
    assert "tenant_id IS NULL" in sql_stmt, "Phase-1 must enforce global only"
    assert "status = 'active'" in sql_stmt, "Must exclude deprecated terms"
    assert "alias_norm = :alias_norm" in sql_stmt, "Must match alias_norm"
    assert "ORDER BY weight DESC, LENGTH(alias) DESC" in sql_stmt, "Ordering must be stable"
    
    assert args[1]["alias_norm"] == "xe may thue"
