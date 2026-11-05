# INGESTION DATA CONTRACT (SSoT)

> **Version:** 1.0.0
> **Status:** DRAFT (Implementing)
> **Enforcement:** Strict (Fail-Closed)

## 1. Core Principles
1.  **Trusted Context Only:** `tenant_id`, `department_id`, and `geo_code` MUST be extracted from a trusted source (JWT / Internal Headers). **NEVER** accept these from public form fields.
2.  **Fail-Closed API:** If required context is missing, reject with HTTP 400/403. **DO NOT** enqueue the job.
3.  **No Fake Defaults:** NEVER assign a default `tenant_id` to legacy data. Missing tenant = Quarantine.
4.  **Deterministic IDs:** IDs MUST be deterministic hashes.
5.  **Exact Schema:** Qdrant payload keys MUST match the contract (e.g., `doc_type`, NOT `doc_category`).

## 2. Chunk Payload Contract (Qdrant)

Every chunk in Qdrant MUST have this payload structure.

```json
{
  "tenant_id": "str (REQUIRED)",
  "doc_type": "str (Enum Value)",
  "scope": "str (Enum: INTERNAL, PUBLIC, RESTRICTED)",
  "security_level": "int (REQUIRED)",
  "department_id": "str (Required if scope=INTERNAL)",
  "geo_code": "str (Required if geo isolation enabled)",
  "domain": "str (Optional)",
  "document_id": "str (REQUIRED)",
  "chunk_id": "str (REQUIRED)"
}
```

### Field Definitions

| Field | Type | Required | Source of Truth | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `tenant_id` | `str` | ✅ Always | **Trusted Context** (JWT/Header) | Never from public form. |
| `doc_type` | `str` (Enum) | ✅ Always | Request Param | Maps to `DocType`. Replaces `doc_category`. |
| `scope` | `str` (Enum) | ✅ Always | Request Param | `PUBLIC`, `INTERNAL`, `RESTRICTED`. No default. |
| `security_level` | `int` | ✅ Always | Request Param | Access Control Level. |
| `department_id` | `str` | ✅ if `scope=INTERNAL` | **Trusted Context** | Required for internal documents. |
| `geo_code` | `str` | ✅ if enabled | **Trusted Context** | Replaces `commune_id`. |
| `domain` | `str` | Optional | Request Param | Sub-domain classifier. |
| `document_id` | `str` | ✅ Always | System (Hash) | Deterministic ID. |
| `chunk_id` | `str` | ✅ Always | System (Hash) | Deterministic ID. |

## 3. Trusted Context

Ingestion service relies on a **Trusted Context** passed from the API Gateway or Authentication Middleware.

**Required Claims/Headers:**
*   `tenant_id`: Identifies the tenant owner of the data.
*   `department_id`: Identifies the department (for Internal scope).
*   `geo_code`: Identifies the geographic region (for Geo isolation).

**Validation Rule:**
If `tenant_id` is missing or invalid in the trusted context, the request **MUST** be rejected immediately (HTTP 401/403).

## 4. Legacy Mapping

| Old Field | New Field | Migration Action |
| :--- | :--- | :--- |
| `doc_category` | `doc_type` | Rename key. Validate against Enum. |
| `commune_id` | `geo_code` | Rename key. |
| (Missing) | `tenant_id` | **QUARANTINE**. Do not backfill with default. |
| (Missing) | `security_level` | **QUARANTINE** or require manual intervention. |

## 5. Error Codes

| Code | HTTP Status | Description |
| :--- | :--- | :--- |
| `ERR_UNAUTHORIZED_CALLER` | 401 | Missing or invalid auth token. |
| `ERR_MISSING_TENANT_CONTEXT` | 403 | Authenticated but missing `tenant_id` claim. |
| `ERR_MISSING_DEPARTMENT_CONTEXT` | 403 | `scope=INTERNAL` but missing `department_id`. |
| `ERR_SCOPE_SECURITY_VIOLATION` | 403 | `security_level` too low for `RESTRICTED` scope. |
| `ERR_INVALID_DOC_TYPE` | 400 | `doc_type` not in Enum. |
| `ERR_INVALID_SCOPE` | 400 | `scope` not in Enum. |

