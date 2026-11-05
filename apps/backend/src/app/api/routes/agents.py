from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.agents.registry import register_defaults, registry
from app.core.policy.config import AGENT_POLICIES

router = APIRouter()


class AgentCatalogItem(BaseModel):
    id: str = Field(..., description="Agent ID used by /api/chat")
    display_name: str = Field(..., description="Safe UI name")
    enabled: bool = Field(..., description="True if agent is registered/runnable")
    category: Optional[str] = Field(default=None, description="Category hint from policy")
    notes: List[str] = Field(default_factory=list, description="Non-sensitive UI notes")
    class_name: Optional[str] = Field(default=None, description="Runtime class name when enabled")
    has_policy: bool = Field(default=False, description="True if agent has policy entry")
    default_scope: Optional[str] = Field(default=None)
    max_security_level: Optional[int] = Field(default=None)


def _scope_name(scope: Any) -> Optional[str]:
    if scope is None:
        return None
    return str(getattr(scope, "value", scope))


def _build_catalog(registered: Dict[str, Dict[str, Any]]) -> List[AgentCatalogItem]:
    policy_ids = set(AGENT_POLICIES.keys())
    reg_ids = set(registered.keys())
    all_ids = sorted(policy_ids | reg_ids)

    items: List[AgentCatalogItem] = []
    for agent_id in all_ids:
        reg = registered.get(agent_id) or {}
        policy = AGENT_POLICIES.get(agent_id)
        enabled = bool(reg)

        notes: List[str] = []
        if policy and not enabled:
            notes.append("Configured in policy but implementation is not registered.")
        if enabled and not policy:
            notes.append("Registered at runtime but no policy entry found.")

        items.append(
            AgentCatalogItem(
                id=agent_id,
                display_name=str(reg.get("name") or agent_id),
                enabled=enabled,
                category=_scope_name(getattr(policy, "default_scope", None)) if policy else None,
                notes=notes,
                class_name=str(reg.get("class")) if reg.get("class") else None,
                has_policy=bool(policy),
                default_scope=_scope_name(getattr(policy, "default_scope", None)) if policy else None,
                max_security_level=getattr(policy, "max_security_level", None) if policy else None,
            )
        )

    # Show runnable agents first, then disabled ones.
    return sorted(items, key=lambda x: (not x.enabled, x.id))


@router.get("/agents", response_model=List[AgentCatalogItem], tags=["agents"])
async def list_agents() -> List[AgentCatalogItem]:
    # Defensive: ensure registry is hydrated even if startup hook was skipped in tests/tools.
    if not registry.list_agents():
        register_defaults()
    return _build_catalog(registry.list_agents())
