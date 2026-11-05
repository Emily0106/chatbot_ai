from typing import Any, Dict
from fastapi import Request

from app.security.auth import AuthClaims
from app.agents.contract import TrustedContext

def build_trusted_context(
    claims: AuthClaims,
    request: Request = None,
    payload: Any = None,
) -> TrustedContext:
    """
    Constructs a TrustedContext from validated AuthClaims.
    
    CRITICAL SECURITY LOGIC (B4):
    - tenant_id MUST come from claims.tenant_id (Server-side).
    - Client-provided tenant_id in payload is IGNORED to prevent spoofing.
    """
    
    # Validation: Ensure claims has tenant_id (should be guaranteed by auth.py, but safe guard)
    if not claims.tenant_id:
        raise ValueError("AuthClaims missing tenant_id. Misconfigured API Key?")

    return TrustedContext(
        tenant_id=claims.tenant_id,
        user_id=claims.subject or "api_key_user",
        security_level=claims.security_level,
        request_id=getattr(request.state, "trace_id", "unknown") if request else "unknown",
        geo_code=claims.geo_code,
        # We can attach original payload for debugging/audit, but Agent should rely on ctx.tenant_id
    )
