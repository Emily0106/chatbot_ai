from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.chat import chat_stream_gen
from app.schemas.chat import ChatMeta, ChatRequest, ChatResponse


def _no_evidence_response(msg: str = "Không tìm thấy thông tin phù hợp. (no_hits)") -> ChatResponse:
    resp = ChatResponse(answer=msg, meta=ChatMeta(debug_info={}), citations=[])
    setattr(resp.meta, "is_refusal", True)
    setattr(resp.meta, "refusal", {"code": "NO_EVIDENCE", "message": msg})
    return resp


def _parse_sse_payload(chunk: str) -> tuple[str | None, dict]:
    if not isinstance(chunk, str) or "event:" not in chunk or "data:" not in chunk:
        return None, {}
    lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
    event = None
    data = {}
    for ln in lines:
        if ln.startswith("event:"):
            event = ln.split(":", 1)[1].strip()
        if ln.startswith("data:"):
            raw = ln.split(":", 1)[1].strip()
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
    return event, data


@pytest.fixture
def mock_claims():
    claims = MagicMock()
    claims.tenant_id = "tenant_a"
    claims.subject = "user_a"
    claims.roles = ["user"]
    return claims


@pytest.mark.asyncio
async def test_stream_smalltalk_routes_llm_only(mock_claims):
    payload = ChatRequest(agent_id="legal", message="xin chào", stream=True)
    mock_request = MagicMock()
    mock_db = AsyncMock()

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.core.rate_limit.rate_limiter") as mock_rl, \
         patch("app.security.context.build_trusted_context", return_value=MagicMock(security_level=1)), \
         patch("app.core.policy.manager.PolicyManager.enforce_context"), \
         patch("app.api.routes.chat.achat", new=AsyncMock(return_value="Xin chào!")), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent:
        mock_rl.enter_stream = AsyncMock(return_value=MagicMock(allowed=True))
        mock_rl.exit_stream = AsyncMock()
        mock_agent = MagicMock()
        mock_agent.process_stream = AsyncMock()
        mock_get_agent.return_value = mock_agent

        items = [i async for i in chat_stream_gen(payload, mock_request, mock_db, mock_claims, 1, "trace-stream-1")]

    parsed = [_parse_sse_payload(i) for i in items]
    meta_payloads = [d for ev, d in parsed if ev == "meta"]
    assert any(d.get("route_mode") == "llm_only" for d in meta_payloads)
    assert any("event: token" in i and "Xin chào!" in i for i in items)
    assert any("event: done" in i for i in items)
    assert mock_agent.process_stream.call_count == 0


@pytest.mark.asyncio
async def test_stream_evidence_required_no_hits_stays_refusal(mock_claims):
    payload = ChatRequest(agent_id="legal", message="Điều 5 quy định gì?", stream=True)
    mock_request = MagicMock()
    mock_db = AsyncMock()

    async def _stream_refusal(_ctx, _query):
        yield _no_evidence_response()

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.core.rate_limit.rate_limiter") as mock_rl, \
         patch("app.security.context.build_trusted_context", return_value=MagicMock(security_level=1)), \
         patch("app.core.policy.manager.PolicyManager.enforce_context"), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent:
        mock_rl.enter_stream = AsyncMock(return_value=MagicMock(allowed=True))
        mock_rl.exit_stream = AsyncMock()
        mock_agent = MagicMock()
        mock_agent.process_stream = _stream_refusal
        mock_get_agent.return_value = mock_agent

        items = [i async for i in chat_stream_gen(payload, mock_request, mock_db, mock_claims, 1, "trace-stream-2")]

    assert any("event: done" in i for i in items)
    assert any("NO_EVIDENCE" in i for i in items)
    assert not any("no_evidence_llm_fallback" in i for i in items)


@pytest.mark.asyncio
async def test_stream_general_explain_no_hits_uses_ungrounded_fallback(mock_claims):
    payload = ChatRequest(agent_id="legal", message="giải thích khái niệm quyền tác giả", stream=True)
    mock_request = MagicMock()
    mock_db = AsyncMock()

    async def _stream_refusal(_ctx, _query):
        yield _no_evidence_response()

    with patch("app.api.routes.chat.audit_event"), \
         patch("app.core.rate_limit.rate_limiter") as mock_rl, \
         patch("app.security.context.build_trusted_context", return_value=MagicMock(security_level=1)), \
         patch("app.core.policy.manager.PolicyManager.enforce_context"), \
         patch("app.api.routes.chat.achat", new=AsyncMock(return_value="Quyền tác giả là quyền của tác giả.")), \
         patch("app.api.routes.chat.get_agent") as mock_get_agent:
        mock_rl.enter_stream = AsyncMock(return_value=MagicMock(allowed=True))
        mock_rl.exit_stream = AsyncMock()
        mock_agent = MagicMock()
        mock_agent.process_stream = _stream_refusal
        mock_get_agent.return_value = mock_agent

        items = [i async for i in chat_stream_gen(payload, mock_request, mock_db, mock_claims, 1, "trace-stream-3")]

    assert any("event: token" in i for i in items)
    assert any("kiến thức chung" in i for i in items)
    assert any("no_evidence_llm_fallback" in i for i in items)
