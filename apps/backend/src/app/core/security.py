# app/core/security.py
from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException


async def get_current_tenant_id(
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> str:
    """
    MVP: lay tenant_id tu header X-Tenant-ID.
    Production: thay the bang decode JWT Bearer token -> tenant_id.

    Co che:
    - Neu REQUIRE_TENANT_HEADER=1: bat buoc co X-Tenant-ID, thieu la 401.
    - Neu khong: cho phep fallback de dev local.
    """
    require = os.getenv("REQUIRE_TENANT_HEADER", "0").strip() in ("1", "true", "True", "yes", "YES")

    if not x_tenant_id:
        if require:
            raise HTTPException(status_code=401, detail="Missing X-Tenant-ID")
        return os.getenv("DEFAULT_TENANT_ID", "xa_mac_dinh")

    return x_tenant_id.strip()
