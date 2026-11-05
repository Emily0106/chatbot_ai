
# apps/backend/src/app/core/policy/errors.py
class PolicyError(Exception):
    """Base class for policy exceptions"""
    pass

class MissingContextError(PolicyError):
    """
    Raised when user context is missing a required field (e.g. department_id)
    requested by the agent's isolation policy.
    """
    def __init__(self, field: str, agent_id: str):
        self.field = field
        self.agent_id = agent_id
        super().__init__(f"Agent {agent_id} isolation policy requires context field: {field}")
