# app/core/logging.py
from __future__ import annotations

import logging
import sys

from app.config import settings


def setup_logging() -> None:
    """
    Setup logging idempotent (khong bi trung handler khi uvicorn --reload).
    Co milliseconds de debug latency.
    """
    env_mode = str(getattr(settings, "ENV_MODE", "dev")).lower()
    level = logging.DEBUG if env_mode in ("dev", "debug", "local") else logging.INFO

    # asctime + msecs -> co milliseconds
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)

    # Idempotent: clear old handlers (uvicorn reload)
    root.handlers = []
    root.addHandler(handler)

    # Giảm ồn thư viện
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
