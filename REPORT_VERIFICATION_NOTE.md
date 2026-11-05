# REPORT VERIFICATION NOTE

**Date:** 2026-02-05
**Status:** Reality Check Complete

## Verification Findings

| Claim in Deep Audit Report | Status | Evidence | Notes / Impact |
| :--- | :--- | :--- | :--- |
| **1. Tenant ID from Request Body** | **TRUE** | `apps/backend/src/app/api/routes/chat.py:117` `tenant_id = getattr(payload, "tenant_id", None)` | **CRITICAL P0**. Client controls data boundary. |
| **2. No Auth Middleare** | **TRUE** | `apps/backend/src/app/main.py` has no `add_middleware` for Auth. Comment confirms: `No auth for now (handled by Gateway/Nginx).` | **CRITICAL P0**. API is public. |
| **3. SQL Injection (f-string)** | **TRUE** | `apps/backend/src/app/core/db_sql.py:84` `sql = text(f"""..."""` | **CRITICAL P0**. SQL constructed via string formatting. |
| **4. Health Endpoints Exist** | **TRUE** | `main.py` has `/health` and `/health/ready`. `ops.py` has `/api/ops/health`. | **OK**. Basic observability exists. |
| **5. Missing Agent Registration** | **FALSE** | `apps/backend/src/app/agents/registry.py:113-133` | **CORRECTION**. `Calendar`, `Meeting`, `Economy`, `Land`, `Social` ARE registered. Report was outdated or hallucinated this gap. |
| **6. Requirements-CI Lightweight** | **TRUE** | `requirements-ci.txt` lines 1-17 | **OK**. Excludes `torch`, `sentence-transformers`. |
| **7. CI_MODE Dummy Defaults** | **TRUE** | `apps/backend/src/app/config.py` | `OPENAI_API_KEY`, `POSTGRES_USER` etc have defaults if `CI_MODE`. |
| **8. Smoke Test Agents** | **PARTIAL** | `verify_agent_flow.py` checks `citizen`, `legal`, `accurate_people`. | Limited coverage. |

## Evidence Output

**1. tenant_id usage (chat.py):**
```bash
117:    tenant_id = getattr(payload, "tenant_id", None)
118:    if not tenant_id:
119:        yield f"event: error\ndata: {json.dumps({'code': 403, 'message': 'Missing tenant_id'})}\n\n"
...
208:    tenant_id = getattr(payload, "tenant_id", None)
448:            tenant_id = getattr(payload, "tenant_id", None)
```

**2. Auth Middleware (main.py):**
```bash
apps/backend/src/app/main.py:9:from fastapi.middleware.cors import CORSMiddleware
# No other middleware found
apps/backend/src/app/api/routes/metrics.py:12:    No auth for now (handled by Gateway/Nginx).
```

**3. SQL Injection (db_sql.py):**
```bash
84:    sql = text(f"""
140:            f"""
157:            f"""
```

**4. Agent Registry (registry.py):**
```bash
128:    registry.register(MeetingAgent())
129:    registry.register(CalendarAgent())
130:    registry.register(EconomyAgent())
131:    registry.register(DocManagerAgent())
132:    registry.register(LandAgent())
133:    registry.register(SocialAgent())
```

**5. Test Status:**
```text
ERROR apps/backend/src/test_agent_certification.py
E   ModuleNotFoundError: No module named 'core_shared'
# Implication: Local dev environment needs PYTHONPATH setup to run tests, unlike CI which sets it.
```

## Delta vs Deep Audit Report
1. **Agent Registration:** The Report claimed 7+ agents were unregistered. **Reality:** They ARE registered in `apps/backend/src/app/agents/registry.py`. This P1 task is likely already done or requires only verification of functionality, not registration code.
2. **Health Checks:** Report claimed minimal health checks, but implementation seems standard/adequate for now.
3. **Agent Router:** Confirmed missing (logic is manual `agent_id` in `chat.py`).

## Implications for Phase A
- **P0 Items (Auth, SQLi, Tenant)**: Confirmed valid and urgent.
- **P1 Items (Register Agents)**: Downgrade priority or change to "Verify Agent Logic" since registration lines exist.
- **Immediate Action**: Fix `PYTHONPATH` for local `pytest` to ensure we can verifying changes safely.
