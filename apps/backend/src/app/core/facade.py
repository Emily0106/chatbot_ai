from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rag.pipeline import rag_retrieve, RagPipelineResult
from app.schemas.chat import RetrievalFilters, Citation
from app.core.policy.manager import PolicyManager
from app.core.policy.types import UserContext
from app.core.taxonomy import GeoLevel
from fastapi import HTTPException
from app.core.policy.errors import MissingContextError
from app.schemas.chat import ChatResponse

logger = logging.getLogger(__name__)

T = TypeVar("T")

@dataclass
class CoreError:
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None

@dataclass
class CoreResponse(Generic[T]):
    ok: bool
    data: Optional[T] = None
    error: Optional[CoreError] = None
    meta: Dict[str, Any] = field(default_factory=dict)

class CoreService:
    """
    Unified interface for all Core capabilities.
    Enforces: Tenant Isolation, Tracing, Error Handling.
    """

    async def search(
        self,
        db: AsyncSession,
        query: str,
        *,
        tenant_id: str,
        trace_id: str,
        agent_id: str = "core_facade",
        filters: Optional[RetrievalFilters] = None,
        top_k: int = 30,
        enable_rerank: bool = True,
        department_id: Optional[str] = None
    ) -> CoreResponse[RagPipelineResult]:
        """
        Performs RAG retrieval (Hybrid + Rerank + Gate).
        Wraps app.core.rag.pipeline.rag_retrieve.
        """
        t0 = time.perf_counter()
        
        # 0. Build UserContext (MVP: derived from args)
        # Future: Pass full UserContext from API layer
        user_ctx = UserContext(
            tenant_id=tenant_id,
            role=None, # Not passed to search yet
            department_id=department_id,
            security_level=None
        )

        try:
            # 1. Enforce Policy
            policy_result = PolicyManager.enforce_filters(
                agent_id=agent_id,
                user_ctx=user_ctx,
                request_filters=filters
            )
        except MissingContextError as e:
            # Convert policy error to 403 Access Denied
            logger.warning(f"CoreService: Access Denied for agent {agent_id}. Reason: {e}")
            raise HTTPException(status_code=403, detail=f"missing_context:{e.field}")
        
        final_constraints = policy_result["filters"]
        policy_meta = policy_result["policy_meta"]
        
        # Log conflict if any
        if policy_meta.get("conflict"):
            logger.warning(f"Policy Conflict for agent={agent_id}: {policy_meta}")

        # 2. Convert to RetrievalFilters object
        clean_filters = RetrievalFilters(
            doc_type=final_constraints.get("doc_type"),
            doc_types=final_constraints.get("doc_types"), # Support multiple
            domain=final_constraints.get("domain"),
            security_level=final_constraints.get("security_level"),
            status=final_constraints.get("status"),
            from_date=final_constraints.get("from_date"),
            to_date=final_constraints.get("to_date")
        )

        try:
            result = await rag_retrieve(
                db=db,
                tenant_id=tenant_id,
                agent_id=agent_id,
                query=query,
                filters=clean_filters, # Use enforced filters
                top_k=top_k,
                enable_rerank=enable_rerank,
                trace_id=trace_id,
            )
            
            # Inject Policy Meta into Result Meta for Debugging
            result.meta["policy"] = policy_meta
            
            # Check for "soft" failures (e.g. no context found)
            # rag_retrieve returns empty context if no hits/gating failed
            if not result.context:
                return CoreResponse(
                    ok=True, # It's a valid execution, just no result
                    data=result,
                    meta={
                        "trace_id": trace_id,
                        "duration_ms": duration,
                        "reason": result.meta.get("reason", "no_context"),
                        "gating_passed": False
                    }
                )

            return CoreResponse(
                ok=True,
                data=result,
                meta={
                    "trace_id": trace_id,
                    "duration_ms": duration,
                    "reason": "success",
                    "gating_passed": True,
                    **result.meta
                }
            )

        except Exception as e:
            logger.exception(f"CoreService.search failed: {e}")
            return CoreResponse(
                ok=False,
                error=CoreError(
                    code="INTERNAL_ERROR",
                    message=str(e)
                ),
                meta={
                    "trace_id": trace_id,
                    "duration_ms": int((time.perf_counter() - t0) * 1000)
                }
            )

_instance = CoreService()

def get_core_service() -> CoreService:
    return _instance


async def execute_agent_query(
    *,
    agent: Any,
    ctx: Any,
    query: str,
    db: Optional[AsyncSession] = None,
    trace_id: Optional[str] = None,
) -> ChatResponse:
    """
    Central execution entrypoint for chat route.
    Agents can optionally provide `execute_via_core(...)`; otherwise this keeps
    backward-compatible legacy delegation.
    """
    explicit_executor = None
    cls = type(agent)
    cls_executor = getattr(cls, "execute_via_core", None)
    if callable(cls_executor):
        explicit_executor = getattr(agent, "execute_via_core", None)
    else:
        inst_dict = getattr(agent, "__dict__", {})
        if isinstance(inst_dict, dict) and "execute_via_core" in inst_dict:
            explicit_executor = inst_dict.get("execute_via_core")

    if callable(explicit_executor):
        return await explicit_executor(ctx=ctx, query=query, db=db, trace_id=trace_id)

    process = getattr(agent, "process", None)
    if callable(process):
        logger.warning(
            "core.facade.legacy_delegate agent=%s",
            getattr(getattr(agent, "metadata", None), "agent_id", getattr(agent, "agent_id", "unknown")),
        )
        return await process(ctx, query)

    raise RuntimeError("Agent has no execute_via_core/process entrypoint")
