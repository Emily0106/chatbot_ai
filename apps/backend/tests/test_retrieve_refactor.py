import pytest
from unittest.mock import AsyncMock

# Mocking modules before import is tricky with standard unittest.mock in a single file without separate process or robust patching.
# However, we can use monkeypatching on the imported module if we import it inside the test or fixture.

@pytest.mark.asyncio
async def test_retrieve_uses_canonical_embed_query(monkeypatch):
    """
    Verify that the retrieve function's internal dense_embed_fn 
    delegates to app.core.llm.embed_query.
    """
    # 1. Mock dependent modules that might crash import (e.g. config settings)
    # Since we can't easily prevent import side-effects of 'app.core.rag.retrieve' if it was already imported,
    # we assume the environment is set up enough for import (or we mock sys.modules).
    # For now, let's try importing. If 'retrieve.py' imports 'settings' which validates env vars transparently,
    # we might need to set env vars.
    
    # We rely on the fact that previous steps might have verified imports or we use the passed monkeypatch env.
    
    import app.core.rag.retrieve as retrieve_module
    
    # 2. Mock embed_query in app.core.llm
    # We verify that retrieve.py -> imports embed_query -> we patch that import *where it looks*?
    # retrieve.py has: from app.core.llm import embed_query
    # So we should patch 'app.core.rag.retrieve.embed_query' OR 'app.core.llm.embed_query' depending on binding.
    # Because it is imported as a function, patching app.core.llm.embed_query affects future imports, 
    # but retrieve.py already imported it. So we must patch 'app.core.rag.retrieve.embed_query'.
    
    mock_embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    monkeypatch.setattr(retrieve_module, "embed_query", mock_embed_query)
    
    # 3. Setup mocks for retrieve()'s arguments and internal calls to avoid hitting DB/Qdrant
    mock_db = AsyncMock()
    
    # Mock search_hybrid_chunks to stop execution flow but capture the passed dense_embed_fn
    captured_fn = []
    
    async def mock_search_hybrid(*args, **kwargs):
        fn = kwargs.get('dense_embed_fn')
        if fn:
            captured_fn.append(fn)
            # Call it to trigger the embed_query
            await fn("test query")
        return [] # Return empty hits
    
    monkeypatch.setattr(retrieve_module, "search_hybrid_chunks", mock_search_hybrid)
    
    # 4. Call retrieve
    # We strictly only care about it calling search_hybrid -> dense_embed_fn -> embed_query
    await retrieve_module.retrieve(
        db=mock_db,
        tenant_id="test_tenant",
        agent_id="test_agent",
        query="test query"
    )
    
    # 5. Assertions
    assert len(captured_fn) == 1, "dense_embed_fn should be passed to search_hybrid_chunks"
    
    mock_embed_query.assert_called_once_with("test query")
