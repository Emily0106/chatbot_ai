import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.api.routes.chat import _chat_endpoint_impl
from app.schemas.chat import ChatRequest

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def mock_claims():
    claims = MagicMock()
    claims.tenant_id = "test-tenant"
    claims.subject = "user1"
    claims.roles = ["user"]
    return claims

@pytest.mark.asyncio
async def test_audit_enrichment_expansion_disabled(mock_db, mock_claims):
    """Verify safe defaults when expansion is disabled."""
    with patch("app.api.routes.chat.audit_event") as mock_audit, \
         patch("app.api.routes.chat.get_agent") as mock_get_agent:
        
        # Setup mock agent to return a response with citations
        mock_agent = AsyncMock()
        
        from app.schemas.chat import ChatResponse, ChatMeta, Citation
        mock_response = ChatResponse(
            answer="Test answer",
            meta=ChatMeta(
                agent_id="test-agent",
                timing={}
            ),
            citations=[Citation(chunk_id="chunk1", document_id="doc1")]
        )
        
        mock_agent.process.return_value = mock_response
        mock_get_agent.return_value = mock_agent

        request = ChatRequest(message="Test query", agent_id="test-agent")
        
        # Mock Context Builder
        with patch("app.security.context.build_trusted_context") as mock_ctx:
            mock_ctx.return_value = MagicMock(security_level=1)
            
            # Mock Memory Linker
            mock_store = AsyncMock()
            mock_store.get_cases.return_value = []
            with patch("app.core.memory.session_store.get_session_store", return_value=mock_store):
                with patch("app.core.memory.linker.choose_best_case", return_value=(None, 0, "")):
                    # Mock PolicyManager
                    with patch("app.core.policy.manager.PolicyManager.enforce_context"):
                        with patch("app.api.routes.chat.validate_citations", return_value=(True, {})):
                            await _chat_endpoint_impl(
                                payload=request,
                                request=MagicMock(),
                                db=mock_db,
                                claims=mock_claims,
                                effective_security_level=1,
                                trace_id="trace1"
                            )

        # Find the rag.access call
        rag_access_calls = [call for call in mock_audit.call_args_list if call[0][0] == "rag.access"]
        assert len(rag_access_calls) == 1
        
        kwargs = rag_access_calls[0][1]
        
        # Assert safe defaults exist
        assert kwargs["expansion_applied"] is False
        assert kwargs["variants_count"] == 1
        assert kwargs["variant_sources"] == {"ORIGINAL": 1}
        assert kwargs["llm_used"] is False
        assert kwargs["contains_pii"] is False
        
        # Assert NO raw queries leaked
        assert "original_query" not in kwargs
        assert "normalized_query" not in kwargs
        assert "redacted_query" not in kwargs


@pytest.mark.asyncio
async def test_audit_enrichment_expansion_enabled(mock_db, mock_claims):
    """Verify correct metric packing when expansion is enabled."""
    with patch("app.api.routes.chat.audit_event") as mock_audit, \
         patch("app.api.routes.chat.get_agent") as mock_get_agent:
        
        mock_agent = AsyncMock()
        from app.schemas.chat import ChatResponse, ChatMeta, Citation
        mock_response = ChatResponse(
            answer="Test answer",
            meta=ChatMeta(
                agent_id="test-agent",
                timing={}
            ),
            citations=[Citation(chunk_id="chunk1", document_id="doc1")]
        )
        # Simulate RetrieveResult.debug["query_expansion_audit"]
        mock_response.meta.query_expansion_audit = {
            "expansion_applied": True,
            "variants_count": 3,
            "variant_sources": {"ORIGINAL": 1, "LEXICON": 2},
            "llm_used": False,
            "llm_timeout": False,
            "lexicon_version": "v1",
            "contains_pii": True,
            "injection_suspected": False,
            "is_code_query": False,
            "must_keep_tokens_count": 1
        }
        mock_agent.process.return_value = mock_response
        mock_get_agent.return_value = mock_agent

        request = ChatRequest(message="Test query", agent_id="test-agent")
        
        with patch("app.security.context.build_trusted_context") as mock_ctx:
            mock_ctx.return_value = MagicMock(security_level=1)
            mock_store = AsyncMock()
            mock_store.get_cases.return_value = []
            with patch("app.core.memory.session_store.get_session_store", return_value=mock_store):
                with patch("app.core.memory.linker.choose_best_case", return_value=(None, 0, "")):
                    # Mock PolicyManager
                    with patch("app.core.policy.manager.PolicyManager.enforce_context"):
                        with patch("app.api.routes.chat.validate_citations", return_value=(True, {})):
                            await _chat_endpoint_impl(
                                payload=request,
                                request=MagicMock(),
                                db=mock_db,
                                claims=mock_claims,
                                effective_security_level=1,
                                trace_id="trace1"
                            )

        rag_access_calls = [call for call in mock_audit.call_args_list if call[0][0] == "rag.access"]
        assert len(rag_access_calls) == 1
        
        kwargs = rag_access_calls[0][1]
        assert kwargs["expansion_applied"] is True
        assert kwargs["variants_count"] == 3
        assert kwargs["variant_sources"] == {"ORIGINAL": 1, "LEXICON": 2}
        assert kwargs["lexicon_version"] == "v1"
        assert kwargs["contains_pii"] is True
        
        # Assert NO raw queries leaked
        assert "original_query" not in kwargs
        assert "redacted_query" not in kwargs
