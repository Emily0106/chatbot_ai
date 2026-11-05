from __future__ import annotations

import hashlib
import hmac
import html
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import settings
from app.core.audit.audit import audit_event
from app.core.cache import cache_get_tenant_epoch, cache_incr_tenant_epoch
from app.core.ops.ingestion_adapter import IngestionOpsClient

router = APIRouter()


def _ops_enabled_or_404() -> None:
    if not bool(getattr(settings, "OPS_CONSOLE_ENABLED", False)):
        raise HTTPException(status_code=404, detail="Not Found")


def _expected_admin_key() -> str:
    return str(getattr(settings, "OPS_ADMIN_KEY", "") or "").strip()


def _cookie_token(expected_key: str) -> str:
    raw = f"ops-console::{expected_key}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def _trace_id(request: Request) -> str:
    return (
        request.headers.get("x-request-id")
        or request.headers.get("X-Request-Id")
        or request.headers.get("x-trace-id")
        or request.headers.get("X-Trace-Id")
        or uuid.uuid4().hex
    )


def _parse_is_deleted(v: Optional[str]) -> Optional[bool]:
    if v is None or str(v).strip() == "":
        return None
    x = str(v).strip().lower()
    if x in {"1", "true", "yes", "y"}:
        return True
    if x in {"0", "false", "no", "n"}:
        return False
    raise HTTPException(status_code=400, detail="is_deleted must be true|false")


def require_ops_admin(request: Request) -> Dict[str, str]:
    _ops_enabled_or_404()
    expected = _expected_admin_key()
    if not expected:
        raise HTTPException(status_code=503, detail="OPS_ADMIN_KEY is not configured")

    header_key = request.headers.get("X-Admin-Key")
    cookie_value = request.cookies.get("ops_admin_token")

    if header_key is not None:
        if not hmac.compare_digest(header_key, expected):
            raise HTTPException(status_code=403, detail="Invalid admin key")
        actor = request.headers.get("X-Admin-Actor") or (request.client.host if request.client else "ops_admin")
        return {"actor_id": str(actor), "auth_via": "header"}

    if cookie_value:
        if not hmac.compare_digest(cookie_value, _cookie_token(expected)):
            raise HTTPException(status_code=403, detail="Invalid admin session")
        actor = request.headers.get("X-Admin-Actor") or "ops_admin_cookie"
        return {"actor_id": str(actor), "auth_via": "cookie"}

    raise HTTPException(status_code=401, detail="Missing X-Admin-Key header")


def _ops_client() -> IngestionOpsClient:
    return IngestionOpsClient()


def _render_rows_jobs(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<tr><td colspan='8'>No jobs</td></tr>"
    out: List[str] = []
    for row in rows:
        out.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('job_id') or ''))}</td>"
            f"<td>{html.escape(str(row.get('job_type') or row.get('status') or ''))}</td>"
            f"<td>{html.escape(str(row.get('status') or ''))}</td>"
            f"<td>{html.escape(str(row.get('progress') or ''))}</td>"
            f"<td>{html.escape(str(row.get('doc_id') or ''))}</td>"
            f"<td>{html.escape(str(row.get('created_at') or ''))}</td>"
            f"<td>{html.escape(str(row.get('updated_at') or ''))}</td>"
            f"<td>{html.escape(str(row.get('error') or row.get('last_error') or ''))}</td>"
            "</tr>"
        )
    return "".join(out)


def _render_rows_docs(rows: List[Dict[str, Any]], tenant_id: str) -> str:
    if not rows:
        return "<tr><td colspan='10'>No documents</td></tr>"
    out: List[str] = []
    for row in rows:
        doc_id = str(row.get("doc_id") or "")
        out.append(
            "<tr>"
            f"<td>{html.escape(doc_id)}</td>"
            f"<td>{html.escape(str(row.get('title') or ''))}</td>"
            f"<td>{html.escape(str(row.get('scope') or ''))}</td>"
            f"<td>{html.escape(str(row.get('doc_type') or row.get('doc_category') or ''))}</td>"
            f"<td>{html.escape(str(row.get('security_level') or ''))}</td>"
            f"<td>{html.escape(str(row.get('is_deleted')))}</td>"
            f"<td>{html.escape(str(row.get('chunks_count') or 0))}</td>"
            f"<td>{html.escape(str(row.get('rows_count') or 0))}</td>"
            f"<td>{html.escape(str(row.get('created_at') or ''))}</td>"
            "<td>"
            f"<button onclick=\"runAction('reindex', '{html.escape(tenant_id)}', '{html.escape(doc_id)}')\">Reindex</button>"
            f"<button onclick=\"runAction('delete', '{html.escape(tenant_id)}', '{html.escape(doc_id)}')\">Delete</button>"
            "</td>"
            "</tr>"
        )
    return "".join(out)


