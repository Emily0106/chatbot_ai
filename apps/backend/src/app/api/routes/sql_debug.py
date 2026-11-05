from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
import logging

from app.core.sql.validator import SQLValidator
from app.core.sql.types import SQLPolicy, SecurityError, ValidationError, Lane
from app.api.routes.ops_console import require_ops_admin

router = APIRouter(prefix="/debug/sql", tags=["debug"])
logger = logging.getLogger(__name__)

class DebugSQLRequest(BaseModel):
    sql: str
    tenant_id: str = "debug_tenant"
    params: Dict[str, Any] = {}

class DebugSQLResponse(BaseModel):
    original_sql: str
    safe_sql: Optional[str] = None
    injected_info: Dict[str, Any] = {}
    params_masked: Dict[str, Any] = {}
    status: str # "ALLOWED" | "BLOCKED"
    error: Optional[str] = None

def _mask_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Masks sensitive parameters for logging/debug.
    Duplicated from SQLExecutor to ensure consistency without instantiation overhead.
    """
    masked = {}
    sensitive_keys = {"cccd", "phone", "email", "address", "name", "fullname", "search", "q_ascii"}
    for k, v in params.items():
        if k.lower() in sensitive_keys or any(s in k.lower() for s in sensitive_keys):
            masked[k] = "<PII_MASKED>"
        else:
            masked[k] = v
    return masked

@router.post("/plan", response_model=DebugSQLResponse)
async def debug_sql_plan(
    req: DebugSQLRequest,
    _admin: Dict[str, str] = Depends(require_ops_admin),
):
    """
    Dry-run SQL validation and transformation.
    Does NOT execute against DB.
    """
    del _admin
    validator = SQLValidator()
    # Use default policy for debug, or we could allow passing policy in request
    policy = SQLPolicy(
        tenant_column="commune_id",
        allowed_relations=["view_people", "view_budget", "structured_rows"],
        max_limit=50,
        forbid_set_ops=True,
        forbid_subquery=False,
        forbid_join=False
    )
    
    try:
        safe_sql_obj = validator.validate_and_transform(
            raw_sql=req.sql,
            params=req.params,
            tenant_id=req.tenant_id,
            policy=policy,
            lane="template"
        )
        
        return DebugSQLResponse(
            original_sql=req.sql,
            safe_sql=safe_sql_obj.sql,
            injected_info=safe_sql_obj.injected,
            params_masked=_mask_params(safe_sql_obj.params),
            status="ALLOWED"
        )
        
    except (SecurityError, ValidationError) as e:
        return DebugSQLResponse(
            original_sql=req.sql,
            status="BLOCKED",
            error=str(e)
        )
    except Exception as e:
        logger.exception("Debug SQL Plan failed")
        return DebugSQLResponse(
            original_sql=req.sql,
            status="BLOCKED",
            error=f"System Error: {str(e)}"
        )
