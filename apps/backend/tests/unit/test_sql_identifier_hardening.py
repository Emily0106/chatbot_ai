import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.core.db_sql import fetch_chunks_by_ids
from app.config import settings

@pytest.mark.asyncio
async def test_invalid_identifier_rejected():
    """
    Test A: Verify that malicious table/column names in settings are rejected.
    """
    mock_session = AsyncMock()
    
    # We patch the settings object used in db_sql.py
    # Since getattr is used, we can mock the attribute access
    with patch("app.core.db_sql.settings") as mock_settings:
        # Configure mock to behave like settings but with malicious table
        mock_settings.CHUNKS_TABLE = "chunks; DROP TABLE users"
        mock_settings.CHUNK_ID_COL = "chunk_id" 
        mock_settings.CHUNK_DOCUMENT_ID_COL = "doc_id"
        mock_settings.CHUNK_EMBED_TEXT_COL = "embed_text"
        mock_settings.CHUNK_DISPLAY_TEXT_COL = "display_text"
        mock_settings.CHUNK_PAYLOAD_COL = "payload"
        mock_settings.CHUNK_SECURITY_COL = "security_level"
        
        # Also need ALLOW_DEFAULT_TENANT if we hit that path (we won't if t1)
        
        with pytest.raises(ValueError, match="Invalid SQL Table Name"):
             await fetch_chunks_by_ids(
                 mock_session, 
                 tenant_id="t1", 
                 chunk_ids=["c1"]
             )

@pytest.mark.asyncio
async def test_default_tenant_blocked():
    """
    Test B: Verify tenant_id='default' is blocked when ALLOW_DEFAULT_TENANT=False
    """
    mock_session = AsyncMock()
    
    # Patch ALLOW_DEFAULT_TENANT on the real settings or mock it
    # Pydantic settings are tricky to patch directly if field doesn't exist or is frozen
    # So we patch the import in db_sql
    with patch("app.core.db_sql.settings") as mock_settings:
        mock_settings.ALLOW_DEFAULT_TENANT = False
        
        with pytest.raises(ValueError, match="Access to default tenant is restricted"):
            await fetch_chunks_by_ids(
                mock_session,
                tenant_id="default",
                chunk_ids=["c1"]
            )

@pytest.mark.asyncio
async def test_default_tenant_allowed():
    """
    Test C: Verify "default" tenant proceeds if allowed.
    """
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result
    
    with patch("app.core.db_sql.settings") as mock_settings:
        mock_settings.ALLOW_DEFAULT_TENANT = True
        # Ensure identifiers are valid so we don't fail validation
        mock_settings.CHUNKS_TABLE = "chunks"
        mock_settings.CHUNK_ID_COL = "chunk_id"
        mock_settings.CHUNK_DOCUMENT_ID_COL = "doc_id"
        mock_settings.CHUNK_EMBED_TEXT_COL = "embed_text"
        mock_settings.CHUNK_DISPLAY_TEXT_COL = "display_text"
        mock_settings.CHUNK_PAYLOAD_COL = "payload"
        mock_settings.CHUNK_SECURITY_COL = "security_level"
        mock_settings.DOCUMENTS_TABLE = "documents"
        mock_settings.DOCUMENT_ID_COL = "doc_id"
        mock_settings.DOCUMENT_TENANT_COL = "tenant_id"
        
        await fetch_chunks_by_ids(
            mock_session,
            tenant_id="default",
            chunk_ids=["c1"]
        )
        
    assert mock_session.execute.called
    # check that sql uses document-tenant join filter
    sql_str = str(mock_session.execute.call_args[0][0])
    assert "d.tenant_id = :tenant_id" in sql_str
