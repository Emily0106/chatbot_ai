import os
import json
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

# Header scheme for FastAPI Swagger UI support
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

class AuthClaims(BaseModel):
    """
    Authenticated claims attached to request.state.user
    Used for Tenant Isolation and RBAC (Step B4, C3)
    """
    tenant_id: str
    subject: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    security_level: int = 1
    allowed_agents: Optional[List[str]] = None
    geo_code: Optional[str] = None

def _load_api_keys() -> Dict[str, dict]:
    """
    Load API keys from JSON env var.
    
    Supports two formats:
    1. New (C3): {"key": {"tenant_id": "t1", "roles": ["user"], "security_level": 1, "allowed_agents": [...], "geo_code": "..."}}
    2. Legacy: {"key": "tenant_id_string"}
    
    Fail-closed: Returns empty dict if env var invalid/missing.
    """
    raw = os.getenv("API_KEYS_JSON", "")
    if not raw:
        # Default dev key logic: ONLY valid if explicit dev/local environment or CI
        # Fail-closed in prod/staging (security baseline)
        env_mode = str(getattr(settings, "ENV_MODE", "prod")).lower()
        if settings.CI_MODE or env_mode in ("dev", "local", "debug"):
            return {
                "dev-key-123": {
                    "tenant_id": "default", 
                    "roles": ["admin"], 
                    "security_level": 5,
                    "geo_code": "default"
                }
            }
        # In PROD/STAGING with no header -> Empty dict -> Fail Closed
        return {}
    
    try:
        parsed = json.loads(raw)
        # Normalize legacy string format to new dict format
        normalized = {}
        for key, value in parsed.items():
            if isinstance(value, str):
                # Legacy format: "key": "tenant_id"
                normalized[key] = {
                    "tenant_id": value,
                    "roles": ["user"],
                    "security_level": 1,
                    "geo_code": "default"
                }
            elif isinstance(value, dict):
                # New format: already a dict
                normalized[key] = value
            else:
                # Invalid format, skip this key
                continue
        return normalized
    except json.JSONDecodeError:
        return {}

def authenticate_api_key(
    request: Request,
    api_key: str = Security(api_key_header)
) -> AuthClaims:
    """
    Validate X-API-Key header.
    Fail-closed: 401 if missing/invalid.
    """
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    
    keys_db = _load_api_keys()
    user_data = keys_db.get(api_key)
    
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    # Construct claims
    # Validate required fields (fail-closed if DB config is bad)
    if "tenant_id" not in user_data:
        raise HTTPException(status_code=403, detail="Misconfigured Key: Missing tenant scope")
        
    claims = AuthClaims(
        tenant_id=user_data["tenant_id"],
        subject=user_data.get("subject"),
        roles=user_data.get("roles", []),
        security_level=user_data.get("security_level", 1),
        allowed_agents=user_data.get("allowed_agents"),
        geo_code=user_data.get("geo_code")
    )
    
    # Attach to request state for downstream use (Step B4)
    request.state.user = claims
    return claims

def require_auth(claims: AuthClaims = Security(authenticate_api_key)) -> AuthClaims:
    """Dependency for Router"""
    return claims
