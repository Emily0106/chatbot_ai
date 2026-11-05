from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.chat import _chat_endpoint_impl
from app.schemas.chat import ChatMeta, ChatRequest, ChatResponse


@pytest.fixture
def mock_claims():
    claims = MagicMock()
    claims.tenant_id = "tenant_a"
    claims.subject = "user_a"
    claims.roles = ["user"]
    return claims


def _no_evidence_response(msg: str = "Không tìm thấy thông tin phù hợp. (no_hits)") -> ChatResponse:
    resp = ChatResponse(answer=msg, meta=ChatMeta(debug_info={}), citations=[])
    setattr(resp.meta, "is_refusal", True)
    setattr(resp.meta, "refusal", {"code": "NO_EVIDENCE", "message": msg})
    return resp


@pytest.mark.asyncio
async def test_smalltalk_llm_only_skips_agent_process_and_memory(mock_claims):
    payload = ChatRequest(agent_id="legal", message="xin chào", stream=False)

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.security.context.build_trusted_context") as mock_ctx, \
         patch("app.api.routes.chat.achat", new=AsyncMock(return_value="Xin chào!")) as mock_achat, \
         patch("app.core.policy.manager.PolicyManager.enforce_context"), \
         patch("app.core.memory.session_store.get_session_store", side_effect=AssertionError("memory should not run")):

        mock_ctx.return_value = MagicMock(security_level=1)
        mock_agent = AsyncMock()
        mock_get_agent.return_value = mock_agent

        response = await _chat_endpoint_impl(
            payload=payload,
            request=MagicMock(),
            db=MagicMock(),
            claims=mock_claims,
            effective_security_level=1,
            trace_id="trace-smalltalk",
        )

    assert response.answer
    assert response.citations == []
    assert response.meta.route_mode == "llm_only"
    assert response.meta.route_reason == "smalltalk"
    assert response.meta.evidence_status == "ok"
    assert response.meta.citations_len == 0
    assert "llm_only" in response.meta.used_tools
    assert mock_agent.process.await_count == 0
    assert mock_achat.await_count == 1


@pytest.mark.asyncio
async def test_meta_chat_llm_only_skips_agent_process_and_memory(mock_claims):
    payload = ChatRequest(agent_id="legal", message="bạn là agent gì", stream=False)

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.security.context.build_trusted_context") as mock_ctx, \
         patch("app.api.routes.chat.achat", new=AsyncMock(return_value="Tôi là legal agent.")) as mock_achat, \
         patch("app.core.policy.manager.PolicyManager.enforce_context"), \
         patch("app.core.memory.session_store.get_session_store", side_effect=AssertionError("memory should not run")):

        mock_ctx.return_value = MagicMock(security_level=1)
        mock_agent = AsyncMock()
        mock_get_agent.return_value = mock_agent

        response = await _chat_endpoint_impl(
            payload=payload,
            request=MagicMock(),
            db=MagicMock(),
            claims=mock_claims,
            effective_security_level=1,
            trace_id="trace-meta-chat",
        )

    assert response.answer
    assert response.citations == []
    assert response.meta.route_mode == "llm_only"
    assert response.meta.route_reason == "agent_intro"
    assert response.meta.evidence_status == "ok"
    assert response.meta.citations_len == 0
    assert "llm_only" in response.meta.used_tools
    assert mock_agent.process.await_count == 0
    assert mock_achat.await_count == 1


