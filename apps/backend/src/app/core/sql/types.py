from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Literal

Lane = Literal["template", "slm", "manual"]

class SQLError(Exception): ...
class SecurityError(SQLError): ...
class ValidationError(SQLError): ...
class ExecutionError(SQLError): ...
class TimeoutError(ExecutionError): ...

@dataclass(frozen=True)
class SQLPolicy:
    tenant_column: str                 # e.g. "commune_id"
    allowed_relations: List[str]       # view whitelist
    allowed_columns: Optional[Dict[str, List[str]]] = None  # optional per-view col whitelist
    max_limit: int = 50
    statement_timeout_ms: int = 1500
    forbid_set_ops: bool = True        # UNION/INTERSECT/EXCEPT
    forbid_subquery: bool = False      # can be True for tighter phase-0
    forbid_join: bool = False
    max_joins: int = 3
    require_explicit_limit: bool = False  # if False, executor injects limit

@dataclass(frozen=True)
class UserContext:
    tenant_id: str
    user_role: str                     # e.g. "viewer/admin"
    user_id: Optional[str] = None
    trace_id: Optional[str] = None
    ip: Optional[str] = None

@dataclass(frozen=True)
class SafeSQL:
    sql: str                           # canonical SQL after AST transform
    params: Dict[str, Any]             # sanitized + injected (tenant_id, etc.)
    injected: Dict[str, Any]           # evidence of transforms
    fingerprint: str                   # hash for cache/log
