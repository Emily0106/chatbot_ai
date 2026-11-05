# QA Certification Report: Gov-AI Agents (Wave 1 & Wave 2)
**Date:** 2026-02-02
**Author:** QA Engineering (Automated)
**Status:** ✅ PASS

## Executive Summary
This report certifies that the 11 scaffolded agents (Wave 1 and Wave 2) meet the **Zero-Trust**, **Fail-Closed**, and **Metadata-Scoped** requirements. 
Testing verified strict import restrictions, refusal semantics on empty data, and correct policy enforcement (geo/department/clearance) when data is present (mocked positive flow).

## Agents Certified
1. `citizen_agent`: Public, RAG (Law/Procedure).
2. `report_agent`: Internal (Lvl 2), RAG (Reports).
3. `health_agent`: Public, RAG (Health).
4. `culture_agent`: Public, RAG (Culture/Tourism).
5. `agri_agent`: Public, RAG (Agriculture).
6. `meeting_agent`: Internal, RAG (Minutes).
7. `calendar_agent`: Internal, Tool Only (Not Implemented).
8. `economy_agent`: Internal (Lvl 2), RAG + SQL(TODO).
9. `doc_manager`: Internal + Dept Match, RAG.
10. `land_agent`: Restricted (Lvl 2) + Geo Match, RAG.
11. `social_agent`: Restricted (Lvl 2) + Dept Match, RAG.

## Test Matrix & Results

| Test Category | Requirement | Method | Result |
| :--- | :--- | :--- | :--- |
| **A. Registry** | 11 Agents exist, uniquely registered. | `test_registry_count_and_keys` | ✅ PASS |
| **B. Static Guards** | No forbidden imports (requests, psycopg2, etc.). | `test_zero_trust_static_analysis` | ✅ PASS |
| **C. Fail-Closed** | Returns `NO_EVIDENCE` (or valid refusal) on empty DB. | `test_fail_closed_on_empty_rag` | ✅ PASS |
| **D. Positive Flow** | RAG filters (doc_type) are correctly constructed. | `test_positive_flow_with_policy_check` | ✅ PASS |
| **E. Policy** | Geo and Department context passed to RAG. | `test_positive_flow_with_policy_check` | ✅ PASS |
| **F. Pollution** | Agents do not request out-of-scope doc types. | `test_cross_agent_pollution_mocked` | ✅ PASS |

## Evidence Log

### 1. Pytest Results
```text
apps/backend/src/test_agent_certification.py ......                      [100%]
========================= 6 passed, 1 warning in 8.00s =========================
```

### 2. Static Analysis Proof
The static analysis scanned all 11 files and found **0 forbidden imports**. 
(Note: Legacy exemptions applied to `citizen_qa.py` and `legal.py` only).

### 3. Flow Verification (Mocked)
**Scenario A: Citizen Agent (Public)**  
*Query*: "law query"  
*Context*: Public User  
*Verification*: Agent called RAG with `filters={'doc_types': ['law', 'admin_procedure', 'citizen_guide']}`.  
*Result*: Correct Scope Enforced.

**Scenario B: Land Agent (Restricted)**  
*Query*: "planning query"  
*Context*: User in `geo_VN`, Security Level 2.  
*Verification*: Agent called RAG with `user_context={'geo_code': 'geo_VN'}`.  
*Result*: Geo-fencing Enforced.

**Scenario C: Cross-Agent Pollution**  
*Agent*: `economy_agent`  
*Input*: "tourist query"  
*Verification*: Agent filtered for `['stats', 'internal_report']`. Did NOT include `tourism_spots`.  
*Result*: Pollution Prevented.

## Next Actions for Developers
The scaffolding is certified. Developers may now implement business logic inside these files adhering to the following rules:
1. **Enable Tools**: Implement `web_search` or `sql_execute_safe` using the **project wrappers only**.
2. **Do Not Import Clients**: Use `app.core.rag.pipeline`, `app.core.db_sql`, `app.core.llm_client`.
3. **Keep Tool Notes**: Update the `AGENT TOOL NOTE` if new tools are added.

## Risk Assessment
- **Integration**: Real Qdrant/Postgres integration is pending end-to-end verification (requires running stack).
- **Prompting**: The `build_generation_prompt` signature was updated to `(query, case=None, context=context)` to match current core template. Ensure core template remains stable.

**Artifacts**:
- `apps/backend/src/test_agent_certification.py` (The Gitkeeper)
- `scripts/seed_qa_data.py` (Data Generator)
