# app/main.py
from __future__ import annotations

import inspect
import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text as sql_text

from app.config import settings
from app.core.logging import setup_logging
from app.core import db_sql
from app.core import db_sql
from app.schemas.chat import ChatResponse

# Soft dependency: Cache
try:
    from app.core.cache import cache_ping
except Exception:  # pragma: no cover
    cache_ping = None  # type: ignore

# Soft dependency: Qdrant (assume async client)
try:
    from app.core.db_vector import qdrant_client
except Exception:  # pragma: no cover
    qdrant_client = None  # type: ignore


def _parse_cors_origins() -> Dict[str, Any]:
    """
    settings.CORS_ORIGINS: "http://localhost:3000,https://abc.com"
    Neu khong co -> dev: ["*"]
    Luu y: allow_credentials=True khong hop voi allow_origins=["*"] (browser se chan).
    """
    raw = str(getattr(settings, "CORS_ORIGINS", "") or "").strip()
    if not raw:
        origins = ["*"]
    else:
        origins = [o.strip() for o in raw.split(",") if o.strip()]

    if "*" in origins:
        return {"allow_origins": ["*"], "allow_credentials": False}
    return {"allow_origins": origins, "allow_credentials": True}


async def _maybe_await(x):
    return await x if inspect.isawaitable(x) else x


# 1) Setup logging (idempotent)
setup_logging()
logger = logging.getLogger("app.main")

from contextlib import asynccontextmanager
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    # C0: Runtime fail-closed validation (must be first)
    try:
        settings.runtime_validate()
        logger.info("✅ Runtime validation passed")
    except RuntimeError as e:
        logger.critical(f"❌ Runtime validation failed: {e}")
        raise
    
    rerank_enabled = bool(getattr(settings, "RERANK_ENABLED", False))
    warmup_on_startup = bool(getattr(settings, "RERANK_WARMUP_ON_STARTUP", True))

    if rerank_enabled and warmup_on_startup:
        try:
            from app.core.llm.rerank import warmup_reranker
            await asyncio.to_thread(warmup_reranker)
            logger.info("✅ Reranker model warmed up")
        except Exception as e:
            # Non-fatal: system still runs, but first rerank may fallback
            logger.exception("❌ Reranker warmup failed: %s", e)

    # Warmup embedding
    try:
        from app.core.llm import embed_texts
        await embed_texts(["warmup"])
        logger.info("✅ Embedding model warmed up")
    except Exception as e:
        logger.warning("❌ Embedding warmup failed: %s", e)

    # Hydrate Agent Registry
    try:
        from app.agents.registry import register_defaults
        register_defaults()
        logger.info("✅ Agent Registry Hydrated")
    except Exception as e:
        logger.exception("❌ Failed to register default agents: %s", e)

    yield

    # --- SHUTDOWN ---
    # (optional) cleanup resources

# 2) FastAPI app
env_mode = str(getattr(settings, "ENV_MODE", "dev")).lower()
app = FastAPI(
    title="AI Gov Chat Backend",
    version="1.0.0",
    docs_url="/docs" if env_mode in ("dev", "debug", "local") else None,
    lifespan=lifespan,
)

from app.api.routes.chat import router as chat_router
from app.api.routes.sql_debug import router as sql_debug_router
from app.api.routes.meeting import router as meeting_router
from app.api.routes.agents import router as agents_router
from app.api.routes.docs import router as docs_router

app.include_router(chat_router, prefix=settings.API_PREFIX)
app.include_router(sql_debug_router, prefix=settings.API_PREFIX)
app.include_router(meeting_router, prefix=settings.API_PREFIX)
app.include_router(agents_router, prefix=settings.API_PREFIX)
app.include_router(docs_router, prefix=settings.API_PREFIX)

from app.api.routes.temp_docs import router as temp_docs_router
app.include_router(temp_docs_router, prefix="/api") # /api/temp/...

from app.api.routes.metrics import router as metrics_router
app.include_router(metrics_router) # /metrics (no prefix typically, or /api/metrics if preferred. User asked for /metrics)

from app.api.routes.ops_console import router as ops_console_router
app.include_router(ops_console_router) # /ops

# 3) CORS (quan trong cho Frontend)
cors_cfg = _parse_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_cfg["allow_origins"],
    allow_credentials=cors_cfg["allow_credentials"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4) Health checks
@app.get("/health")
async def health_check():
    """Liveness probe: container con song."""
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness_check():
    """
    Readiness probe:
    - Postgres: CRITICAL
    - Qdrant: CRITICAL cho RAG
    - Redis: SOFT (hong thi van chay)
    """
    status: Dict[str, Any] = {"database": "unknown", "vector_db": "unknown", "cache": "unknown"}
    ready = True

    # Cache (soft)
    if cache_ping is None:
        status["cache"] = "disabled"
    else:
        try:
            status["cache"] = "ok" if bool(await cache_ping()) else "failed"
        except Exception as e:
            logger.warning("Readiness - Redis ping failed: %s", str(e))
            status["cache"] = "failed"

    # Postgres (critical)
    try:
        async for session in db_sql.get_async_db():
            await session.execute(sql_text("SELECT 1"))
            break
        status["database"] = "ok"
    except Exception as e:
        logger.warning("Readiness - Postgres failed: %s", str(e))
        status["database"] = "failed"
        ready = False

    # Qdrant (critical)
    try:
        if qdrant_client is None:
            raise RuntimeError("Qdrant client not initialized")
        # async client: get_collections() (neu sync thi _maybe_await se handle)
        await _maybe_await(qdrant_client.get_collections())
        status["vector_db"] = "ok"
    except Exception as e:
        logger.warning("Readiness - Qdrant failed: %s", str(e))
        status["vector_db"] = "failed"
        ready = False

    if not ready:
        raise HTTPException(status_code=503, detail=status)

    return status


# 5) Chat endpoint (non-stream MVP)
# 5) Chat endpoint (Removed - see app/api/routes/chat.py)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