@pytest.mark.asyncio
async def test_evidence_prompt_routes_to_rag_and_calls_agent(mock_claims):
    payload = ChatRequest(agent_id="legal", message="Điều 5 quy định gì?", stream=False)
    response_from_agent = ChatResponse(answer="Test answer", meta=ChatMeta(debug_info={}), citations=[])

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.security.context.build_trusted_context") as mock_ctx, \
         patch("app.core.memory.session_store.get_session_store") as mock_store_factory, \
         patch("app.core.memory.linker.choose_best_case", return_value=(None, 0.0, "")), \
         patch("app.core.prompts.templates.build_retrieval_context", return_value="query with memory"), \
         patch("app.core.policy.manager.PolicyManager.enforce_context"):

        mock_ctx.return_value = MagicMock(security_level=1)
        mock_agent = AsyncMock()
        mock_agent.process = AsyncMock(return_value=response_from_agent)
        mock_get_agent.return_value = mock_agent

        mock_store = AsyncMock()
        mock_store.get_cases = AsyncMock(return_value=[])
        mock_store.add_case = AsyncMock(return_value=None)
        mock_store_factory.return_value = mock_store

        response = await _chat_endpoint_impl(
            payload=payload,
            request=MagicMock(),
            db=MagicMock(),
            claims=mock_claims,
            effective_security_level=1,
            trace_id="trace-rag",
        )

    assert response.meta.route_mode.startswith("rag_")
    assert response.meta.route_reason
    assert response.meta.evidence_status in ("ok", "low_evidence")
    assert response.meta.citations_len == 0
    assert mock_agent.process.await_count == 1
    assert mock_agent.process.call_args[0][1] == "query with memory"


@pytest.mark.asyncio
async def test_evidence_prompt_routes_to_rag_via_facade_entrypoint(mock_claims):
    payload = ChatRequest(agent_id="legal", message="Điều 5 quy định gì?", stream=False)
    response_from_facade = ChatResponse(answer="Facade answer", meta=ChatMeta(debug_info={}), citations=[])

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.security.context.build_trusted_context") as mock_ctx, \
         patch("app.api.routes.chat.execute_agent_query", new=AsyncMock(return_value=response_from_facade)) as mock_execute, \
         patch("app.core.memory.session_store.get_session_store") as mock_store_factory, \
         patch("app.core.memory.linker.choose_best_case", return_value=(None, 0.0, "")), \
         patch("app.core.prompts.templates.build_retrieval_context", return_value="query with memory"), \
         patch("app.core.policy.manager.PolicyManager.enforce_context"):

        mock_ctx.return_value = MagicMock(security_level=1)
        mock_agent = AsyncMock()
        mock_agent.process = AsyncMock(side_effect=AssertionError("chat route must not call agent.process directly"))
        mock_get_agent.return_value = mock_agent

        mock_store = AsyncMock()
        mock_store.get_cases = AsyncMock(return_value=[])
        mock_store.add_case = AsyncMock(return_value=None)
        mock_store_factory.return_value = mock_store

        response = await _chat_endpoint_impl(
            payload=payload,
            request=MagicMock(),
            db=MagicMock(),
            claims=mock_claims,
            effective_security_level=1,
            trace_id="trace-rag-facade-entry",
        )

    assert response.answer == "Facade answer"
    assert response.meta.route_mode.startswith("rag_")
    assert mock_execute.await_count == 1
    assert mock_execute.call_args.kwargs["query"] == "query with memory"
    assert mock_agent.process.await_count == 0


@pytest.mark.asyncio
async def test_general_explain_no_evidence_uses_ungrounded_llm_fallback(mock_claims):
    payload = ChatRequest(agent_id="legal", message="giải thích khái niệm quyền tác giả", stream=False)

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.security.context.build_trusted_context") as mock_ctx, \
         patch("app.api.routes.chat.achat", new=AsyncMock(return_value="Quyền tác giả là quyền của tác giả đối với tác phẩm.")) as mock_achat, \
         patch("app.core.memory.session_store.get_session_store") as mock_store_factory, \
         patch("app.core.memory.linker.choose_best_case", return_value=(None, 0.0, "")), \
         patch("app.core.prompts.templates.build_retrieval_context", return_value="query with memory"), \
         patch("app.core.policy.manager.PolicyManager.enforce_context"):

        mock_ctx.return_value = MagicMock(security_level=1)
        mock_agent = AsyncMock()
        mock_agent.process = AsyncMock(return_value=_no_evidence_response())
        mock_get_agent.return_value = mock_agent

        mock_store = AsyncMock()
        mock_store.get_cases = AsyncMock(return_value=[])
        mock_store.add_case = AsyncMock(return_value=None)
        mock_store_factory.return_value = mock_store

        response = await _chat_endpoint_impl(
            payload=payload,
            request=MagicMock(),
            db=MagicMock(),
            claims=mock_claims,
            effective_security_level=1,
            trace_id="trace-fallback",
        )

    assert response.meta.route_mode == "llm_only"
    assert response.meta.route_reason == "no_evidence_llm_fallback"
    assert getattr(response.meta, "ungrounded", False) is True
    assert getattr(response.meta, "fallback_reason", "") == "no_evidence_llm_fallback"
    assert str(getattr(response.meta, "original_route_mode", "")).startswith("rag_")
    assert response.citations == []
    assert "kiến thức chung" in response.answer.lower()
    assert response.meta.evidence_status == "no_hits"
    assert response.meta.citations_len == 0
    assert mock_agent.process.await_count == 1
    assert mock_achat.await_count == 1


