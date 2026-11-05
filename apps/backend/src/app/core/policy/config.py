
# apps/backend/src/app/core/policy/config.py
from dataclasses import dataclass, field
from typing import Literal, Set, Optional, Dict

from app.core.taxonomy import DocType, DataScope

@dataclass(frozen=True)
class AgentPolicy:
    agent_id: str
    allowed_doc_types: Set[DocType]
    allowed_scopes: Set[DataScope]
    isolation_level: Literal["none", "department", "geo"]
    max_security_level: Optional[int] = None # Enforce maximum security clearance agent can access
    default_scope: Optional[DataScope] = None # Default scope if UserContext.scope is missing

# SSoT: Agent Permission Definition
# This serves as the "License to Operate"
AGENT_POLICIES: Dict[str, AgentPolicy] = {
    # --- LEGACY / ALIASES ---
    "meeting_assistant": AgentPolicy(
        agent_id="meeting_assistant",
        allowed_doc_types={DocType.MEETING_TRANSCRIPT, DocType.MEETING_SCHEDULE},
        allowed_scopes={DataScope.INTERNAL},
        isolation_level="department", 
        max_security_level=3,
        default_scope=DataScope.INTERNAL
    ),
    "legal": AgentPolicy(
        agent_id="legal",
        allowed_doc_types={DocType.LAW, DocType.DECREE, DocType.CIRCULAR, DocType.DECISION},
        allowed_scopes={DataScope.PUBLIC},
        isolation_level="none",
        max_security_level=1,
        default_scope=DataScope.PUBLIC
    ),
    "citizen": AgentPolicy(
        agent_id="citizen",
        allowed_doc_types={DocType.ADMIN_PROCEDURE, DocType.PUBLIC_NEWS, DocType.LAW},
        allowed_scopes={DataScope.PUBLIC},
        isolation_level="geo",
        max_security_level=1,
        default_scope=DataScope.PUBLIC
    ),
    "officer": AgentPolicy(
        agent_id="officer",
        allowed_doc_types={DocType.ADMIN_PROCEDURE, DocType.PUBLIC_NEWS, DocType.LAW, DocType.MEETING_TRANSCRIPT, DocType.PLAN, DocType.OTHER},
        allowed_scopes={DataScope.PUBLIC, DataScope.INTERNAL, DataScope.RESTRICTED},
        isolation_level="department", 
        max_security_level=3,
        default_scope=DataScope.INTERNAL # Default to Internal for efficient work
    ),

    # --- WAVE 1 AGENTS ---
    "citizen_agent": AgentPolicy(
        agent_id="citizen_agent",
        allowed_doc_types={DocType.LAW, DocType.ADMIN_PROCEDURE, DocType.CITIZEN_GUIDE},
        allowed_scopes={DataScope.PUBLIC},
        isolation_level="none", 
        max_security_level=1,
        default_scope=DataScope.PUBLIC
    ),
    "report_agent": AgentPolicy(
        agent_id="report_agent",
        allowed_doc_types={DocType.INTERNAL_REPORT, DocType.STATS},
        allowed_scopes={DataScope.INTERNAL},
        isolation_level="department", 
        max_security_level=2,
        default_scope=DataScope.INTERNAL
    ),
    "health_agent": AgentPolicy(
        agent_id="health_agent",
        allowed_doc_types={DocType.HEALTH_GUIDELINES, DocType.DISEASE_INFO},
        allowed_scopes={DataScope.PUBLIC},
        isolation_level="none",
        max_security_level=1,
        default_scope=DataScope.PUBLIC
    ),
    "culture_agent": AgentPolicy(
        agent_id="culture_agent",
        allowed_doc_types={DocType.CULTURE_GUIDE, DocType.TOURISM_SPOTS},
        allowed_scopes={DataScope.PUBLIC},
        isolation_level="none", 
        max_security_level=1,
        default_scope=DataScope.PUBLIC
    ),
    "agri_agent": AgentPolicy(
        agent_id="agri_agent",
        allowed_doc_types={DocType.AGRI_TECH},
        allowed_scopes={DataScope.PUBLIC},
        isolation_level="none",
        max_security_level=1,
        default_scope=DataScope.PUBLIC
    ),

    # --- WAVE 2 AGENTS ---
    "meeting_agent": AgentPolicy(
        agent_id="meeting_agent",
        allowed_doc_types={DocType.MEETING_MINUTES, DocType.MEETING_TRANSCRIPT},
        allowed_scopes={DataScope.INTERNAL},
        isolation_level="none", 
        max_security_level=2,
        default_scope=DataScope.INTERNAL
    ),
    "calendar_agent": AgentPolicy(
        agent_id="calendar_agent",
        allowed_doc_types=set(), 
        allowed_scopes={DataScope.INTERNAL},
        isolation_level="none",
        max_security_level=2,
        default_scope=DataScope.INTERNAL
    ),
    "economy_agent": AgentPolicy(
        agent_id="economy_agent",
        allowed_doc_types={DocType.STATS, DocType.INTERNAL_REPORT},
        allowed_scopes={DataScope.INTERNAL},
        isolation_level="none", 
        max_security_level=2,
        default_scope=DataScope.INTERNAL
    ),
    "doc_manager": AgentPolicy(
        agent_id="doc_manager",
        allowed_doc_types={DocType.OFFICIAL_DOCUMENT},
        allowed_scopes={DataScope.INTERNAL},
        isolation_level="department", 
        max_security_level=2,
        default_scope=DataScope.INTERNAL
    ),
    "land_agent": AgentPolicy(
        agent_id="land_agent",
        allowed_doc_types={DocType.LAND_PLANNING, DocType.CONSTRUCTION_PERMIT},
        allowed_scopes={DataScope.RESTRICTED},
        isolation_level="geo", 
        max_security_level=2,
        default_scope=DataScope.RESTRICTED
    ),
    "social_agent": AgentPolicy(
        agent_id="social_agent",
        allowed_doc_types={DocType.SOCIAL_POLICY, DocType.WELFARE_POLICY},
        allowed_scopes={DataScope.RESTRICTED},
        isolation_level="department", 
        max_security_level=2,
        default_scope=DataScope.RESTRICTED
    ),
}
