"""PR-10: Streaming Audit Parity Tests.

Verify that the streaming handler emits audit_event("rag.access")
with the same QE fields as the blocking path, and never leaks raw query.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.core.audit.qe_meta import qe_audit_defaults, qe_audit_from_meta


# ─────────────────────────────────────────────────────────────────
# Unit tests for the centralized helper (qe_meta.py)
# ─────────────────────────────────────────────────────────────────

class TestQeAuditDefaults:
    def test_returns_safe_defaults(self):
        d = qe_audit_defaults()
        assert d["expansion_applied"] is False
        assert d["variants_count"] == 1
        assert d["variant_sources"] == {"ORIGINAL": 1}
        assert d["llm_used"] is False
        assert d["contains_pii"] is False

    def test_returns_fresh_copy(self):
        a = qe_audit_defaults()
        b = qe_audit_defaults()
        a["expansion_applied"] = True
        assert b["expansion_applied"] is False  # not mutated


class TestQeAuditFromMeta:
    def test_none_returns_defaults(self):
        result = qe_audit_from_meta(None)
        assert result == qe_audit_defaults()

    def test_meta_without_qe_attr_returns_defaults(self):
        meta = MagicMock(spec=[])  # no attributes
        result = qe_audit_from_meta(meta)
        assert result == qe_audit_defaults()

    def test_meta_with_qe_dict(self):
        meta = MagicMock()
        meta.query_expansion_audit = {
            "expansion_applied": True,
            "variants_count": 3,
            "variant_sources": {"ORIGINAL": 1, "LEXICON": 2},
        }
        result = qe_audit_from_meta(meta)
        assert result["expansion_applied"] is True
        assert result["variants_count"] == 3
        # Missing keys filled with defaults
        assert result["llm_used"] is False
        assert result["contains_pii"] is False

    def test_strips_forbidden_keys(self):
        """Ensure raw query fields are NEVER passed through."""
        meta = MagicMock()
        meta.query_expansion_audit = {
            "expansion_applied": True,
            "original_query": "THIS SHOULD BE STRIPPED",
            "normalized_query": "THIS TOO",
            "redacted_query": "AND THIS",
            "raw_query": "ALSO THIS",
            "query": "NOPE",
        }
        result = qe_audit_from_meta(meta)
        assert "original_query" not in result
        assert "normalized_query" not in result
        assert "redacted_query" not in result
        assert "raw_query" not in result
        assert "query" not in result
        # Still has defaults
        assert result["expansion_applied"] is True

    def test_dict_meta_access(self):
        meta = {"query_expansion_audit": {"expansion_applied": True, "variants_count": 2}}
        result = qe_audit_from_meta(meta)
        assert result["expansion_applied"] is True
        assert result["variants_count"] == 2


# ─────────────────────────────────────────────────────────────────
# Integration: streaming handler emits rag.access
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_streaming_emits_rag_access_with_qe_defaults():
    """Verify streaming finally block calls audit_event('rag.access') with QE defaults."""
    from app.api.routes.chat import chat_stream_gen
    from app.schemas.chat import ChatRequest

    mock_claims = MagicMock()
    mock_claims.tenant_id = "t1"
    mock_claims.subject = "user1"
    mock_claims.roles = ["user"]

    payload = ChatRequest(message="test query", agent_id="test-agent")
    mock_request = MagicMock()
    mock_db = AsyncMock()

    with patch("app.api.routes.chat.audit_event") as mock_audit, \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.core.rate_limit.rate_limiter") as mock_rl:

        # Rate limiter allows
        mock_rl.enter_stream = AsyncMock(return_value=MagicMock(allowed=True))
        mock_rl.exit_stream = AsyncMock()

        # Agent yields one chunk then stops
        mock_agent = AsyncMock()

        async def fake_stream(ctx, msg):
            yield 'event: message\ndata: {"text":"hello"}\n\n'

        mock_agent.process_stream = fake_stream
        mock_get_agent.return_value = mock_agent

        with patch("app.security.context.build_trusted_context", return_value=MagicMock(security_level=1)):
            # Exhaust the generator
            chunks = []
            async for chunk in chat_stream_gen(payload, mock_request, mock_db, mock_claims, 1, "trace1"):
                chunks.append(chunk)

    # Find rag.access call
    rag_calls = [c for c in mock_audit.call_args_list if c[0][0] == "rag.access"]
    assert len(rag_calls) >= 1, f"Expected rag.access call, got: {[c[0][0] for c in mock_audit.call_args_list]}"

    kwargs = rag_calls[0][1]
    assert kwargs["stream"] is True
    assert kwargs["expansion_applied"] is False  # defaults
    assert kwargs["variants_count"] == 1
    assert kwargs["variant_sources"] == {"ORIGINAL": 1}

    # No raw query leakage
    assert "original_query" not in kwargs
    assert "normalized_query" not in kwargs
    assert "redacted_query" not in kwargs


@pytest.mark.asyncio
async def test_streaming_rag_access_fires_even_on_error():
    """Verify rag.access still fires in finally if agent raises."""
    from app.api.routes.chat import chat_stream_gen
    from app.schemas.chat import ChatRequest

    mock_claims = MagicMock()
    mock_claims.tenant_id = "t1"
    mock_claims.subject = "user1"
    mock_claims.roles = ["user"]

    payload = ChatRequest(message="test query", agent_id="test-agent")

    with patch("app.api.routes.chat.audit_event") as mock_audit, \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.core.rate_limit.rate_limiter") as mock_rl:

        mock_rl.enter_stream = AsyncMock(return_value=MagicMock(allowed=True))
        mock_rl.exit_stream = AsyncMock()

        mock_agent = AsyncMock()

        async def failing_stream(ctx, msg):
            yield 'event: message\ndata: {"text":"partial"}\n\n'
            raise RuntimeError("Simulated agent crash")

        mock_agent.process_stream = failing_stream
        mock_get_agent.return_value = mock_agent

        with patch("app.security.context.build_trusted_context", return_value=MagicMock(security_level=1)):
            chunks = []
            async for chunk in chat_stream_gen(payload, MagicMock(), AsyncMock(), mock_claims, 1, "trace2"):
                chunks.append(chunk)

    # rag.access should still fire despite exception
    rag_calls = [c for c in mock_audit.call_args_list if c[0][0] == "rag.access"]
    assert len(rag_calls) >= 1

    kwargs = rag_calls[0][1]
    assert kwargs["stream"] is True
    assert kwargs["expansion_applied"] is False  # safe defaults
