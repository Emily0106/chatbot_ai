from __future__ import annotations

from typing import Any, Dict, List, Optional
import os

import httpx

from app.config import settings


class IngestionOpsClient:
    """
    Backend adapter for ingestion-admin/document operations.
    All calls are tenant-scoped via trusted headers.
    """

    def __init__(self, *, base_url: Optional[str] = None, timeout_s: Optional[float] = None):
        raw_base = (
            base_url
            or (getattr(settings, "OPS_INGESTION_BASE_URL", "") or "").strip()
            or (getattr(settings, "INGESTION_BASE_URL", "") or "").strip()
            or os.getenv("OPS_INGESTION_BASE_URL", "").strip()
            or "http://ingest-api:8010"
        )
        self.base_url = raw_base.rstrip("/")
        self.timeout_s = float(timeout_s or getattr(settings, "OPS_HTTP_TIMEOUT_S", 12.0) or 12.0)
        self.internal_token = str(
            getattr(settings, "INGEST_INTERNAL_TOKEN", "") or os.getenv("INGEST_INTERNAL_TOKEN", "") or ""
        ).strip()

    def _headers(self, tenant_id: str) -> Dict[str, str]:
        if not self.internal_token:
            raise RuntimeError("INGEST_INTERNAL_TOKEN is required for ingestion adapter")
        return {
            "X-GOVAI-TENANT-ID": str(tenant_id),
            "X-GOVAI-USER-ROLE": "admin",
            "X-Internal-Token": self.internal_token,
        }

    async def _request(
        self,
        *,
        method: str,
        path: str,
        tenant_id: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.request(
                method=method,
                url=url,
                headers=self._headers(tenant_id),
                params=params,
                json=json_body,
            )

        if resp.status_code >= 400:
            detail: Any
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:500]
            raise RuntimeError(f"Ingestion request failed {resp.status_code} path={path} detail={detail}")

        if not resp.content:
            return {}
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}

    async def list_jobs(self, *, tenant_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        out = await self._request(
            method="GET",
            path="/api/v1/admin/jobs",
            tenant_id=tenant_id,
            params={"limit": int(limit)},
        )
        return list(out or [])

    async def list_documents(
        self,
        *,
        tenant_id: str,
        scope: Optional[str] = None,
        doc_type: Optional[str] = None,
        is_deleted: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"limit": int(limit)}
        if scope:
            params["scope"] = scope
        if doc_type:
            params["doc_type"] = doc_type
        if is_deleted is not None:
            params["is_deleted"] = bool(is_deleted)

        out = await self._request(
            method="GET",
            path="/api/v1/admin/documents",
            tenant_id=tenant_id,
            params=params,
        )
        return list(out or [])

    async def delete_doc(self, *, tenant_id: str, doc_id: str) -> Dict[str, Any]:
        out = await self._request(
            method="DELETE",
            path=f"/api/v1/docs/{doc_id}",
            tenant_id=tenant_id,
        )
        return dict(out or {})

    async def reindex_doc(self, *, tenant_id: str, doc_id: str) -> Dict[str, Any]:
        out = await self._request(
            method="POST",
            path=f"/api/v1/docs/{doc_id}/reindex",
            tenant_id=tenant_id,
        )
        return dict(out or {})
