
# apps/backend/src/app/core/policy/types.py
from dataclasses import dataclass
from typing import Optional
from app.core.taxonomy import GeoLevel

@dataclass(frozen=True)
class UserContext:
    tenant_id: str
    role: Optional[str] = None
    department_id: Optional[str] = None
    security_level: Optional[int] = None # User's clearance
    geo_code: Optional[str] = None
    geo_level: Optional[GeoLevel] = None
    scope: Optional[str] = None # "PUBLIC", "INTERNAL", "RESTRICTED"
