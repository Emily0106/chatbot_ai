"""
AGENT TOOL NOTE
- agent_id: calendar_agent
- business: Tra cứu lịch làm việc, đặt phòng họp
- data lane:
  - RAG: NO (API based)
  - allowed_doc_types: []
- tools (implemented now):
  - NONE (returns NOT_IMPLEMENTED refusal)
- tools (TODO for dev):
  - external_api_call("calendar", payload)
- policy:
  - scope: internal
- refusal:
  - Default: NOT_IMPLEMENTED (until API tool is added)
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

class CalendarAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="calendar_agent",
        name="Trợ lý Lịch làm việc",
        description="Tra cứu lịch và đặt phòng họp.",
        doc_types=[]
    )
    
    policy = AgentPolicy(
        required_clearance=1 
    )

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        # TODO(dev): Implement API call here.
        # Example:
        # result = await external_api_call(ctx, "calendar_service", {"query": query})
        
        # Current: Fail-closed / Not Implemented
        return self._make_refusal(
            RefusalCode.NOT_IMPLEMENTED, 
            "Chức năng tra cứu lịch chưa được kết nối."
        )