def _render_ops_html(
    *,
    tenant_id: str,
    scope: str,
    doc_type: str,
    is_deleted: str,
    jobs: List[Dict[str, Any]],
    docs: List[Dict[str, Any]],
    epoch: Optional[int],
    epoch_healthy: bool,
    load_error: str,
    action_message: str,
) -> str:
    safe_tenant = html.escape(tenant_id)
    safe_scope = html.escape(scope)
    safe_doc_type = html.escape(doc_type)
    safe_is_deleted = html.escape(is_deleted)
    safe_load_error = html.escape(load_error)
    safe_action_message = html.escape(action_message)
    epoch_txt = str(epoch if epoch is not None else "N/A")
    epoch_health_txt = "healthy" if epoch_healthy else "unavailable"

    selected_all = "selected" if safe_is_deleted == "" else ""
    selected_false = "selected" if safe_is_deleted == "false" else ""
    selected_true = "selected" if safe_is_deleted == "true" else ""
    action_class = "ok" if safe_action_message else "muted"
    jobs_html = _render_rows_jobs(jobs)
    docs_html = _render_rows_docs(docs, tenant_id)

    parts: List[str] = [
        "<!doctype html>",
        "<html>",
        "<head>",
        '  <meta charset="utf-8" />',
        "  <title>Ops Console</title>",
        "  <style>",
        "    body { font-family: sans-serif; margin: 24px; }",
        "    table { border-collapse: collapse; width: 100%; margin-top: 8px; }",
        "    th, td { border: 1px solid #ddd; padding: 6px; font-size: 12px; text-align: left; vertical-align: top; }",
        "    .row { margin-bottom: 12px; }",
        "    .muted { color: #666; }",
        "    .error { color: #a00; }",
        "    .ok { color: #0a0; }",
        "    button { margin-right: 6px; }",
        "    .section { margin-top: 24px; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <h1>Ops Console (Internal)</h1>",
        '  <div class="row muted">Tenant filter is required before data fetch to avoid cross-tenant exposure.</div>',
        "",
        '  <form method="get" action="/ops" class="row">',
        f'    <label>tenant_id <input name="tenant_id" value="{safe_tenant}" /></label>',
        f'    <label>scope <input name="scope" value="{safe_scope}" /></label>',
        f'    <label>doc_type <input name="doc_type" value="{safe_doc_type}" /></label>',
        "    <label>is_deleted",
        '      <select name="is_deleted">',
        f'        <option value="" {selected_all}>all</option>',
        f'        <option value="false" {selected_false}>false</option>',
        f'        <option value="true" {selected_true}>true</option>',
        "      </select>",
        "    </label>",
        '    <button type="submit">Load</button>',
        "  </form>",
        "",
        '  <div class="row">',
        '    <button onclick="bumpEpoch()">Bump Tenant Epoch</button>',
        '    <form method="post" action="/ops/logout" style="display:inline">',
        '      <button type="submit">Logout</button>',
        "    </form>",
        "  </div>",
        "",
        f'  <div id="action-result" class="row {action_class}">{safe_action_message}</div>',
        f'  <div class="row error">{safe_load_error}</div>',
        "",
        '  <div class="section">',
        "    <h2>RAG Debug</h2>",
        f"    <div>tenant_epoch: <strong>{html.escape(epoch_txt)}</strong> ({html.escape(epoch_health_txt)})</div>",
        "  </div>",
        "",
        '  <div class="section">',
        "    <h2>Ingestion Jobs</h2>",
        "    <table>",
        "      <thead>",
        "        <tr>",
        "          <th>job_id</th><th>type</th><th>status</th><th>progress</th><th>doc_id</th><th>created_at</th><th>updated_at</th><th>error</th>",
        "        </tr>",
        "      </thead>",
        f"      <tbody>{jobs_html}</tbody>",
        "    </table>",
        "  </div>",
        "",
        '  <div class="section">',
        "    <h2>Documents</h2>",
        "    <table>",
        "      <thead>",
        "        <tr>",
        "          <th>doc_id</th><th>title</th><th>scope</th><th>doc_type</th><th>security</th><th>is_deleted</th><th>chunks</th><th>rows</th><th>created_at</th><th>actions</th>",
        "        </tr>",
        "      </thead>",
        f"      <tbody>{docs_html}</tbody>",
        "    </table>",
        "  </div>",
        "",
        "  <script>",
        "    async function runAction(kind, tenantId, docId) {",
        "      if (!tenantId || !docId) {",
        "        document.getElementById('action-result').textContent = 'tenant_id/doc_id are required';",
        "        return;",
        "      }",
        "      const form = new URLSearchParams();",
        "      form.append('tenant_id', tenantId);",
        "      form.append('doc_id', docId);",
        "      const endpoint = kind === 'delete' ? '/ops/action/delete' : '/ops/action/reindex';",
        "      const res = await fetch(endpoint, {",
        "        method: 'POST',",
        "        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },",
        "        body: form.toString(),",
        "      });",
        "      const data = await res.json();",
        "      document.getElementById('action-result').textContent = JSON.stringify(data);",
        "    }",
        "",
        "    async function bumpEpoch() {",
        "      const tenantId = new URLSearchParams(window.location.search).get('tenant_id');",
        "      if (!tenantId) {",
        "        document.getElementById('action-result').textContent = 'tenant_id is required';",
        "        return;",
        "      }",
        "      const form = new URLSearchParams();",
        "      form.append('tenant_id', tenantId);",
        "      const res = await fetch('/ops/action/bump-epoch', {",
        "        method: 'POST',",
        "        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },",
        "        body: form.toString(),",
        "      });",
        "      const data = await res.json();",
        "      document.getElementById('action-result').textContent = JSON.stringify(data);",
        "      if (res.ok) {",
        "        window.location.reload();",
        "      }",
        "    }",
        "  </script>",
        "</body>",
        "</html>",
    ]
    return "\n".join(parts)


