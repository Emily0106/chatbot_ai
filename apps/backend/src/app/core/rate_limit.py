from __future__ import annotations
import time
import logging
import asyncio
from typing import Optional, NamedTuple
from app.config import settings
from app.core.cache import _get_client

logger = logging.getLogger(__name__)

# -------------------------------------------------------------
# LUA SCRIPTS (ATOMIC)
# -------------------------------------------------------------

# Token Bucket Script
# KEYS[1] = bucket_key
# ARGV[1] = rate (tokens/sec)
# ARGV[2] = capacity (max tokens)
# ARGV[3] = now_ms (current timestamp)
# ARGV[4] = cost (default 1)
# Returns: {allowed (0/1), retry_after_ms}
SCRIPT_TOKEN_BUCKET = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local cap = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local info = redis.call("HMGET", key, "tokens", "ts")
local tokens = tonumber(info[1])
local ts = tonumber(info[2])

if not tokens then
    tokens = cap
    ts = now
end

-- Refill
local delta_ms = math.max(0, now - ts)
local refill = (delta_ms / 1000) * rate
tokens = math.min(cap, tokens + refill)

local allowed = 0
local retry_after = 0

if tokens >= cost then
    allowed = 1
    tokens = tokens - cost
else
    allowed = 0
    -- Time needed to get enough tokens
    local needed = cost - tokens
    retry_after = (needed / rate) * 1000
end

-- Update state
redis.call("HMSET", key, "tokens", tokens, "ts", now)
-- Expire key after enough time to be full + buffer (e.g. 60s)
redis.call("EXPIRE", key, 60)

return {allowed, retry_after}
"""

# Inflight Enter Script
# KEYS[1] = key
# ARGV[1] = limit
# ARGV[2] = ttl (seconds)
# Returns: {allowed (0/1), current_count}
SCRIPT_ENTER_COUNTER = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = redis.call("INCR", key)
if current == 1 then
    redis.call("EXPIRE", key, ttl)
end

if current > limit then
    redis.call("DECR", key)
    return {0, current - 1}
end

return {1, current}
"""

# Inflight Exit Script
# KEYS[1] = key
# Returns: current_count
SCRIPT_EXIT_COUNTER = """
local key = KEYS[1]
local val = redis.call("DECR", key)
if val < 0 then
    redis.call("SET", key, 0)
    val = 0
end
return val
"""

class RateLimitResult(NamedTuple):
    allowed: bool
    reason: str
    retry_after_s: float | None

class RateLimiter:
    def __init__(self):
        self.prefix = settings.RATE_LIMIT_REDIS_PREFIX
        self.timeout = settings.RATE_LIMIT_REDIS_TIMEOUT_S
        
    def _key(self, tenant_id: str, scope: str, lane: str = "") -> str:
        k = f"{self.prefix}:{scope}:{tenant_id}"
        if lane:
            k += f":{lane}"
        return k

    async def _eval(self, script: str, keys: list, args: list) -> any:
        client = _get_client()
        if not client:
            # Fail open if no redis
            return None
        
        try:
            # Use asyncio.wait_for to enforce strict timeout for Redis call
            # But redis-py async client handles socket timeout?
            # Config settings.RATE_LIMIT_REDIS_TIMEOUT_S suggests application level timeout logic
            # or relying on client socket_timeout.
            # Here we trust the client configuration (socket_timeout) but can add extra safety.
            return await client.eval(script, len(keys), *keys, *args)
        except Exception as e:
            logger.warning("RateLimiter redis error: %s", e)
            return None

    async def allow_request(self, tenant_id: str) -> RateLimitResult:
        if not settings.ENABLE_RATE_LIMITING:
            return RateLimitResult(True, "disabled", None)

        key = self._key(tenant_id, "tb:req")
        rate = settings.RATE_LIMIT_RPS
        cap = settings.RATE_LIMIT_BURST
        now_ms = int(time.time() * 1000)
        
        res = await self._eval(SCRIPT_TOKEN_BUCKET, [key], [rate, cap, now_ms, 1])
        
        if res is None:
            # Redis Fail Open - Metric
            from app.core.metrics import RATE_LIMIT_BLOCK_TOTAL
            RATE_LIMIT_BLOCK_TOTAL.labels(type="redis_failopen").inc()
            return RateLimitResult(True, "redis_unavailable", None)
            
        allowed, retry_ms = res
        if allowed:
            return RateLimitResult(True, "ok", None)
        else:
            # RPS Deny - Metric
            from app.core.metrics import RATE_LIMIT_BLOCK_TOTAL
            RATE_LIMIT_BLOCK_TOTAL.labels(type="rps").inc()
            return RateLimitResult(False, "rate_limit_exceeded", float(retry_ms)/1000.0)

    async def enter_inflight(self, tenant_id: str, lane: str = "all") -> RateLimitResult:
        if not settings.ENABLE_RATE_LIMITING:
            return RateLimitResult(True, "disabled", None)
            
        key = self._key(tenant_id, "inflight", lane)
        limit = settings.MAX_INFLIGHT_PER_TENANT
        ttl = 120 # guard check
        
        res = await self._eval(SCRIPT_ENTER_COUNTER, [key], [limit, ttl])
        
        if res is None:
             from app.core.metrics import RATE_LIMIT_BLOCK_TOTAL
             RATE_LIMIT_BLOCK_TOTAL.labels(type="redis_failopen").inc()
             return RateLimitResult(True, "redis_unavailable", None)
             
        allowed, _ = res
        if allowed:
            return RateLimitResult(True, "ok", None)
        else:
            from app.core.metrics import RATE_LIMIT_BLOCK_TOTAL
            RATE_LIMIT_BLOCK_TOTAL.labels(type="inflight").inc()
            return RateLimitResult(False, "inflight_limit_exceeded", None)

    async def exit_inflight(self, tenant_id: str, lane: str = "all") -> None:
        if not settings.ENABLE_RATE_LIMITING:
            return
            
        key = self._key(tenant_id, "inflight", lane)
        await self._eval(SCRIPT_EXIT_COUNTER, [key], [])

    async def enter_stream(self, tenant_id: str) -> RateLimitResult:
        if not settings.ENABLE_RATE_LIMITING:
            return RateLimitResult(True, "disabled", None)
            
        key = self._key(tenant_id, "streams")
        limit = settings.MAX_STREAMS_PER_TENANT
        ttl = settings.STREAM_TIMEOUT_S + 30 # Slightly more than stream timeout
        
        res = await self._eval(SCRIPT_ENTER_COUNTER, [key], [limit, ttl])
        
        if res is None:
            from app.core.metrics import RATE_LIMIT_BLOCK_TOTAL
            RATE_LIMIT_BLOCK_TOTAL.labels(type="redis_failopen").inc()
            return RateLimitResult(True, "redis_unavailable", None)
            
        allowed, _ = res
        if allowed:
            return RateLimitResult(True, "ok", None)
        else:
            from app.core.metrics import RATE_LIMIT_BLOCK_TOTAL
            RATE_LIMIT_BLOCK_TOTAL.labels(type="streams").inc()
            return RateLimitResult(False, "stream_limit_exceeded", None)

    async def exit_stream(self, tenant_id: str) -> None:
        if not settings.ENABLE_RATE_LIMITING:
            return
        key = self._key(tenant_id, "streams")
        await self._eval(SCRIPT_EXIT_COUNTER, [key], [])
    
    # Global instance
rate_limiter = RateLimiter()
