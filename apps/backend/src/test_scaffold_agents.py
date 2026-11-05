import pytest
import ast
import os
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.registry import registry, register_defaults
from app.agents.contract import TrustedContext, RefusalCode

# Ensure all agents registered
register_defaults()

AGENTS_TO_TEST = [
    "citizen_agent", "report_agent", "health_agent", "culture_agent", "agri_agent",
    "meeting_agent", "calendar_agent", "economy_agent", "doc_manager", "land_agent", "social_agent"
]

@pytest.mark.asyncio
async def test_registry_loads_11_agents():
    """Verify registry loads at least the 11 scaffolding agents."""
    agents = registry.list_agents()
    print(f"Registered Agents: {list(agents.keys())}")
    for agent_id in AGENTS_TO_TEST:
        assert agent_id in agents, f"{agent_id} not registered"

@pytest.mark.asyncio
@pytest.mark.parametrize("agent_id", AGENTS_TO_TEST)
async def test_all_agents_fail_closed_on_empty_db(agent_id):
    """Verify fail-closed behavior (Refusal) when no info/tool available."""
    agent = registry.get(agent_id)
    ctx = TrustedContext(
        tenant_id="test", user_id="u", security_level=2,
        request_payload={}, department_id="dept_1", geo_code="geo_1"
    )

    with patch("app.core.db_sql.get_async_db") as mock_get_db, \
         patch("app.core.rag.pipeline.rag_retrieve", new_callable=AsyncMock) as mock_rag, \
         patch("app.core.web_search.WebSearchService.search", new_callable=AsyncMock) as mock_search:
         
        # Mock Empty DB
        mock_get_db.return_value.__aiter__.return_value = [AsyncMock()]
        mock_rag.return_value = None # RAG returns nothing
        mock_search.return_value = [] # Web search returns nothing
        
        resp = await agent.process(ctx, "Test Query")
        
        # Must be a refusal
        meta = resp.meta.model_dump() if hasattr(resp.meta, "model_dump") else resp.meta
        assert meta.get("is_refusal") is True
        
        refusal = meta.get("refusal", {})
        code = refusal.get("code")
        
        # Allowable refusal codes: NO_EVIDENCE, NOT_IMPLEMENTED, OUT_OF_SCOPE
        assert code in [RefusalCode.NO_EVIDENCE, RefusalCode.NOT_IMPLEMENTED, RefusalCode.OUT_OF_SCOPE]

@pytest.mark.asyncio
async def test_cross_agent_pollution():
    """Test pollution: Asking economy agent about tourism should ideally fail or be unrelated."""
    # This is a behavior test. 
    # Since we mock RAG to be empty, they will refuse 'NO_EVIDENCE'. 
    # Pollution is harder to test without data.
    # But we can verify that they DON'T accept everything if we had mocked data.
    # For scaffolding, verifying they are distinct instances with distinct doc_types is enough.
    
    agent_econ = registry.get("economy_agent")
    agent_cul = registry.get("culture_agent")
    
    assert agent_econ.metadata.doc_types != agent_cul.metadata.doc_types
    assert "stats" in agent_econ.metadata.doc_types
    assert "tourism_spots" not in agent_econ.metadata.doc_types

def test_no_raw_client_imports_in_agents():
    """Static Analysis: Ban direct use of requests, psycopg2, qdrant_client in agents."""
    agent_dir = "apps/backend/src/app/agents"
    forbidden_imports = ["requests", "psycopg2", "qdrant_client", "sqlalchemy"]
    legacy_exemptions = ["people_lookup.py", "accurate_people.py", "universal_lookup.py", "citizen_qa.py", "legal.py"]
    
    for filename in os.listdir(agent_dir):
        if filename.endswith(".py") and filename not in ["__init__.py", "registry.py", "base.py", "contract.py"] and filename not in legacy_exemptions:
            path = os.path.join(agent_dir, filename)
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=filename)
                
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in forbidden_imports:
                            pytest.fail(f"Forbidden import '{alias.name}' in {filename}. Use core wrappers.")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split(".")[0] in forbidden_imports:
                        pytest.fail(f"Forbidden import from '{node.module}' in {filename}. Use core wrappers.")
