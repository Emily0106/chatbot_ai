import hmac
from typing import Optional
from fastapi import Header, HTTPException
from pydantic import BaseModel
from app.core.taxonomy import TenantId, DepartmentId, GeoCode, IngestionError
from app.core.config import settings


from enum import Enum

class UserRole(str, Enum):
    CITIZEN = "citizen"
    OFFICER = "officer"
    CHAIRMAN = "chairman"
    ADMIN = "admin"

class TrustedContext(BaseModel):
    tenant_id: TenantId
    department_id: Optional[DepartmentId] = None
    geo_code: Optional[GeoCode] = None
    user_role: UserRole = UserRole.CITIZEN
    is_trusted: bool = True


def require_internal_token(
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
) -> None:
    """
    Service-to-service guard for ingestion APIs that trust internal context headers.
    """
    expected = str(getattr(settings, "INGEST_INTERNAL_TOKEN", "") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="INGEST_INTERNAL_TOKEN is not configured")
    if x_internal_token is None:
        raise HTTPException(status_code=401, detail="Missing X-Internal-Token header")
    if not hmac.compare_digest(str(x_internal_token), expected):
        raise HTTPException(status_code=403, detail="Invalid internal token")

def get_trusted_context(
    x_govai_tenant_id: str = Header(..., alias="X-GOVAI-TENANT-ID"),
    x_govai_department_id: Optional[str] = Header(None, alias="X-GOVAI-DEPARTMENT-ID"),
    x_govai_geo_code: Optional[str] = Header(None, alias="X-GOVAI-GEO-CODE"),
    x_govai_user_role: str = Header("citizen", alias="X-GOVAI-USER-ROLE"),
) -> TrustedContext:
    """
    Extracts trusted context from internal headers.
    In production, these headers MUST be stripped by the edge gateway from public traffic,
    and only injected by the Authentication Service.
    
    Fail-Closed: If tenant_id is missing (enforced by FastAPI '...'), reject.
    """
    if not x_govai_tenant_id:
        # Should be caught by FastAPI, but double check
        raise HTTPException(
            status_code=403, 
            detail={"code": IngestionError.ERR_MISSING_TENANT_CONTEXT, "message": "Missing Tenant ID"}
        )

    print(f"DEBUG AUTH: header_role='{x_govai_user_role}' header_tenant='{x_govai_tenant_id}'")
    try:
        role = UserRole(x_govai_user_role)
    except ValueError:
        # Fallback to citizen or fail? Fail-safe: default to citizen if unknown, 
        # but for Admin/Officer actions we will check specific roles.
        # Let's default to citizen if invalid to avoid 500s on bad headers, 
        # effectively denying admin rights.
        role = UserRole.CITIZEN

    return TrustedContext(
        tenant_id=TenantId(x_govai_tenant_id),
        department_id=DepartmentId(x_govai_department_id) if x_govai_department_id else None,
        geo_code=GeoCode(x_govai_geo_code) if x_govai_geo_code else None,
        user_role=role
    )
