import pytest
from unittest.mock import AsyncMock, patch
from app.core.rate_limit import RateLimiter, RateLimitResult
from app.config import settings

@pytest.mark.asyncio
async def test_token_bucket_allow_deny(monkeypatch):
    """
    Simulate Lua script return values:
    - [1, 0] -> Allowed
    - [0, 500] -> Denied, retry in 500ms
    """
    rl = RateLimiter()
    
    # Mock _eval to simulate redis return
    mock_eval = AsyncMock()
    monkeypatch.setattr(rl, "_eval", mock_eval)
    
    # Case 1: Allow
    mock_eval.return_value = [1, 0]
    res = await rl.allow_request("t1")
    assert res.allowed is True
    assert res.reason == "ok"
    
    # Case 2: Deny
    mock_eval.return_value = [0, 500]
    res = await rl.allow_request("t1")
    assert res.allowed is False
    assert res.reason == "rate_limit_exceeded"
    assert res.retry_after_s == 0.5

@pytest.mark.asyncio
async def test_inflight_allow_deny(monkeypatch):
    rl = RateLimiter()
    mock_eval = AsyncMock()
    monkeypatch.setattr(rl, "_eval", mock_eval)
    
    # Case 1: Allow (count=1)
    mock_eval.return_value = [1, 1]
    res = await rl.enter_inflight("t1")
    assert res.allowed is True
    
    # Case 2: Deny (limit reached)
    mock_eval.return_value = [0, 9]
    res = await rl.enter_inflight("t1")
    assert res.allowed is False
    assert res.reason == "inflight_limit_exceeded"

@pytest.mark.asyncio
async def test_fail_open_on_redis_error(monkeypatch):
    """
    If Redis fails (returns None from _eval wrapper), allow.
    """
    rl = RateLimiter()
    mock_eval = AsyncMock(return_value=None)
    monkeypatch.setattr(rl, "_eval", mock_eval)
    
    res = await rl.allow_request("t1")
    assert res.allowed is True
    assert res.reason == "redis_unavailable"
