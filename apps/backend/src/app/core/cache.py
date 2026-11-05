# app/core/cache.py
from __future__ import annotations

import logging
from typing import Optional, Tuple

import redis.asyncio as redis
from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None
_init_failed_logged: bool = False


def _get_client() -> Optional[redis.Redis]:
    """
    Lazy init Redis client với cấu hình Fail-fast.
    Soft dependency: co Redis thi dung, khong co thi bo qua (khong crash app).
    """
    global _client, _init_failed_logged

    if _client is not None:
        return _client

    redis_url = getattr(settings, "REDIS_URL", "") or ""
    if not redis_url:
        return None

    try:
        _client = redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            # --- PRODUCTION FAIL-FAST ---
            socket_timeout=float(getattr(settings, "REDIS_SOCKET_TIMEOUT", 2.0)),
            socket_connect_timeout=float(getattr(settings, "REDIS_CONNECT_TIMEOUT", 2.0)),
            retry_on_timeout=False,
        )
        return _client
    except Exception as e:
        # log 1 lan de tranh spam
        if not _init_failed_logged:
            logger.warning("Redis init failed (cache disabled): %s", str(e))
            _init_failed_logged = True
        _client = None
        return None


async def cache_get(key: str) -> Optional[str]:
    client = _get_client()
    if not client:
        return None
    try:
        return await client.get(key)
    except Exception as e:
        logger.warning("Redis GET failed key='%s': %s", key, str(e))
        return None


async def cache_set(key: str, value: str, ttl_seconds: int = 300) -> None:
    client = _get_client()
    if not client:
        return
    try:
        await client.set(key, value, ex=int(ttl_seconds))
    except Exception as e:
        logger.warning("Redis SET failed key='%s': %s", key, str(e))


async def cache_delete(key: str) -> None:
    client = _get_client()
    if not client:
        return
    try:
        await client.delete(key)
    except Exception as e:
        logger.warning("Redis DELETE failed key='%s': %s", key, str(e))


async def cache_ping() -> bool:
    """Health check (optional)."""
    client = _get_client()
    if not client:
        return False
    try:
        return bool(await client.ping())
    except Exception as e:
        logger.warning("Redis PING failed: %s", str(e))
        return False


def tenant_epoch_key(tenant_id: str) -> str:
    tid = str(tenant_id or "").strip()
    if not tid:
        raise ValueError("tenant_id is required for epoch key")
    return f"rag:tenant_epoch:{tid}"


async def cache_get_tenant_epoch(tenant_id: str) -> Tuple[int, bool]:
    """
    Returns (epoch, healthy).
    - healthy=True  : Redis reachable and value decoded (or missing -> epoch=0)
    - healthy=False : Redis unavailable/read failed -> caller should bypass cache
    """
    client = _get_client()
    if not client:
        return 0, False

    key = tenant_epoch_key(tenant_id)
    try:
        raw = await client.get(key)
    except Exception as e:
        logger.warning("Redis GET epoch failed key='%s': %s", key, str(e))
        return 0, False

    if raw is None:
        return 0, True

    try:
        return int(raw), True
    except Exception:
        logger.warning("Redis epoch value invalid key='%s' value=%r", key, raw)
        return 0, False


async def cache_incr_tenant_epoch(tenant_id: str) -> Tuple[Optional[int], bool]:
    """
    Best-effort tenant epoch bump.
    Returns (new_epoch, healthy):
    - healthy=True  : Redis reachable and INCR succeeded
    - healthy=False : Redis unavailable / INCR failed
    """
    client = _get_client()
    if not client:
        return None, False

    key = tenant_epoch_key(tenant_id)
    try:
        new_epoch = await client.incr(key)
    except Exception as e:
        logger.warning("Redis INCR epoch failed key='%s': %s", key, str(e))
        return None, False

    try:
        return int(new_epoch), True
    except Exception:
        logger.warning("Redis INCR epoch invalid value key='%s' value=%r", key, new_epoch)
        return None, False
