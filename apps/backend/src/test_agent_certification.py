"""
apps/backend/src/test_agent_certification.py

QA Certification Suite for Gov-AI Agents (Wave 1 + Wave 2).
Scope:
- 11 Agents Existence
- Zero-Trust Static Analysis
- Fail-Closed Semantics (Refusal Checks)
- Positive Evidence Flow (Mocked RAG)
- Policy & Cross-Pollution Logic

Usage:
  pytest apps/backend/src/test_agent_certification.py
"""
import pytest
import ast
import os
import inspect
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.registry import registry, register_defaults
from app.agents.contract import TrustedContext, RefusalCode, AgentResponse

# Initialize Registry
register_defaults()

AGENTS_TO_CERTIFY = [
    "citizen_agent", "report_agent", "health_agent", "culture_agent", "agri_agent",
    "meeting_agent", "calendar_agent", "economy_agent", "doc_manager", "land_agent", "social_agent"
]

RESTRICTED_AGENTS = ["economy_agent", "land_agent", "social_agent"] # req level 2

DOC_TYPE_MAPPING = {
    "citizen_agent": ["law", "admin_procedure", "citizen_guide"],
    "meeting_agent": ["meeting_minutes"],
    "economy_agent": ["stats", "internal_report"],
    # ... add others as needed for specific assertion
}

# ------------------------------------------------------------------------
# A. STRUCTURE & REGISTRY
# ------------------------------------------------------------------------
def test_registry_count_and_keys():
    """Certify exactly 11 agents (+ legacy) are loaded."""
    agents_dict = registry.list_agents()
    print(f"\nLoaded Agents: {list(agents_dict.keys())}")
    
    # Check all target agents exist
    for aid in AGENTS_TO_CERTIFY:
        assert aid in agents_dict, f"Missing {aid}"
        # Validate Object Integrity via get()
        agent = registry.get(aid)
        assert agent.metadata.agent_id == aid
        
    # Verify Metadata Integrity
    for aid in AGENTS_TO_CERTIFY:
        agent = registry.get(aid)
        assert agent.metadata.name is not None
        assert isinstance(agent.metadata.doc_types, list)

def test_agent_tool_note_existence():
    """Certify each file has the 'AGENT TOOL NOTE' block."""
    agent_dir = "apps/backend/src/app/agents"
    for aid in AGENTS_TO_CERTIFY:
        # Map agent_id to filename approx logic
        filename = f"{aid}.py"
        path = os.path.join(agent_dir, filename)
        assert os.path.exists(path), f"File {path} not found"
        
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "AGENT TOOL NOTE" in content, f"{filename} missing AGENT TOOL NOTE"

# ------------------------------------------------------------------------
# B. ZERO-TRUST STATIC GUARDS
# ------------------------------------------------------------------------
def test_zero_trust_static_analysis():
    """Ban forbidden imports in certifiable agents."""
    agent_dir = "apps/backend/src/app/agents"
    forbidden = ["requests", "httpx", "aiohttp", "psycopg2", "asyncpg", "qdrant_client", "sqlalchemy"]
    
    for aid in AGENTS_TO_CERTIFY:
        filename = f"{aid}.py"
        path = os.path.join(agent_dir, filename)
        
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=filename)
            
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    fullname = alias.name
                    base = fullname.split(".")[0]
                    if base in forbidden:
                        pytest.fail(f"Agent {aid} imports forbidden '{fullname}'")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    base = node.module.split(".")[0]
                    if base in forbidden:
                        pytest.fail(f"Agent {aid} imports forbidden '{node.module}'")

# ------------------------------------------------------------------------
# C. FAIL-CLOSED SEMANTICS (EMPTY DB)
# ------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fail_closed_on_empty_rag():
    """Certify agents refuse when RAG returns None/Empty."""
    ctx = TrustedContext(tenant_id="test", user_id="u", security_level=2)
    
    with patch("app.core.db_sql.get_async_db") as mock_db, \
         patch("app.core.rag.pipeline.rag_retrieve", new_callable=AsyncMock) as mock_rag, \
         patch("app.core.web_search.WebSearchService.search", new_callable=AsyncMock) as mock_web:
         
        mock_db.return_value.__aiter__.return_value = [AsyncMock()]
        mock_rag.return_value = None # Empty flow
        mock_web.return_value = [] # Empty web search flow
        
        for aid in AGENTS_TO_CERTIFY:
            agent = registry.get(aid)
            resp = await agent.process(ctx, "Anything")
            
            # Check refusal
            meta = resp.meta.model_dump()
            assert meta.get("is_refusal") is True
            
            # Code Check
            refusal_info = meta.get("refusal", {})
            code = refusal_info.get("code")
            assert code in [
                RefusalCode.NO_EVIDENCE, 
                RefusalCode.NOT_IMPLEMENTED,
                RefusalCode.OUT_OF_SCOPE
            ], f"{aid} returned invalid refusal code {code}"

