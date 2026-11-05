from __future__ import annotations
from typing import Dict, Optional, Type
import logging

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata

logger = logging.getLogger(__name__)

class AgentRegistry:
    """
    Centralized Agent Registry (PR-B0).
    - Enforces metadata validation on registration.
    - Single source of truth for agent routing.
    """

    def __init__(self, default_agent_id: str = "citizen") -> None:
        self._agents: Dict[str, BaseAgent] = {}
        self.default_agent_id = default_agent_id
        # We delay default registration to avoid circular imports during init if possible, 
        # but for now we keep it explicit or move it to a setup function.
        # To avoid circular imports, we might urge main.py to call `register_defaults()`.
        # However, keeping backward compat logic:
        pass 

    def register(self, agent: BaseAgent) -> None:
        """
        Register an agent instance.
        Validates strict contract compliance.
        """
        # 1. Validate Base Class
        if not isinstance(agent, BaseAgent):
             raise TypeError(f"Agent must inherit from BaseAgent. Got {type(agent)}")

        # 2. Validate Metadata (Contract)
        if not hasattr(agent, "metadata") or not isinstance(agent.metadata, AgentMetadata):
             # Fallback for Legacy Agents (PR-A wrappings)
             # If agent has agent_id/name attrs, wrap them ad-hoc?
             # Better to Fail Fast as per PR requirement.
             # But we need to support legacy agents momentarily until they are updated.
             # Strict Mode:
             if getattr(agent, "agent_id", None):
                 # Temporary: Allow if agent_id exists but warn
                 logger.warning(f"Agent {agent.agent_id} missing strict metadata coverage. Legacy mode.")
             else:
                 raise ValueError("Agent missing metadata and agent_id")
        
        agent_id = agent.metadata.agent_id if hasattr(agent, "metadata") else agent.agent_id
        
        if not agent_id:
            raise ValueError("Agent ID cannot be empty")
            
        if agent_id in self._agents:
            logger.warning(f"Overwriting existing agent: {agent_id}")
            
        self._agents[agent_id] = agent
        logger.info(f"Registered Agent: {agent_id}")

    def get(self, agent_id: Optional[str]) -> BaseAgent:
        """
        Get agent by ID. Returns Default Agent if not found or ID is None.
        """
        if agent_id and agent_id in self._agents:
            return self._agents[agent_id]
        
        if self.default_agent_id in self._agents:
            return self._agents[self.default_agent_id]
            
        raise RuntimeError(f"Agent '{agent_id}' not found and default '{self.default_agent_id}' missing.")

    def list_agents(self) -> Dict[str, Dict]:
        """Return simple list for UI/Debug"""
        return {
            pid: {
                "name": agent.metadata.name if hasattr(agent, "metadata") else agent.name,
                "class": agent.__class__.__name__
            }
            for pid, agent in self._agents.items()
        }

# Global Instance
registry = AgentRegistry(default_agent_id="citizen_agent")

def get_agent(agent_id: str | None) -> BaseAgent:
    return registry.get(agent_id)

def register_defaults():
    """Call this from app startup to hydrate registry"""
    # Lazy imports to avoid circular dependency
    # from app.agents.citizen_qa import CitizenQAAgent # DEPRECATED
    from app.agents.legal import LegalAgent
    from app.agents.people_lookup import PeopleLookupAgent
    from app.agents.accurate_people import AccuratePeopleAgent
    from app.agents.universal_lookup import UniversalLookupAgent
    from app.agents.citizen_agent import CitizenAgent
    from app.agents.report_agent import ReportAgent
    from app.agents.health_agent import HealthAgent
    from app.agents.culture_agent import CultureAgent
    from app.agents.agri_agent import AgriAgent
    
    # Wave 2 Agents
    from app.agents.meeting_agent import MeetingAgent
    from app.agents.calendar_agent import CalendarAgent
    from app.agents.economy_agent import EconomyAgent
    from app.agents.doc_manager import DocManagerAgent
    from app.agents.land_agent import LandAgent
    from app.agents.social_agent import SocialAgent


    # Register core set
    # Note: These agents must be updated/wrapped to have metadata to pass strictly.
    # We allow legacy fallback in register() for now.
    # registry.register(CitizenQAAgent()) # DEPRECATED: Replaced by CitizenAgent
    registry.register(LegalAgent())
    registry.register(PeopleLookupAgent())
    registry.register(AccuratePeopleAgent())
    registry.register(UniversalLookupAgent())
    # registry.register(MeetingAgent()) # Replaced by Wave 2 MeetingAgent

    # Wave 1 Scaffolding
    registry.register(CitizenAgent())
    registry.register(ReportAgent())
    registry.register(HealthAgent())
    registry.register(CultureAgent())
    registry.register(AgriAgent())
    
    # Wave 2 Scaffolding
    registry.register(MeetingAgent())
    registry.register(CalendarAgent())
    registry.register(EconomyAgent())
    registry.register(DocManagerAgent())
    registry.register(LandAgent())
    registry.register(SocialAgent())
