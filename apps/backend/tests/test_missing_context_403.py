
# apps/backend/tests/test_missing_context_403.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import HTTPException

from app.core.facade import CoreService, CoreResponse
from app.core.policy.types import UserContext
from app.core.policy.errors import MissingContextError
from app.core.policy.manager import PolicyManager

@pytest.mark.asyncio
async def test_missing_context_raises_403():
    """
    Test that facade catches MissingContextError and raises HTTPException 403.
    """
    service = CoreService()
    
    # Mock PolicyManager to raise MissingContextError
    with patch("app.core.facade.PolicyManager.enforce_filters") as mock_enforce:
        mock_enforce.side_effect = MissingContextError(field="department_id", agent_id="meeting_assist")
        
        with pytest.raises(HTTPException) as excinfo:
            await service.search(
                db=AsyncMock(),
                query="test",
                tenant_id="test_tenant",
                trace_id="test_trace",
                agent_id="meeting_assist"
            )
            
        assert excinfo.value.status_code == 403
        assert "missing_context:department_id" in excinfo.value.detail