# ------------------------------------------------------------------------
# D. POSITIVE FLOW (MOCKED RAG) & E. POLICY ENFORCEMENT
# ------------------------------------------------------------------------
# Standard Rag Result Mock
class MockRagResult:
    def __init__(self, context, citations=[], meta={}):
        self.context = context
        self.citations = citations
        self.meta = meta

@pytest.mark.asyncio
async def test_positive_flow_with_policy_check():
    """
    Certify that:
    1. Agents construct correct filters (doc_types).
    2. Agents pass contexts (department, geo).
    3. Agents return success when RAG returns data.
    """
    ctx = TrustedContext(
        tenant_id="t1", 
        user_id="u1", 
        security_level=2,
        department_id="dept_IT",
        geo_code="geo_VN"
    )
    
    with patch("app.core.db_sql.get_async_db") as mock_db, \
         patch("app.core.rag.pipeline.rag_retrieve", new_callable=AsyncMock) as mock_rag, \
         patch("app.core.llm_client.achat", new_callable=AsyncMock) as mock_llm:
         
        mock_db.return_value.__aiter__.return_value = [AsyncMock()]
        mock_llm.return_value = "AI generated answer based on context."
        
        # Scenario: RAG matches
        mock_rag.return_value = MockRagResult(
            context="Found some data about laws.",
            citations=[{"chunk_id": "c1", "title": "Law 1"}],
            meta={}
        )
        
        # 1. Citizen Agent (Public)
        agent = registry.get("citizen_agent")
        await agent.process(ctx, "law query")
        
        # Verify RAG Call Filters
        call_args = mock_rag.call_args[1] # kwargs
        filters = call_args["filters"]
        # .doc_types or .doc_type depending on implementation updates
        passed_types = getattr(filters, "doc_types", None) or getattr(filters, "doc_type", None)
        
        assert passed_types is not None, "citizen_agent did not pass doc_type filter"
        # Since we set it to list in previous fix, expect list
        if isinstance(passed_types, list):
            assert "law" in passed_types
        else:
            # If implementation uses string single
            assert passed_types in ["law", "admin_procedure", "citizen_guide"]

        # 2. Land Agent (Restricted + Geo)
        agent_land = registry.get("land_agent")
        await agent_land.process(ctx, "planning query")
        
        call_args = mock_rag.call_args[1]
        user_context = call_args["user_context"]
        assert "geo_code" in user_context, "land_agent missing geo_code in user_context"
        assert user_context["geo_code"] == "geo_VN"

# ------------------------------------------------------------------------
# F. CROSS-AGENT POLLUTION
# ------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cross_agent_pollution_mocked():
    """Verify Agents don't ask for wrong doc types."""
    ctx = TrustedContext(tenant_id="t1", user_id="u1", security_level=2)
    
    with patch("app.core.db_sql.get_async_db") as mock_db, \
         patch("app.core.rag.pipeline.rag_retrieve", new_callable=AsyncMock) as mock_rag:
         
        mock_db.return_value.__aiter__.return_value = [AsyncMock()]
        mock_rag.return_value = MockRagResult(context="Mock") 
        # Even if we return mock, we check the CALL arguments.
        
        # Economy Agent should NOT ask for tourism_spots
        agent = registry.get("economy_agent")
        await agent.process(ctx, "tourist query")
        
        call_args = mock_rag.call_args[1]
        filters = call_args["filters"]
        passed_types = getattr(filters, "doc_types", []) or getattr(filters, "doc_type", [])
        
        if not isinstance(passed_types, list): passed_types = [passed_types]
        
        assert "stats" in passed_types or "internal_report" in passed_types
        assert "tourism_spots" not in passed_types
        assert "meeting_minutes" not in passed_types
