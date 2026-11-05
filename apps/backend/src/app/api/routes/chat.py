# app/api/routes/chat.py
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.db_sql import get_async_db

from app.core.rag.pipeline import rag_retrieve
from app.core.rag.evidence import EvidenceGate, GateDecision
from app.core.rag.router import HandoffRouter
from app.agents.registry import get_agent
from app.agents.prompt_builder import build_messages, get_agent_rag_config
from app.security.auth import require_auth, AuthClaims
from app.security import policy
from app.core.policy.errors import MissingContextError
from app.api.routes.auth_helper import authorize_chat_request

from app.core.llm_client import achat
from app.core.llm.citation_guard import (
    CitationGuardConfig,
    validate_citations,
    make_repair_messages,
)

from app.schemas.chat import ChatRequest, ChatResponse, Handoff, ChatMeta
from app.core.metrics import (
    CHAT_REQUESTS_TOTAL,
    CHAT_LATENCY_SECONDS,
    GATE_FAIL_TOTAL,
    STREAMS_ACTIVE,
    INFLIGHT_ACTIVE,
    STREAM_DISCONNECT_TOTAL,
)
from app.core.audit.audit import audit_event, compute_query_hash
from app.core.audit.qe_meta import qe_audit_from_meta
from app.core.facade import execute_agent_query
from app.core.route_policy import decide_route_mode
from app.core.sql.executor import SQLExecutor
from app.core.sql.types import SQLPolicy
from app.schemas.chat import Citation

logger = logging.getLogger(__name__)
router = APIRouter()


