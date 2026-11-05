from typing import Any, Dict, List, Optional
from sqlalchemy import text
from app.core.db_sql import get_async_db
from app.core.sql.validator import SQLValidator
from app.core.sql.types import Lane, SQLPolicy, SecurityError, ValidationError

import logging
import time
import hashlib

logger = logging.getLogger(__name__)

class SQLExecutor:
    def __init__(self):
        self.validator = SQLValidator()
        # Default Gov-grade policy
        self.policy = SQLPolicy(
            tenant_column="commune_id",
            allowed_relations=["view_people", "view_budget", "structured_rows"],
            max_limit=50,
            statement_timeout_ms=2000,
            forbid_set_ops=True,
            forbid_subquery=False, # Allow subqueries for now if needed, or True for strictness
            forbid_join=False
        )

    async def execute_safe(
        self,
        sql: str,
        tenant_id: str,
        params: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        *,
        policy: Optional[SQLPolicy] = None,
        lane: Lane = "template",
    ) -> Dict[str, Any]:
        """
        Validates and executes the SQL query safely.
        Returns: { "data": [...], "meta": {...} }
        """
        start_time = time.perf_counter()
        params = params or {}
        effective_policy = policy or self.policy
        
        # 1. Validate
        try:
            safe_sql_obj = self.validator.validate_and_transform(
                raw_sql=sql,
                params=params,
                tenant_id=tenant_id,
                policy=effective_policy,
                lane=lane,
            )
        except (SecurityError, ValidationError) as e:
            raise ValueError(f"SQL Validation Failed: {str(e)}")
        
        final_sql = safe_sql_obj.sql
        safe_params = safe_sql_obj.params
        
        # 2. Execute
        rows = []
        try:
            async for session in get_async_db():
                # Set statement timeout
                await session.execute(text(f"SET LOCAL statement_timeout = {effective_policy.statement_timeout_ms}"))
                
                # Execute with params
                result = await session.execute(text(final_sql), safe_params)
                keys = result.keys()
                for r in result.all():
                    rows.append(dict(zip(keys, r)))
                break # Only one session needed
        except Exception as e:
            logger.error(f"SQL Execution Error: {str(e)}", extra={"tenant_id": tenant_id, "trace_id": trace_id})
            raise RuntimeError(f"Database Execution Error: {str(e)}")
        finally:
            duration = (time.perf_counter() - start_time) * 1000
            logger.info(
                "SQL Executed",
                extra={
                    "tenant_id": tenant_id,
                    "trace_id": trace_id,
                    "duration_ms": round(duration, 2),
                    "row_count": len(rows),
                    "sql_fingerprint": safe_sql_obj.fingerprint,
                    "injected": safe_sql_obj.injected,
                    "params_masked": self._mask_params(safe_params)
                }
            )
            
        return {
            "data": rows,
            "meta": {
                "executed_sql": final_sql, # Only for debug
                "row_count": len(rows),
                "duration_ms": round(duration, 2)
            }
        }
            
    def _mask_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Masks sensitive parameters for logging.
        """
        masked = {}
        sensitive_keys = {"cccd", "phone", "email", "address", "name", "fullname", "search", "q_ascii"}
        for k, v in params.items():
            if k.lower() in sensitive_keys or any(s in k.lower() for s in sensitive_keys):
                masked[k] = "<PII_MASKED>"
            else:
                masked[k] = v
        return masked
