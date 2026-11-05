# app/agents/base.py
from __future__ import annotations

import logging
import os
import time
import uuid
import inspect
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, AsyncGenerator

from app.schemas.chat import ChatRequest, ChatResponse, Citation, ChatMeta
from app.agents.contract import (
    AgentMetadata, 
    AgentPolicy, 
    TrustedContext, 
    AgentResponse, 
    RefusalCode,
    AgentRefusal
)

class BaseAgent(ABC):
    """
    Base class for Gov-AI Agents (PR-B0 Contract).
    
    Contract:
    - metadata: AgentMetadata (ID, Name, DocTypes)
    - policy: AgentPolicy (Scopes, Clearance)
    - process(ctx, query): Core Logic
    """
    
    # Defaults (Override in subclass)
    metadata: AgentMetadata
    policy: AgentPolicy = AgentPolicy()
    
    # Legacy/Convenience
    default_top_k: int = 8

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"agents.{self.__class__.__name__}")
        self.debug_enabled = os.getenv("APP_DEBUG", "0").lower() in ("1", "true", "yes")

    # ---------------------------------------------------------
    # NEW CONTRACT (PR-B0)
    # ---------------------------------------------------------
    @abstractmethod
    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        """
        Main execution method.
        MUST fail-closed if context is insufficient.
        """
        raise NotImplementedError

    async def process_stream(self, ctx: TrustedContext, query: str) -> AsyncGenerator[AgentResponse, None]:
        """
        Streaming support. Default: yield single response.
        """
        resp = await self.process(ctx, query)
        yield resp

    # ---------------------------------------------------------
    # LEGACY ADAPTER (Bridging old ChatRequest to new Contract)
    # ---------------------------------------------------------
    async def handle(self, req: ChatRequest) -> ChatResponse:
        """
        Adapter method for legacy `chat.py` calls (if any remain).
        Converts ChatRequest -> TrustedContext -> process().
        """
        # 1. Build TrustedContext
        # Note: In a real system, this comes from Middleware/JWT. 
        # Here we trust the ChatRequest has been sanitized by API layer.
        ctx = TrustedContext(
            tenant_id=req.tenant_id or "default",
            user_id=getattr(req, "user_id", "anonymous"), # Missing in ChatRequest schema usually
            department_id=getattr(req, "context", {}).get("department_id"),
            geo_code=getattr(req, "context", {}).get("geo_code"),
            security_level=int(getattr(req, "security_level", 1)),
            request_payload=req.model_dump()
        )
        
        query = req.message or req.query or ""
        
        # 2. Check Policy (Fail-Closed)
        if not self._check_policy(ctx):
             return self._make_refusal(RefusalCode.INSUFFICIENT_CLEARANCE, "Context policy mismatch")

        # 3. Process
        try:
             start = time.perf_counter()
             resp = await self.process(ctx, query)
             
             # Fill Meta latency if missing
             if resp.meta.latency_ms is None:
                 resp.meta.latency_ms = int((time.perf_counter() - start) * 1000)
                 
             return resp
             
        except Exception as e:
             self.logger.exception(f"Agent Process Error: {e}")
             return self._make_refusal(RefusalCode.NO_EVIDENCE, f"System Error: {str(e)}")

    def _check_policy(self, ctx: TrustedContext) -> bool:
        """Validate if ctx meets this agent's policy."""
        # 1. Clearance
        if ctx.security_level < self.policy.required_clearance:
            self.logger.warning(f"Policy Fail: Clearance {ctx.security_level} < {self.policy.required_clearance}")
            return False
            
        # 2. Scopes
        if self.policy.required_scopes:
            # Check if ctx.token_scopes has intersection or superset? 
            # Usually strict: Need ALL required? Or ANY? 
            # Let's assume ANY for now or skip if token_scopes empty in MVP.
            pass
            
        # 3. Dept Match
        if self.policy.requires_department_match:
             # Validate dept logic (omitted for MVP)
             pass
             
        return True

    def _make_refusal(self, code: RefusalCode, msg: str) -> AgentResponse:
        """Return standardized refusal."""
        return AgentResponse(
            answer=msg,
            citations=[],
            meta={
                "refusal": {"code": code, "message": msg},
                "is_refusal": True
            }
        )

    # ---------------------------------------------------------
    # HELPERS (Retained for utilities if subclass uses them)
    # ---------------------------------------------------------
    def build_meta(self, **kwargs) -> ChatMeta:
        return ChatMeta(**kwargs)