@pytest.mark.asyncio
async def test_evidence_required_no_evidence_stays_refusal_with_next_steps(mock_claims):
    payload = ChatRequest(
        agent_id="legal",
        message="cung cấp thông tin về luật sở hữu trí tuệ mới nhất",
        stream=False,
    )

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.api.routes.chat._answer_ungrounded_fallback", new=AsyncMock(return_value=ChatResponse(answer="fallback", citations=[], meta=ChatMeta()))) as mock_fallback, \
         patch("app.security.context.build_trusted_context") as mock_ctx, \
         patch("app.core.memory.session_store.get_session_store") as mock_store_factory, \
         patch("app.core.memory.linker.choose_best_case", return_value=(None, 0.0, "")), \
         patch("app.core.prompts.templates.build_retrieval_context", return_value="query with memory"), \
         patch("app.core.policy.manager.PolicyManager.enforce_context"):

        mock_ctx.return_value = MagicMock(security_level=1)
        mock_agent = AsyncMock()
        mock_agent.process = AsyncMock(return_value=_no_evidence_response())
        mock_get_agent.return_value = mock_agent

        mock_store = AsyncMock()
        mock_store.get_cases = AsyncMock(return_value=[])
        mock_store.add_case = AsyncMock(return_value=None)
        mock_store_factory.return_value = mock_store

        response = await _chat_endpoint_impl(
            payload=payload,
            request=MagicMock(),
            db=MagicMock(),
            claims=mock_claims,
            effective_security_level=1,
            trace_id="trace-evidence-required",
        )

    assert getattr(response.meta, "is_refusal", False) is True
    assert response.meta.refusal["code"] == "NO_EVIDENCE"
    assert "Gợi ý tiếp theo:" in response.answer
    assert response.meta.evidence_status == "no_hits"
    assert response.meta.citations_len == 0
    assert mock_fallback.await_count == 0


@pytest.mark.asyncio
async def test_restricted_context_disables_no_evidence_fallback(mock_claims):
    payload = ChatRequest(agent_id="legal", message="giải thích khái niệm quyền tác giả", stream=False)

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.api.routes.chat._answer_ungrounded_fallback", new=AsyncMock(return_value=ChatResponse(answer="fallback", citations=[], meta=ChatMeta()))) as mock_fallback, \
         patch("app.security.context.build_trusted_context") as mock_ctx, \
         patch("app.core.memory.session_store.get_session_store") as mock_store_factory, \
         patch("app.core.memory.linker.choose_best_case", return_value=(None, 0.0, "")), \
         patch("app.core.prompts.templates.build_retrieval_context", return_value="query with memory"), \
         patch("app.core.policy.manager.PolicyManager.enforce_context"):

        mock_ctx.return_value = MagicMock(security_level=2)
        mock_agent = AsyncMock()
        mock_agent.process = AsyncMock(return_value=_no_evidence_response())
        mock_get_agent.return_value = mock_agent

        mock_store = AsyncMock()
        mock_store.get_cases = AsyncMock(return_value=[])
        mock_store.add_case = AsyncMock(return_value=None)
        mock_store_factory.return_value = mock_store

        response = await _chat_endpoint_impl(
            payload=payload,
            request=MagicMock(),
            db=MagicMock(),
            claims=mock_claims,
            effective_security_level=2,
            trace_id="trace-restricted-no-fallback",
        )

    assert getattr(response.meta, "is_refusal", False) is True
    assert response.meta.refusal["code"] == "NO_EVIDENCE"
    assert "Gợi ý tiếp theo:" in response.answer
    assert response.meta.evidence_status == "no_hits"
    assert response.meta.citations_len == 0
    assert mock_fallback.await_count == 0