@router.get("/ops/login", response_class=HTMLResponse)
async def ops_login_page() -> HTMLResponse:
    _ops_enabled_or_404()
    return HTMLResponse(
        """<!doctype html>
<html><body>
  <h1>Ops Console Login</h1>
  <form method="post" action="/ops/login">
    <label>X-Admin-Key <input type="password" name="admin_key" /></label>
    <button type="submit">Login</button>
  </form>
</body></html>"""
    )


@router.post("/ops/login")
async def ops_login_submit(admin_key: str = Form(...)) -> RedirectResponse:
    _ops_enabled_or_404()
    expected = _expected_admin_key()
    if not expected:
        raise HTTPException(status_code=503, detail="OPS_ADMIN_KEY is not configured")
    if not hmac.compare_digest(str(admin_key), expected):
        raise HTTPException(status_code=403, detail="Invalid admin key")

    resp = RedirectResponse(url="/ops", status_code=303)
    resp.set_cookie("ops_admin_token", _cookie_token(expected), httponly=True, samesite="strict", max_age=3600)
    return resp


@router.post("/ops/logout")
async def ops_logout() -> RedirectResponse:
    _ops_enabled_or_404()
    resp = RedirectResponse(url="/ops/login", status_code=303)
    resp.delete_cookie("ops_admin_token")
    return resp


@router.get("/ops", response_class=HTMLResponse)
async def ops_console(
    request: Request,
    tenant_id: str = Query(default=""),
    scope: str = Query(default=""),
    doc_type: str = Query(default=""),
    is_deleted: str = Query(default=""),
    admin: Dict[str, str] = Depends(require_ops_admin),
) -> HTMLResponse:
    client = _ops_client()
    jobs: List[Dict[str, Any]] = []
    docs: List[Dict[str, Any]] = []
    epoch: Optional[int] = None
    epoch_healthy = False
    load_error = ""

    tenant = str(tenant_id or "").strip()
    if tenant:
        try:
            jobs = await client.list_jobs(tenant_id=tenant, limit=100)
            docs = await client.list_documents(
                tenant_id=tenant,
                scope=(scope or "").strip() or None,
                doc_type=(doc_type or "").strip() or None,
                is_deleted=_parse_is_deleted(is_deleted),
                limit=100,
            )
            epoch, epoch_healthy = await cache_get_tenant_epoch(tenant)
        except Exception as e:
            load_error = str(e)[:500]
    else:
        load_error = "tenant_id is required before querying jobs/documents."

    action_message = str(request.query_params.get("message", "") or "")
    html_body = _render_ops_html(
        tenant_id=tenant,
        scope=str(scope or ""),
        doc_type=str(doc_type or ""),
        is_deleted=str(is_deleted or ""),
        jobs=jobs,
        docs=docs,
        epoch=epoch,
        epoch_healthy=epoch_healthy,
        load_error=load_error,
        action_message=action_message,
    )

    resp = HTMLResponse(html_body)
    # Convenience: valid header auth upgrades to a short-lived cookie session.
    if admin.get("auth_via") == "header":
        expected = _expected_admin_key()
        if expected:
            resp.set_cookie("ops_admin_token", _cookie_token(expected), httponly=True, samesite="strict", max_age=3600)
    return resp


