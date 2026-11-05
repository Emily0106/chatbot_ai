from typing import Tuple
from fastapi import HTTPException
from app.schemas.chat import ChatRequest
from app.security.auth import AuthClaims
from app.security import policy
from app.core.metrics import CHAT_REQUESTS_TOTAL, AUTHZ_DENIALS_TOTAL
from app.core.audit.audit import audit_event, compute_query_hash

def authorize_chat_request(
    payload: ChatRequest, 
    claims: AuthClaims, 
    trace_id: str
) -> Tuple[str, int]:
    """
    Shared authorization logic for blocking and streaming paths.
    Enforces RBAC and Security Level.
    Returns: (agent_id, effective_security_level)
    """
    agent_id = getattr(payload, "agent_id", "citizen") or "citizen"
    # Standardize stream label (avoid truthy string issues)
    is_stream = "true" if getattr(payload, "stream", False) else "false"
    
    # PII-Safe Query Info
    q_str = getattr(payload, "message", "") or getattr(payload, "query", "") or ""
    q_len = len(q_str)
    q_hash = compute_query_hash(q_str) if q_str else None
    
    # 1. Check agent access
    if not policy.can_use_agent(claims, agent_id):
        # Audit denial
        audit_event(
            "authz.denied",
            trace_id=trace_id,
            endpoint="/api/chat",
            method="POST",
            tenant_id=claims.tenant_id,
            subject=claims.subject,
            roles=claims.roles,
            agent_id=agent_id,
            reason="agent_not_allowed",
            allowed_agents=claims.allowed_agents,
            allowed_agents_count=len(claims.allowed_agents or []),
            requested_security_level=getattr(payload, "security_level", 1),
            user_security_level=claims.security_level,
            query_len=q_len,
            query_sha1=q_hash,
            stream=getattr(payload, "stream", False)
        )
        # Metrics
        CHAT_REQUESTS_TOTAL.labels(
            agent_id=agent_id, 
            lane="all", 
            stream=is_stream, 
            status="denied"
        ).inc()
        AUTHZ_DENIALS_TOTAL.labels(
             agent_id=agent_id,
             reason="agent_not_allowed",
             stream=is_stream
        ).inc()
        
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: Agent '{agent_id}' not permitted for your role"
        )
    
    # 2. Enforce security level ceiling
    requested = getattr(payload, "security_level", 1)
    strict = policy.get_strict_mode()
    try:
        effective = policy.clamp_security_level(requested, claims.security_level, strict=strict)
    except ValueError as e:
        audit_event(
            "authz.denied",
            trace_id=trace_id,
            endpoint="/api/chat",
            method="POST",
            tenant_id=claims.tenant_id,
            subject=claims.subject,
            roles=claims.roles,
            agent_id=agent_id,
            reason="security_level_escalation",
            requested_level=requested,
            user_level=claims.security_level,
            allowed_agents_count=len(claims.allowed_agents or []),
            query_len=q_len,
            query_sha1=q_hash,
            stream=getattr(payload, "stream", False)
        )
        CHAT_REQUESTS_TOTAL.labels(
            agent_id=agent_id, 
            lane="all", 
            stream=is_stream, 
            status="denied"
        ).inc()
        AUTHZ_DENIALS_TOTAL.labels(
             agent_id=agent_id,
             reason="security_level_escalation",
             stream=is_stream
        ).inc()
        
        raise HTTPException(
            status_code=403,
            detail=f"Security level escalation denied: {str(e)}"
        )
        
    return agent_id, effective
