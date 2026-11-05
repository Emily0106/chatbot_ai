from __future__ import annotations
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from app.schemas.chat import Citation, Handoff, ChatResponse

class RefusalCode(str, Enum):
    NO_EVIDENCE = "NO_EVIDENCE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    MISSING_CONTEXT = "MISSING_CONTEXT"
    INSUFFICIENT_CLEARANCE = "INSUFFICIENT_CLEARANCE"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

class AgentMetadata(BaseModel):
    agent_id: str
    name: str
    description: str
    doc_types: List[str] = Field(default_factory=list)

class AgentPolicy(BaseModel):
    required_scopes: List[str] = Field(default_factory=list)
    required_clearance: int = 1
    requires_department_match: bool = False
    requires_geo_match: bool = False
    required_context_fields: List[str] = Field(default_factory=list)

class TrustedContext(BaseModel):
    """
    Context secure (Trust Boundary) passed to agent.
    Derived from JWT/Middleware, NOT user input.
    """
    tenant_id: str
    user_id: str
    department_id: Optional[str] = None
    geo_code: Optional[str] = None
    security_level: int = 1
    token_scopes: List[str] = Field(default_factory=list)
    request_payload: Dict[str, Any] = Field(default_factory=dict) # Raw payload for legacy needs

# Helper for Refusal
class AgentRefusal(BaseModel):
    code: RefusalCode
    message: str

# Re-export or Alias
AgentResponse = ChatResponse