@pytest.mark.asyncio
async def test_sql_candidate_without_permission_returns_clear_refusal(mock_claims):
    payload = ChatRequest(agent_id="legal", message="bao nhiêu văn bản hiện hành", stream=False)

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.security.context.build_trusted_context") as mock_ctx, \
         patch("app.core.policy.manager.PolicyManager.enforce_context"), \
         patch("app.core.memory.session_store.get_session_store", side_effect=AssertionError("memory should not run")):

        mock_ctx.return_value = MagicMock(security_level=1)
        mock_agent = AsyncMock()
        mock_get_agent.return_value = mock_agent

        response = await _chat_endpoint_impl(
            payload=payload,
            request=MagicMock(),
            db=MagicMock(),
            claims=mock_claims,
            effective_security_level=1,
            trace_id="trace-sql-deny",
        )

    assert response.meta.route_mode == "sql_candidate"
    assert response.meta.route_reason == "requires_role"
    assert response.meta.refusal["code"] == "INSUFFICIENT_CLEARANCE"
    assert response.meta.evidence_status == "refused"
    assert response.meta.citations_len == 0
    assert mock_agent.process.await_count == 0


@pytest.mark.asyncio
async def test_sql_candidate_with_permission_executes_sql_lane(mock_claims):
    payload = ChatRequest(agent_id="legal", message="bao nhiêu văn bản public thuộc law", stream=False)
    mock_claims.roles = ["report"]

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.security.context.build_trusted_context") as mock_ctx, \
         patch("app.core.policy.manager.PolicyManager.enforce_context"), \
         patch("app.api.routes.chat.SQLExecutor") as mock_executor_cls, \
         patch("app.core.memory.session_store.get_session_store", side_effect=AssertionError("memory should not run")):

        mock_ctx.return_value = MagicMock(security_level=1)
        mock_agent = AsyncMock()
        mock_get_agent.return_value = mock_agent

        mock_executor = AsyncMock()
        mock_executor.execute_safe = AsyncMock(return_value={"data": [{"total_docs": 7}], "meta": {"row_count": 1}})
        mock_executor_cls.return_value = mock_executor

        response = await _chat_endpoint_impl(
            payload=payload,
            request=MagicMock(),
            db=MagicMock(),
            claims=mock_claims,
            effective_security_level=1,
            trace_id="trace-sql-exec",
        )

    assert response.meta.route_mode == "sql_execute"
    assert response.meta.route_reason == "aggregate_intent_sql_execute"
    assert "sql_execute_count_documents" in response.meta.used_tools
    assert "7" in response.answer
    assert response.meta.evidence_status == "ok"
    assert response.meta.citations_len == 0
    assert mock_agent.process.await_count == 0


@pytest.mark.asyncio
async def test_how_to_routes_to_llm_only_and_skips_agent(mock_claims):
    payload = ChatRequest(agent_id="legal", message="Hướng dẫn tôi cách ingest tài liệu vào hệ thống", stream=False)

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent, \
         patch("app.security.context.build_trusted_context") as mock_ctx, \
         patch("app.api.routes.chat.achat", new=AsyncMock(return_value="Bạn có thể vào /ops rồi bấm Reindex.")) as mock_achat, \
         patch("app.core.policy.manager.PolicyManager.enforce_context"), \
         patch("app.core.memory.session_store.get_session_store", side_effect=AssertionError("memory should not run")):

        mock_ctx.return_value = MagicMock(security_level=1)
        mock_agent = AsyncMock()
        mock_get_agent.return_value = mock_agent

        response = await _chat_endpoint_impl(
            payload=payload,
            request=MagicMock(),
            db=MagicMock(),
            claims=mock_claims,
            effective_security_level=1,
            trace_id="trace-how-to",
        )

    assert response.meta.route_mode == "llm_only"
    assert response.meta.route_reason == "how_to"
    assert response.meta.evidence_status == "ok"
    assert response.meta.citations_len == 0
    assert mock_agent.process.await_count == 0
    assert mock_achat.await_count == 1