@router.post("/ops/action/delete")
async def ops_action_delete(
    request: Request,
    tenant_id: str = Form(...),
    doc_id: str = Form(...),
    admin: Dict[str, str] = Depends(require_ops_admin),
) -> JSONResponse:
    tenant = str(tenant_id or "").strip()
    did = str(doc_id or "").strip()
    if not tenant or not did:
        raise HTTPException(status_code=400, detail="tenant_id and doc_id are required")

    trace_id = _trace_id(request)
    client = _ops_client()
    try:
        result = await client.delete_doc(tenant_id=tenant, doc_id=did)
    except Exception as e:
        audit_event(
            "ops.action",
            request_id=trace_id,
            action="delete",
            tenant_id=tenant,
            doc_id=did,
            actor=admin.get("actor_id"),
            status="error",
            error=str(e)[:300],
        )
        raise HTTPException(status_code=502, detail=str(e))

    audit_event(
        "ops.action",
        request_id=trace_id,
        action="delete",
        tenant_id=tenant,
        doc_id=did,
        actor=admin.get("actor_id"),
        status="ok",
    )
    return JSONResponse({"ok": True, "action": "delete", "tenant_id": tenant, "doc_id": did, "result": result})


@router.post("/ops/action/reindex")
async def ops_action_reindex(
    request: Request,
    tenant_id: str = Form(...),
    doc_id: str = Form(...),
    admin: Dict[str, str] = Depends(require_ops_admin),
) -> JSONResponse:
    tenant = str(tenant_id or "").strip()
    did = str(doc_id or "").strip()
    if not tenant or not did:
        raise HTTPException(status_code=400, detail="tenant_id and doc_id are required")

    trace_id = _trace_id(request)
    client = _ops_client()
    try:
        result = await client.reindex_doc(tenant_id=tenant, doc_id=did)
    except Exception as e:
        audit_event(
            "ops.action",
            request_id=trace_id,
            action="reindex",
            tenant_id=tenant,
            doc_id=did,
            actor=admin.get("actor_id"),
            status="error",
            error=str(e)[:300],
        )
        raise HTTPException(status_code=502, detail=str(e))

    audit_event(
        "ops.action",
        request_id=trace_id,
        action="reindex",
        tenant_id=tenant,
        doc_id=did,
        actor=admin.get("actor_id"),
        status="ok",
    )
    return JSONResponse({"ok": True, "action": "reindex", "tenant_id": tenant, "doc_id": did, "result": result})


@router.post("/ops/action/bump-epoch")
async def ops_action_bump_epoch(
    request: Request,
    tenant_id: str = Form(...),
    admin: Dict[str, str] = Depends(require_ops_admin),
) -> JSONResponse:
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    trace_id = _trace_id(request)
    new_epoch, healthy = await cache_incr_tenant_epoch(tenant)
    if not healthy:
        audit_event(
            "ops.action",
            request_id=trace_id,
            action="bump_epoch",
            tenant_id=tenant,
            actor=admin.get("actor_id"),
            status="error",
            error="redis_unavailable",
        )
        raise HTTPException(status_code=503, detail="Redis unavailable")

    audit_event(
        "ops.action",
        request_id=trace_id,
        action="bump_epoch",
        tenant_id=tenant,
        actor=admin.get("actor_id"),
        status="ok",
        new_epoch=new_epoch,
    )
    return JSONResponse({"ok": True, "action": "bump_epoch", "tenant_id": tenant, "new_epoch": int(new_epoch or 0)})