def _sha1(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8", errors="ignore")).hexdigest()


def _normalize_query(q: str) -> str:
    return " ".join((q or "").strip().split())


def _unwrap_rag_result(rag_res: Any) -> Tuple[str, List[Any], Dict[str, Any]]:
    """Support both dict-like and object-like rag results."""
    if isinstance(rag_res, dict):
        return (
            str(rag_res.get("context") or ""),
            list(rag_res.get("citations") or []),
            dict(rag_res.get("meta") or {}),
            getattr(rag_res, "gate_decision", None),
        )
    return (
        str(getattr(rag_res, "context", "") or ""),
        list(getattr(rag_res, "citations", []) or []),
        dict(getattr(rag_res, "meta", {}) or {}),
        getattr(rag_res, "gate_decision", None),
    )


async def _call_rag_retrieve_tolerant(**kwargs):
    """
    Call rag_retrieve but only pass args that exist in its signature.
    Avoid TypeError when pipeline signature changes.
    """
    sig = inspect.signature(rag_retrieve)
    filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return await rag_retrieve(**filtered)


def _log_chat_trace(payload: Dict[str, Any]) -> None:
    try:
        logger.info("chat_trace=%s", json.dumps(payload, ensure_ascii=False))
    except Exception:
        logger.info("chat_trace=%s", str(payload))


def _get_trace_id(payload: ChatRequest, request: Request) -> str:
    return (
        getattr(payload, "trace_id", None)
        or request.headers.get("x-trace-id")
        or request.headers.get("X-Trace-Id")
        or uuid.uuid4().hex
    )


def _build_llm_only_messages(*, query: str) -> List[Dict[str, str]]:
    system = (
        "Bạn là trợ lý GovAI thân thiện. "
        "Trả lời ngắn gọn, tự nhiên cho chào hỏi/hội thoại xã giao. "
        "Nếu người dùng yêu cầu thông tin pháp lý/chính sách cần căn cứ tài liệu, "
        "hãy đề nghị họ hỏi cụ thể để hệ thống truy xuất tài liệu."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": (query or "").strip()},
    ]


async def _answer_llm_only(*, query: str) -> ChatResponse:
    messages = _build_llm_only_messages(query=query)
    answer = (await achat(messages=messages, temperature=0.3, max_tokens=220)).strip()
    if not answer:
        answer = "Xin chào! Bạn cần mình hỗ trợ gì hôm nay?"
    return ChatResponse(
        answer=answer,
        citations=[],
        meta=ChatMeta(cache_hit=False, used_tools=["llm_only"], debug_info={}),
    )


def _build_ungrounded_fallback_messages(*, query: str) -> List[Dict[str, str]]:
    system = (
        "Bạn là trợ lý GovAI. Trả lời theo kiến thức phổ thông, ngắn gọn, trung tính. "
        "Không được bịa nguồn/tài liệu nội bộ. Không khẳng định đây là thông tin pháp lý cập nhật nhất. "
        "Nếu câu hỏi cần căn cứ pháp lý cụ thể, nhắc người dùng cung cấp tài liệu hoặc câu hỏi có trích dẫn."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": (query or "").strip()},
    ]


async def _answer_ungrounded_fallback(*, query: str) -> ChatResponse:
    messages = _build_ungrounded_fallback_messages(query=query)
    answer = (await achat(messages=messages, temperature=0.2, max_tokens=280)).strip()
    if not answer:
        answer = "Mình có thể giải thích khái niệm này ở mức tổng quan."
    disclaimer = "Lưu ý: Câu trả lời này dựa trên kiến thức chung, chưa có trích dẫn từ tài liệu trong hệ thống."
    out = ChatResponse(
        answer=f"{answer}\n\n{disclaimer}",
        citations=[],
        meta=ChatMeta(cache_hit=False, used_tools=["llm_ungrounded_fallback"], debug_info={}),
    )
    return out


def _get_roles(claims: AuthClaims) -> List[str]:
    return [str(r).strip().lower() for r in (getattr(claims, "roles", None) or []) if str(r).strip()]


def _sql_allowed_roles() -> List[str]:
    raw = str(getattr(settings, "SQL_EXECUTE_ALLOWED_ROLES", "admin,report,officer,chairman") or "")
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _can_execute_sql_lane(claims: AuthClaims) -> bool:
    roles = set(_get_roles(claims))
    allowed = set(_sql_allowed_roles())
    return bool(roles.intersection(allowed))


def _extract_scope_hint(q: str) -> Optional[str]:
    ql = (q or "").lower()
    if "public" in ql or "công khai" in ql:
        return "public"
    if "internal" in ql or "nội bộ" in ql:
        return "internal"
    if "restricted" in ql or "mật" in ql:
        return "restricted"
    return None


def _extract_doc_type_hint(q: str) -> Optional[str]:
    ql = (q or "").lower()
    pairs = [
        ("law", ("law", "luật")),
        ("decree", ("decree", "nghị định")),
        ("circular", ("circular", "thông tư")),
        ("decision", ("decision", "quyết định")),
        ("report", ("report", "báo cáo")),
        ("notice", ("notice", "thông báo")),
    ]
    for doc_type, hints in pairs:
        if any(h in ql for h in hints):
            return doc_type
    return None


def _sql_count_documents_statement() -> str:
    return """
    SELECT COUNT(*)::bigint AS total_docs
    FROM documents
    WHERE COALESCE(is_deleted, FALSE) = FALSE
      AND (:scope IS NULL OR LOWER(COALESCE(scope, '')) = :scope)
      AND (:doc_type IS NULL OR LOWER(COALESCE(doc_type, doc_category, '')) = :doc_type)
    """


async def _answer_sql_execute(*, query: str, claims: AuthClaims, trace_id: str) -> ChatResponse:
    scope = _extract_scope_hint(query)
    doc_type = _extract_doc_type_hint(query)
    sql = _sql_count_documents_statement()

    policy = SQLPolicy(
        tenant_column="tenant_id",
        allowed_relations=["documents"],
        max_limit=1,
        statement_timeout_ms=2000,
        forbid_set_ops=True,
        forbid_subquery=True,
        forbid_join=True,
        max_joins=0,
    )
    executor = SQLExecutor()
    result = await executor.execute_safe(
        sql=sql,
        tenant_id=claims.tenant_id,
        params={"scope": scope, "doc_type": doc_type},
        trace_id=trace_id,
        policy=policy,
        lane="manual",
    )
    rows = result.get("data") or []
    total = 0
    if rows and isinstance(rows[0], dict):
        try:
            total = int(rows[0].get("total_docs") or 0)
        except Exception:
            total = 0

    scope_txt = scope or "all"
    doc_type_txt = doc_type or "all"
    answer = f"Số văn bản hiện có (scope={scope_txt}, doc_type={doc_type_txt}): {total}."
    return ChatResponse(
        answer=answer,
        citations=[],
        meta=ChatMeta(
            cache_hit=False,
            used_tools=["sql_execute_count_documents"],
            debug_info={
                "sql_lane": {
                    "intent": "count_documents",
                    "scope": scope,
                    "doc_type": doc_type,
                    "row_count": int(result.get("meta", {}).get("row_count") or 0),
                }
            },
        ),
    )


def _make_sql_permission_refusal() -> ChatResponse:
    msg = "Tính năng truy vấn thống kê SQL yêu cầu quyền cao hơn (403). Vui lòng dùng API key role admin/report."
    out = ChatResponse(
        answer=msg,
        citations=[],
        meta=ChatMeta(cache_hit=False, used_tools=["sql_candidate_denied"], debug_info={}),
    )
    setattr(out.meta, "is_refusal", True)
    setattr(out.meta, "refusal", {"code": "INSUFFICIENT_CLEARANCE", "message": msg})
    setattr(out.meta, "http_status", 403)
    return out


def _extract_refusal_code(meta: Any) -> Optional[str]:
    def _norm(code: Any) -> Optional[str]:
        if code is None:
            return None
        if hasattr(code, "value"):
            code = getattr(code, "value")
        out = str(code).strip()
        return out or None

    ref = getattr(meta, "refusal", None)
    if isinstance(ref, dict):
        return _norm(ref.get("code"))
    if isinstance(meta, dict):
        ref2 = meta.get("refusal")
        if isinstance(ref2, dict):
            return _norm(ref2.get("code"))
    return None


def _set_refusal_message(meta: Any, message: str) -> None:
    ref = getattr(meta, "refusal", None)
    if isinstance(ref, dict):
        ref["message"] = message
        return
    if isinstance(meta, dict):
        ref2 = meta.get("refusal")
        if isinstance(ref2, dict):
            ref2["message"] = message


def _query_has_restricted_scope_hint(q: str) -> bool:
    ql = (q or "").lower()
    return any(x in ql for x in ("nội bộ", "noi bo", "restricted", "mật", "mat"))


def _should_use_no_evidence_fallback(
    *,
    decision: Any,
    effective_security_level: int,
    query: str,
) -> bool:
    if int(effective_security_level or 1) >= 2:
        return False
    if getattr(decision, "is_evidence_required", False):
        return False
    if _query_has_restricted_scope_hint(query):
        return False
    return bool(
        getattr(decision, "is_smalltalk", False)
        or getattr(decision, "is_agent_intro", False)
        or getattr(decision, "is_general_explain", False)
    )


def _append_no_evidence_next_steps(answer: str) -> str:
    base = (answer or "").strip()
    if "Gợi ý tiếp theo:" in base:
        return base
    tips = (
        "Gợi ý tiếp theo:\n"
        "- Nạp tài liệu liên quan vào đúng tenant hiện tại.\n"
        "- Hỏi cụ thể hơn (ví dụ số điều/khoản, tên văn bản, hoặc trích đoạn).\n"
        "- Kiểm tra API key/tenant/scope để chắc dữ liệu thuộc phạm vi truy cập."
    )
    if not base:
        return tips
    return f"{base}\n\n{tips}"


def _compute_evidence_status(*, response: ChatResponse, route_mode: str) -> str:
    citations_len = len(list(response.citations or []))
    meta = response.meta
    if meta and getattr(meta, "is_refusal", False):
        code = _extract_refusal_code(meta)
        if code == "NO_EVIDENCE":
            refusal_msg = ""
            ref = getattr(meta, "refusal", None)
            if isinstance(ref, dict):
                refusal_msg = str(ref.get("message") or "")
            answer = str(response.answer or "")
            if "no_hits" in refusal_msg.lower() or "no_hits" in answer.lower():
                return "no_hits"
            return "low_evidence"
        return "refused"
    if meta and getattr(meta, "ungrounded", False):
        return "no_hits"
    if str(route_mode).startswith("rag") and citations_len <= 0:
        return "low_evidence"
    return "ok"


def _set_routing_meta(
    *,
    response: ChatResponse,
    route_mode: str,
    route_reason: str,
    sql_candidate: bool,
    original_route_mode: Optional[str] = None,
) -> None:
    if response.meta is None:
        response.meta = ChatMeta()
    setattr(response.meta, "route_mode", route_mode)
    setattr(response.meta, "route_reason", route_reason)
    setattr(response.meta, "route_sql_candidate", bool(sql_candidate))
    if response.meta.debug_info is None:
        response.meta.debug_info = {}
    routing_debug: Dict[str, Any] = {
        "route_mode": route_mode,
        "route_reason": route_reason,
        "sql_candidate": bool(sql_candidate),
    }
    if original_route_mode:
        routing_debug["original_route_mode"] = original_route_mode
    response.meta.debug_info["routing"] = routing_debug


def _apply_meta_contract(
    *,
    response: ChatResponse,
    route_mode: str,
    route_reason: str,
    sql_candidate: bool,
    original_route_mode: Optional[str] = None,
) -> None:
    _set_routing_meta(
        response=response,
        route_mode=route_mode,
        route_reason=route_reason,
        sql_candidate=sql_candidate,
        original_route_mode=original_route_mode,
    )
    citations_len = len(list(response.citations or []))
    setattr(response.meta, "citations_len", citations_len)
    setattr(
        response.meta,
        "evidence_status",
        _compute_evidence_status(response=response, route_mode=route_mode),
    )


def _as_chat_response(chunk: Any) -> Optional[ChatResponse]:
    if isinstance(chunk, ChatResponse):
        return chunk
    if isinstance(chunk, dict):
        try:
            return ChatResponse(**chunk)
        except Exception:
            return None
    if hasattr(chunk, "answer") and hasattr(chunk, "citations"):
        try:
            return ChatResponse(
                answer=str(getattr(chunk, "answer", "") or ""),
                citations=list(getattr(chunk, "citations", []) or []),
                meta=getattr(chunk, "meta", None) or ChatMeta(),
                handoff=getattr(chunk, "handoff", None),
            )
        except Exception:
            return None
    return None


def _read_attempt_debug(meta: Any) -> List[Dict[str, Any]]:
    attempts = getattr(meta, "attempts", None)
    if not attempts and isinstance(meta, dict):
        attempts = meta.get("attempts")
    if not isinstance(attempts, list):
        return []
    out: List[Dict[str, Any]] = []
    for a in attempts:
        if not isinstance(a, dict):
            continue
        rd = a.get("retrieve_debug")
        if isinstance(rd, dict):
            out.append(rd)
    return out


def _derive_rag_route_mode(*, meta: Any, requested_mode: str, requested_reason: str) -> Tuple[str, str]:
    used_tools = set(getattr(meta, "used_tools", None) or [])
    attempt_debug = _read_attempt_debug(meta)
    fusion_modes = {str(d.get("fusion_mode") or "") for d in attempt_debug}
    lexical_skips = [str(d.get("lexical_skip_reason") or "") for d in attempt_debug if d.get("lexical_skip_reason")]

    if "lexical_search" in used_tools and "hybrid_search" in used_tools:
        return "rag_hybrid", "lexical_plus_vector"
    if "lexical_search" in used_tools:
        return "rag_lexical", "lexical_only"
    if "rrf_lexical_hybrid" in fusion_modes:
        return "rag_hybrid", "rrf_lexical_hybrid"

    if requested_mode == "rag_lexical":
        if lexical_skips:
            return "rag_vector", f"lexical_skipped_{lexical_skips[0]}"
        return "rag_vector", "lexical_skipped_unknown"
    return "rag_vector", requested_reason


def _sanitize_citations_for_client(citations: List[Citation]) -> List[Citation]:
    safe: List[Citation] = []
    for c in citations or []:
        doc_id = str(getattr(c, "document_id", "") or "").strip()
        raw_url = str(getattr(c, "file_url", "") or "").strip()

        # Never leak raw storage paths/source_uri to clients.
        if doc_id:
            c.file_url = f"/api/docs/{doc_id}"
        else:
            lower = raw_url.lower()
            if lower.startswith("http://") or lower.startswith("https://") or lower.startswith("/api/"):
                c.file_url = raw_url
            else:
                c.file_url = None
        safe.append(c)
    return safe


# -------------------------------------------------------------------------
# Streaming Implementation (PR-D)
# -------------------------------------------------------------------------

# -------------------------------------------------------------------------
# Streaming Implementation (PR-D) -> Refactored for PR-B0 (Registry)
# -------------------------------------------------------------------------
async def chat_stream_gen(
    payload: ChatRequest,
    request: Request,
    db: AsyncSession,
    claims: AuthClaims,
    security_level: int,
    trace_id: str,
) -> AsyncGenerator[str, None]:
    """
    SSE Generator for Chat.
    Handles: Rate Limit (Stream + Inflight), routing parity, and SSE formatting.
    """
    from app.core.rate_limit import rate_limiter
    from app.core.metrics import STREAMS_ACTIVE, CHAT_REQUESTS_TOTAL
    from app.security.context import build_trusted_context
    from app.core.policy.manager import PolicyManager

    # B4: Server-Side Tenant
    tenant_id = claims.tenant_id
    
    agent_id = payload.agent_id or "universal"
    raw_query = getattr(payload, "query", None) or getattr(payload, "message", None)
    q_str = str(raw_query or "")
    q = _normalize_query(q_str)
    
    audit_event(
        "chat.request",
        trace_id=trace_id,
        endpoint="/api/chat",
        method="POST",
        tenant_id=claims.tenant_id,
        subject=claims.subject,
        roles=claims.roles,
        security_level=security_level, # C3.1: Use enforced level
        agent_id=agent_id,
        stream=True,
        query_len=len(q_str),
        query_sha1=compute_query_hash(q_str)
    )

    # Stream Concurrency Limit
    stream_res = await rate_limiter.enter_stream(tenant_id)
    if not stream_res.allowed:
        # Audit Error ? (Rate Limited)
        yield sse_pack("error", {"code": 429, "message": "Too many concurrent streams"})
        return

    t0 = time.perf_counter()
    citations_count = 0
    status = "ok"
    route_mode = "unknown"
    route_reason = "unknown"
    target_agent = None
    
    try:
        STREAMS_ACTIVE.inc()

        # B4: Trusted Context
        ctx = build_trusted_context(claims, request, payload)
        if hasattr(ctx, 'security_level'):
            ctx.security_level = security_level

        route_decision = decide_route_mode(
            query=q,
            agent_id=agent_id,
            security_level=security_level,
        )
        route_mode = route_decision.mode
        route_reason = route_decision.reason

        yield sse_pack(
            "meta",
            {
                "trace_id": trace_id,
                "agent_id": agent_id,
                "route_mode": route_mode,
                "route_reason": route_reason,
                "sql_candidate": bool(route_decision.sql_candidate),
            },
        )

        target_agent = get_agent(agent_id)
        if not target_agent:
            err_msg = f"Agent {agent_id} not found"
            audit_event("chat.error", trace_id=trace_id, tenant_id=tenant_id, agent_id=agent_id, error_type="AgentNotFound", error_msg=err_msg)
            status = "error"
            yield sse_pack("error", {"code": 404, "message": err_msg})
            return

        async def _emit_response_events(resp: ChatResponse) -> AsyncGenerator[str, None]:
            nonlocal citations_count, status, route_mode, route_reason

            if resp.meta is None:
                resp.meta = ChatMeta()

            if str(route_mode).startswith("rag"):
                route_mode, route_reason = _derive_rag_route_mode(
                    meta=resp.meta,
                    requested_mode=route_mode,
                    requested_reason=route_reason,
                )

            resp.citations = _sanitize_citations_for_client(list(resp.citations or []))
            _apply_meta_contract(
                response=resp,
                route_mode=route_mode,
                route_reason=route_reason,
                sql_candidate=bool(route_decision.sql_candidate),
            )

            if resp.meta and getattr(resp.meta, "is_refusal", False):
                refusal_code = _extract_refusal_code(resp.meta)
                if refusal_code == "NO_EVIDENCE":
                    if _should_use_no_evidence_fallback(
                        decision=route_decision,
                        effective_security_level=security_level,
                        query=q,
                    ):
                        try:
                            original_route_mode = route_mode
                            original_route_reason = route_reason
                            fallback = await _answer_ungrounded_fallback(query=q)
                            route_mode = "llm_only"
                            route_reason = "no_evidence_llm_fallback"
                            setattr(fallback.meta, "ungrounded", True)
                            setattr(fallback.meta, "fallback_reason", "no_evidence_llm_fallback")
                            setattr(fallback.meta, "original_route_mode", original_route_mode)
                            setattr(fallback.meta, "original_route_reason", original_route_reason)
                            _apply_meta_contract(
                                response=fallback,
                                route_mode=route_mode,
                                route_reason=route_reason,
                                sql_candidate=bool(route_decision.sql_candidate),
                                original_route_mode=original_route_mode,
                            )
                            resp = fallback
                        except Exception as e:
                            logger.warning("stream_no_evidence_llm_fallback_failed: %s", type(e).__name__)

                    if resp.meta and getattr(resp.meta, "is_refusal", False):
                        resp.answer = _append_no_evidence_next_steps(str(resp.answer or ""))
                        _set_refusal_message(resp.meta, resp.answer)
                        _apply_meta_contract(
                            response=resp,
                            route_mode=route_mode,
                            route_reason=route_reason,
                            sql_candidate=bool(route_decision.sql_candidate),
                        )
                status = "refused"

            yield sse_pack(
                "meta",
                {
                    "trace_id": trace_id,
                    "agent_id": agent_id,
                    "route_mode": route_mode,
                    "route_reason": route_reason,
                    "sql_candidate": bool(route_decision.sql_candidate),
                    "evidence_status": getattr(resp.meta, "evidence_status", None),
                    "citations_len": int(getattr(resp.meta, "citations_len", len(resp.citations or [])) or 0),
                    "ungrounded": bool(getattr(resp.meta, "ungrounded", False)),
                },
            )

            cits = list(resp.citations or [])
            citations_count = max(citations_count, len(cits))
            if cits:
                yield sse_pack(
                    "citation",
                    {
                        "items": [
                            c.model_dump(exclude_none=True) if hasattr(c, "model_dump") else dict(c)  # type: ignore[arg-type]
                            for c in cits
                        ]
                    },
                )

            if resp.answer:
                yield sse_pack("token", {"text": str(resp.answer)})

            done_payload: Dict[str, Any] = {
                "ok": not bool(getattr(resp.meta, "is_refusal", False)),
                "route_mode": route_mode,
                "route_reason": route_reason,
            }
            refusal = getattr(resp.meta, "refusal", None)
            if isinstance(refusal, dict):
                done_payload["refusal"] = refusal
            yield sse_pack("done", done_payload)

        if route_mode == "llm_only":
            PolicyManager.enforce_context(agent_id, ctx)
            response = await _answer_llm_only(query=q)
            async for event in _emit_response_events(response):
                yield event
            return

        if route_mode == "sql_candidate":
            PolicyManager.enforce_context(agent_id, ctx)
            if not _can_execute_sql_lane(claims):
                response = _make_sql_permission_refusal()
                route_reason = "requires_role"
            else:
                response = await _answer_sql_execute(query=q, claims=claims, trace_id=trace_id)
                route_mode = "sql_execute"
                route_reason = "aggregate_intent_sql_execute"
            async for event in _emit_response_events(response):
                yield event
            return

        # RAG stream path: prefer native SSE strings, but support ChatResponse chunks safely.
        PolicyManager.enforce_context(agent_id, ctx)
        emitted_done = False
        async for chunk in target_agent.process_stream(ctx, payload.message):
            if isinstance(chunk, str):
                if "event: citation" in chunk:
                    citations_count = max(citations_count, 1)
                if "event: done" in chunk:
                    emitted_done = True
                yield chunk
                continue

            resp = _as_chat_response(chunk)
            if resp is None:
                continue
            async for event in _emit_response_events(resp):
                if "event: done" in event:
                    emitted_done = True
                yield event

        if not emitted_done:
            yield sse_pack(
                "done",
                {"ok": status != "error", "route_mode": route_mode, "route_reason": route_reason},
            )
             
    except Exception as e:
        status = "error"
        logger.exception("Stream Error")
        audit_event("chat.error", 
            trace_id=trace_id, 
            tenant_id=tenant_id, 
            agent_id=agent_id, 
            error_type=type(e).__name__, 
            error_msg=str(e)[:200]
        )
        yield sse_pack("error", {"code": 500, "message": str(e)})
    finally:
        # Metrics
        duration = time.perf_counter() - t0
        CHAT_LATENCY_SECONDS.labels(
            agent_id=agent_id, lane="all", stream="true", stage="total"
        ).observe(duration)
        
        CHAT_REQUESTS_TOTAL.labels(
            agent_id=agent_id, lane="all", stream="true", status=status
        ).inc()

        # Audit Response (Stream End)
        audit_event("chat.response",
            trace_id=trace_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            route_mode=route_mode,
            route_reason=route_reason,
            status=status,
            latency_ms=int(duration * 1000),
            citations_count=citations_count,
            stream=True
        )

        # --- PR-10: RAG Access Audit (Streaming Parity) ---
        # Streaming agents handle RAG internally; we emit rag.access
        # with safe QE defaults (or real data if agent exposes meta).
        try:
            # Try to read QE meta from agent's last response if available
            _stream_qe_meta = qe_audit_from_meta(
                getattr(target_agent, '_last_response_meta', None) if 'target_agent' in dir() else None
            )
            audit_event("rag.access",
                trace_id=trace_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                citations_count=citations_count,
                stream=True,
                **_stream_qe_meta
            )
        except Exception:
            # Fail-safe: emit with defaults rather than losing the audit
            audit_event("rag.access",
                trace_id=trace_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                citations_count=citations_count,
                stream=True,
                **qe_audit_from_meta(None)
            )
        STREAMS_ACTIVE.dec()
        await rate_limiter.exit_stream(tenant_id)

                 



@router.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat_endpoint(
    payload: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
    claims: AuthClaims = Depends(require_auth), # <--- Auth Enforced
):
    from app.core.rate_limit import rate_limiter
    
    # 1. Server-Side Tenant Isolation (Step B4)
    # Ignore payload.tenant_id (legacy/spoofable)
    tenant_id = claims.tenant_id
    if getattr(payload, "tenant_id", None) and payload.tenant_id != tenant_id:
        # Just log warning, do not fail (backward compat or debug)
        logger.warning(f"Tenant Mismatch: Payload={payload.tenant_id} ignored. Using Auth={tenant_id}")
    
    from app.core.rate_limit import rate_limiter

    rl_res = await rate_limiter.allow_request(tenant_id)
    if not rl_res.allowed:
        headers = {"Retry-After": str(int(rl_res.retry_after_s or 1))}
        CHAT_REQUESTS_TOTAL.labels(agent_id=getattr(payload, "agent_id", "citizen"), lane="all", stream="false", status="rate_limited").inc()
        raise HTTPException(status_code=429, detail="Too Many Requests (RPS)", headers=headers)
    
    # Generate Trace ID early
    trace_id = _get_trace_id(payload, request)

    # C3.1: Shared Authorization (Blocking + Streaming)
    # Returns (agent_id, effective_security_level) or raises 403
    agent_id, effective_security_level = authorize_chat_request(payload, claims, trace_id)

    # 2. Dispatch (Stream vs Block)
    if payload.stream:
        return StreamingResponse(
            chat_stream_gen(payload, request, db, claims, effective_security_level, trace_id), 
            media_type="text/event-stream"
        )

    # 3. Inflight Limit (Blocking Path)
    inflight_res = await rate_limiter.enter_inflight(tenant_id, lane="all")
    if not inflight_res.allowed:
        CHAT_REQUESTS_TOTAL.labels(agent_id=agent_id, lane="all", stream="false", status="rate_limited").inc()
        raise HTTPException(status_code=503, detail="Server Overloaded (Inflight)")
        
    try:
        INFLIGHT_ACTIVE.labels(lane="all").inc()
        return await _chat_endpoint_impl(payload, request, db, claims, effective_security_level, trace_id)
    finally:
        INFLIGHT_ACTIVE.labels(lane="all").dec()
        await rate_limiter.exit_inflight(tenant_id, lane="all")

async def _chat_endpoint_impl(
    payload: ChatRequest,
    request: Request,
    db: AsyncSession,
    claims: AuthClaims,
    effective_security_level: int,
    trace_id: str,
):
    from app.security.context import build_trusted_context
    
    t0 = time.perf_counter()
    # trace_id passed from caller

    # B4: Build TrustedContext from Claims (Server-Side Tenant)
    ctx = build_trusted_context(claims, request, payload)

    # ---- basic fields ----
    agent_id = getattr(payload, "agent_id", "citizen")
    raw_query = getattr(payload, "query", None) or getattr(payload, "message", None)
    
    q_str = str(raw_query or "")
    q = _normalize_query(q_str)

    # Update context with effective security level (Authorized in chat_endpoint)
    if hasattr(ctx, 'security_level'):
        ctx.security_level = effective_security_level

    # --- B6: Audit Request (Blocking) ---
    audit_event(
        "chat.request",
        trace_id=trace_id,
        endpoint="/api/chat",
        method="POST",
        tenant_id=claims.tenant_id,
        subject=claims.subject,
        roles=claims.roles,
        security_level=effective_security_level,  # Log effective level
        agent_id=agent_id,
        stream=False,
        query_len=len(q_str),
        query_sha1=compute_query_hash(q_str),
    )

    if not q:
        # Audit Error
        audit_event(
            "chat.error", 
            trace_id=trace_id, 
            tenant_id=claims.tenant_id, 
            agent_id=agent_id,
            error_type="ValidationError",
            error_msg="Empty query"
        )
        raise HTTPException(status_code=400, detail="Empty query")
    
    # Wrap in Try/Except for Audit Error + Metrics
    status = "ok" # Initialize status for metrics
    try:
        from app.core.policy.manager import PolicyManager
        import uuid

        route_decision = decide_route_mode(
            query=q,
            agent_id=agent_id,
            security_level=effective_security_level,
        )
        route_mode = route_decision.mode
        route_reason = route_decision.reason
        session_id = getattr(payload, "session_id", None) or str(uuid.uuid4())
        active_case = None
        linked = False
        agent_ms = 0
        response = None

        # ============================================================================
        # 1. AGENT LOOKUP + POLICY
        # ============================================================================
        agent = get_agent(agent_id)
        if agent is None:
            audit_event(
                "chat.error",
                trace_id=trace_id,
                tenant_id=claims.tenant_id,
                agent_id=agent_id,
                error_type="AgentNotFound",
                error_msg=f"Agent {agent_id} not found",
            )
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        if route_mode == "llm_only":
            try:
                t_agent_start = time.perf_counter()
                PolicyManager.enforce_context(agent_id, ctx)
                response = await _answer_llm_only(query=q)
                agent_ms = int((time.perf_counter() - t_agent_start) * 1000)
            except MissingContextError as e:
                audit_event(
                    "chat.error",
                    trace_id=trace_id,
                    tenant_id=claims.tenant_id,
                    agent_id=agent_id,
                    error_type="MissingContextError",
                    error_msg=str(e),
                )
                raise HTTPException(status_code=403, detail=f"Agent Policy Error: {str(e)}")
            except Exception as e:
                # Preserve old behavior as fallback if LLM-only path fails.
                logger.warning("llm_only_failed, fallback_to_rag: %s", type(e).__name__)
                route_mode = "rag_vector"
                route_reason = "llm_only_fallback_to_rag"

        if response is None and route_mode == "sql_candidate":
            try:
                t_agent_start = time.perf_counter()
                PolicyManager.enforce_context(agent_id, ctx)
                if not _can_execute_sql_lane(claims):
                    response = _make_sql_permission_refusal()
                    route_reason = "requires_role"
                else:
                    response = await _answer_sql_execute(query=q, claims=claims, trace_id=trace_id)
                    route_mode = "sql_execute"
                    route_reason = "aggregate_intent_sql_execute"
                agent_ms = int((time.perf_counter() - t_agent_start) * 1000)
            except MissingContextError as e:
                audit_event(
                    "chat.error",
                    trace_id=trace_id,
                    tenant_id=claims.tenant_id,
                    agent_id=agent_id,
                    error_type="MissingContextError",
                    error_msg=str(e),
                )
                raise HTTPException(status_code=403, detail=f"Agent Policy Error: {str(e)}")
            except Exception as e:
                logger.warning("sql_execute_failed: %s", type(e).__name__)
                response = ChatResponse(
                    answer="Không thể thực thi truy vấn thống kê SQL lúc này. Vui lòng thử lại sau.",
                    citations=[],
                    meta=ChatMeta(cache_hit=False, used_tools=["sql_execute_failed"], debug_info={}),
                )
                setattr(response.meta, "is_refusal", True)
                setattr(response.meta, "refusal", {"code": "POLICY_VIOLATION", "message": response.answer})
                route_mode = "sql_execute"
                route_reason = "sql_execute_failed"
                agent_ms = int((time.perf_counter() - t_agent_start) * 1000)

        if response is None:
            # ============================================================================
            # 2. CONVERSATION MEMORY + AGENT DISPATCH (RAG path)
            # ============================================================================
            from app.core.memory.session_store import get_session_store
            from app.core.memory.case_memory import CaseMemory
            from app.core.memory.linker import choose_best_case
            from app.core.prompts.templates import build_retrieval_context

            store = get_session_store()

            # Simple Memory Logic
            all_cases = await store.get_cases(session_id)
            recent_cases = all_cases[-3:] if len(all_cases) > 3 else all_cases
            best_case, _, _ = choose_best_case(q, recent_cases, threshold=0.4)

            if best_case:
                turn = best_case.last_updated_turn + 1
                best_case.update_from_message(q, turn)
                active_case = best_case
                linked = True
            else:
                new_case = CaseMemory(id=str(uuid.uuid4()), session_id=session_id, topic="", user_goal="")
                new_case.update_from_message(q, turn=1)
                await store.add_case(session_id, new_case)
                active_case = new_case
                linked = False

            retrieval_query = build_retrieval_context(q, active_case)

            try:
                t_agent_start = time.perf_counter()
                PolicyManager.enforce_context(agent_id, ctx)
                response = await execute_agent_query(
                    agent=agent,
                    ctx=ctx,
                    query=retrieval_query,
                    db=db,
                    trace_id=trace_id,
                )
                agent_ms = int((time.perf_counter() - t_agent_start) * 1000)
            except MissingContextError as e:
                audit_event(
                    "chat.error",
                    trace_id=trace_id,
                    tenant_id=claims.tenant_id,
                    agent_id=agent_id,
                    error_type="MissingContextError",
                    error_msg=str(e),
                )
                raise HTTPException(status_code=403, detail=f"Agent Policy Error: {str(e)}")
            except Exception as e:
                status = "error" # Update status on agent error
                logger.exception(f"Agent Process Failed: {e}")
                audit_event(
                    "chat.error",
                    trace_id=trace_id,
                    tenant_id=claims.tenant_id,
                    agent_id=agent_id,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                )
                raise HTTPException(status_code=500, detail=f"Agent Error: {str(e)}")

        if response.meta is None:
            response.meta = ChatMeta()
        if str(route_mode).startswith("rag"):
            route_mode, route_reason = _derive_rag_route_mode(
                meta=response.meta,
                requested_mode=route_mode,
                requested_reason=route_reason,
            )
        response.citations = _sanitize_citations_for_client(list(response.citations or []))
        _apply_meta_contract(
            response=response,
            route_mode=route_mode,
            route_reason=route_reason,
            sql_candidate=bool(route_decision.sql_candidate),
        )
        _log_chat_trace(
            {
                "trace_id": trace_id,
                "tenant_id": claims.tenant_id,
                "agent_id": agent_id,
                "route_mode": route_mode,
                "route_reason": route_reason,
                "sql_candidate": bool(route_decision.sql_candidate),
            }
        )

        # ============================================================================
        # 3. POST-PROCESS (Guard + Metrics)
        # ============================================================================
        
        # Check Refusal
        if response.meta and getattr(response.meta, "is_refusal", False):
            refusal_code = _extract_refusal_code(response.meta)
            if refusal_code == "NO_EVIDENCE":
                if _should_use_no_evidence_fallback(
                    decision=route_decision,
                    effective_security_level=effective_security_level,
                    query=q,
                ):
                    try:
                        original_route_mode = route_mode
                        original_route_reason = route_reason
                        response = await _answer_ungrounded_fallback(query=q)
                        route_mode = "llm_only"
                        route_reason = "no_evidence_llm_fallback"
                        setattr(response.meta, "ungrounded", True)
                        setattr(response.meta, "fallback_reason", "no_evidence_llm_fallback")
                        setattr(response.meta, "original_route_mode", original_route_mode)
                        setattr(response.meta, "original_route_reason", original_route_reason)
                        _apply_meta_contract(
                            response=response,
                            route_mode=route_mode,
                            route_reason=route_reason,
                            sql_candidate=bool(route_decision.sql_candidate),
                            original_route_mode=original_route_mode,
                        )
                    except Exception as e:
                        logger.warning("no_evidence_llm_fallback_failed: %s", type(e).__name__)

                if response.meta and getattr(response.meta, "is_refusal", False):
                    response.answer = _append_no_evidence_next_steps(str(response.answer or ""))
                    _set_refusal_message(response.meta, response.answer)
                    _apply_meta_contract(
                        response=response,
                        route_mode=route_mode,
                        route_reason=route_reason,
                        sql_candidate=bool(route_decision.sql_candidate),
                    )

            # If response is still refusal after fallback handling, return immediately.
            if response.meta and getattr(response.meta, "is_refusal", False):
                GATE_FAIL_TOTAL.labels(agent_id=agent_id, reason="agent_refusal").inc()
                status = "refused" # Update status on refusal
                audit_event(
                    "chat.response",
                    trace_id=trace_id,
                    tenant_id=claims.tenant_id,
                    agent_id=agent_id,
                    status="refused",
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    citations_count=0,
                    route_mode=route_mode,
                    route_reason=route_reason,
                )
                # Return immediately
                return response

        # Check Handoff (Already in response object)
        if response.handoff:
            # Optional: Log handoff metric
            pass

        # Citation Guard (Router Level Safety)
        # Only if citations exist
        citations = response.citations
        answer = response.answer
        
        citation_verified = True
        guard_ms = 0
        repair_ms = 0
        
        # Configure via agent config if possible, or use global default
        # For now, simplistic check: allow agent to bypass if they are trusted?
        # We apply same guard as before.
        if citations and len(citations) > 0:
            max_repair_rounds = 1 
            expand_ranges = False
            guard_cfg = CitationGuardConfig(max_repair_rounds=max_repair_rounds, expand_ranges=expand_ranges)
            
            t_guard = time.perf_counter()
            ok, info = validate_citations(answer, num_sources=len(citations), cfg=guard_cfg)
            guard_ms = int((time.perf_counter() - t_guard) * 1000)
            
            if not ok and max_repair_rounds > 0:
                 # Repair Logic (Router manages repair using LLM)
                 # Note: We need messages to repair. But we don't have the agent's internal messages!
                 # We can construct a synthetic repair context?
                 # Or "CitationGuard" should be inside Agent?
                 # For PR-B0, let's just log warning and soft-fail (mark verified=False).
                 # Repairing without context (system prompt etc) is hard.
                 citation_verified = False
                 
            setattr(response.meta, "citation_guard", info)
            setattr(response.meta, "citation_verified", citation_verified)

        # Final Metrics
        total_ms = int((time.perf_counter() - t0) * 1000)
        if hasattr(response.meta, "debug_info") and response.meta.debug_info is not None:
            response.meta.debug_info.update({
                "timing": {
                    "agent_ms": agent_ms,
                    "guard_ms": guard_ms,
                    "total_ms": total_ms
                }
            })
        response.meta.session_id = session_id
        if active_case is not None:
            setattr(response.meta, "case_id", active_case.id)
        setattr(response.meta, "linked", linked)
        
        # --- B6: RAG Access Audit ---
        if citations:
            doc_ids = list(set(getattr(c, "document_id", None) for c in citations if getattr(c, "document_id", None)))
            chunk_ids = list(set(getattr(c, "chunk_id", None) for c in citations if getattr(c, "chunk_id", None)))
            
            # Extract query expansion audit metrics via centralized helper
            qe_meta = qe_audit_from_meta(response.meta)
                
            audit_event("rag.access",
                trace_id=trace_id,
                tenant_id=claims.tenant_id,
                agent_id=agent_id,
                citations_count=len(citations),
                doc_ids=doc_ids[:20],
                chunk_ids=chunk_ids[:20],
                **qe_meta
            )

        # --- B6: Chat Response Audit ---
        audit_event("chat.response",
            trace_id=trace_id,
            tenant_id=claims.tenant_id,
            agent_id=agent_id,
            status="ok",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            citations_count=len(citations) if citations else 0,
            handoff_target=response.handoff.target_agent_id if response.handoff else None,
            route_mode=route_mode,
            route_reason=route_reason
        )

        return response

    except Exception as e:
        status = "error" # Update status on general exception
        # Catch-all Audit Error for Blocking Path
        if not isinstance(e, HTTPException):
             # Only log unknown errors, HTTPExceptions normally handled
             audit_event("chat.error", 
                 trace_id=trace_id, 
                 tenant_id=claims.tenant_id, 
                 agent_id=agent_id,
                 error_type=type(e).__name__,
                 error_msg=str(e)[:200]
             )
        raise
    finally:
        # Metrics (B7)
        duration = time.perf_counter() - t0
        CHAT_LATENCY_SECONDS.labels(
            agent_id=agent_id, lane="all", stream="false", stage="total"
        ).observe(duration)
        
        CHAT_REQUESTS_TOTAL.labels(
            agent_id=agent_id, lane="all", stream="false", status=status
        ).inc()


# ============================================================================
# STREAMING ENDPOINT (PR5) + RATE LIMITING (PR6)
# ============================================================================
from fastapi.responses import StreamingResponse
from app.core.rate_limit import rate_limiter

def sse_pack(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

@router.post("/chat/stream", tags=["chat"])
async def chat_stream(
    request: Request,
):
    """
    [DEPRECATED] This endpoint is deprecated and will be removed.
    Please use POST /api/chat with 'stream': true in the payload.
    """
    raise HTTPException(
        status_code=410, 
        detail="This endpoint is deprecated. Use POST /api/chat with 'stream': true."
    )
