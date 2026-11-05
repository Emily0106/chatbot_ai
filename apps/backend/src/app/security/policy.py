"""
Authorization Policy Module (RBAC + Security Level Enforcement)

Implements enterprise-grade authorization (AuthZ) for Gov-AI Backend.
Complements authentication (AuthN) with role-based access control and
security level enforcement.

Step C3: Authorization (RBAC) + Security-Level Enforcement
"""

import os
import logging
from typing import List, Optional
from app.security.auth import AuthClaims

logger = logging.getLogger(__name__)

# Default agent access by role
DEFAULT_AGENT_ACCESS = {
    "user": ["citizen", "legal", "universal", "people_lookup", "gov_assistant"],
    "admin": ["*"],  # Wildcard: access to all agents
}

def can_use_agent(claims: AuthClaims, agent_id: str) -> bool:
    """
    Check if user has permission to use the specified agent.
    
    Decision logic:
    1. If claims.allowed_agents is explicitly set → enforce allowlist
    2. Else use default role-based access
    
    Args:
        claims: Authenticated user claims
        agent_id: Agent identifier to check access for
        
    Returns:
        True if user can access agent, False otherwise
    """
    # 1. Explicit allowlist takes precedence
    if claims.allowed_agents is not None:
        return agent_id in claims.allowed_agents
    
    # 2. Role-based default access
    for role in claims.roles:
        allowed_agents = DEFAULT_AGENT_ACCESS.get(role, [])
        
        # Wildcard: admin can access all
        if "*" in allowed_agents:
            return True
        
        # Check if agent in role's allowlist
        if agent_id in allowed_agents:
            return True
    
    # Default deny (fail-closed)
    logger.warning(
        f"Agent access denied: tenant={claims.tenant_id}, "
        f"roles={claims.roles}, agent={agent_id}"
    )
    return False


def clamp_security_level(
    requested: Optional[int],
    user_max: int,
    strict: bool = True
) -> int:
    """
    Enforce security level ceiling for user requests.
    
    Security levels: 1 (public) to 5 (top secret)
    
    Args:
        requested: Security level requested in payload (None = default to 1)
        user_max: Maximum security level from user's claims
        strict: If True (staging/prod), raise ValueError on escalation
                If False (dev), clamp and log warning
                
    Returns:
        Effective security level (clamped to user_max)
        
    Raises:
        ValueError: If strict=True and requested > user_max
    """
    # Default to public if not specified
    if requested is None:
        requested = 1
    
    # Validate bounds
    if not (1 <= requested <= 5):
        logger.warning(f"Invalid security level requested: {requested}, defaulting to 1")
        requested = 1
    
    if not (1 <= user_max <= 5):
        logger.error(f"Invalid user security level: {user_max}, defaulting to 1")
        user_max = 1
    
    # Check for escalation attempt
    if requested > user_max:
        if strict:
            raise ValueError(
                f"Security level escalation denied: requested={requested}, "
                f"user_max={user_max}"
            )
        else:
            logger.warning(
                f"Security level clamped: requested={requested} -> clamped={user_max}"
            )
            return user_max
    
    return requested


def require_role(claims: AuthClaims, required_role: str) -> bool:
    """
    Check if user has the required role.
    
    Helper function for future admin-only endpoints.
    
    Args:
        claims: Authenticated user claims
        required_role: Role name to check for
        
    Returns:
        True if user has role, False otherwise
    """
    return required_role in claims.roles


from app.config import settings

def get_strict_mode() -> bool:
    """
    Determine if authorization should use strict mode.
    
    Strict mode (staging/prod): Fail with 403 on violations
    Relaxed mode (dev/ci): Clamp and log warnings
    
    Returns:
        True for strict mode, False for relaxed
    """
    env_mode = str(getattr(settings, "ENV_MODE", "prod")).lower()
    ci_mode = getattr(settings, "CI_MODE", False)
    
    # Strict in staging/prod, relaxed in dev/ci
    return env_mode in ["staging", "prod"] and not ci_mode
