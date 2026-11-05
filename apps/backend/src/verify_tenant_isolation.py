import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../apps/backend/src")))

from app.core.sql.validator import SQLValidator
from app.core.sql.types import SQLPolicy

def verify_tenant_isolation():
    print("Starting Tenant Isolation Verification (SQL-P2-07)...\n")
    
    validator = SQLValidator()
    # Define a strict policy for testing
    policy = SQLPolicy(
        tenant_column="commune_id",
        allowed_relations=["view_people"],
        max_limit=100,
        forbid_set_ops=True,
        forbid_subquery=True,
        forbid_join=True
    )
    tenant_id = "xa_hoa_minh"
    
    # --- Case 1: Standard Case ---
    print("--- Case 1: Standard Query ---")
    sql_1 = "SELECT * FROM view_people WHERE name = 'A'"
    print(f"Input: {sql_1}")
    
    res_1 = validator.validate_and_transform(
        raw_sql=sql_1, params={}, tenant_id=tenant_id, policy=policy, lane="template"
    )
    print(f"Output SQL: {res_1.sql}")
    print(f"Output Params: {res_1.params}")
    
    if "commune_id = :__tenant_id" in res_1.sql and res_1.params.get("__tenant_id") == tenant_id:
        print("✅ SUCCESS: Tenant ID injected correctly.\n")
    else:
        print("❌ FAILURE: Tenant ID missing or incorrect.\n")
        sys.exit(1)

    # --- Case 2: Cross-Tenant Attempt ---
    print("--- Case 2: Cross-Tenant Attempt ---")
    sql_2 = "SELECT * FROM view_people WHERE commune_id = 'xa_hack'"
    print(f"Input: {sql_2}")
    
    res_2 = validator.validate_and_transform(
        raw_sql=sql_2, params={}, tenant_id=tenant_id, policy=policy, lane="template"
    )
    print(f"Output SQL: {res_2.sql}")
    
    # We expect the validator to append AND commune_id = :__tenant_id
    # This results in: WHERE commune_id = 'xa_hack' AND commune_id = :__tenant_id
    # Since 'xa_hack' != 'xa_hoa_minh', this query returns 0 rows.
    if "commune_id = 'xa_hack'" in res_2.sql and "commune_id = :__tenant_id" in res_2.sql:
         print("✅ SUCCESS: Cross-tenant attempt neutralized (Double condition).\n")
    elif "commune_id = :__tenant_id" in res_2.sql and "xa_hack" not in res_2.sql:
         print("✅ SUCCESS: Cross-tenant attempt neutralized (Overwritten).\n")
    else:
         print("❌ FAILURE: Tenant check might be bypassed.\n")
         sys.exit(1)

    # --- Case 3: Comment Bypass ---
    print("--- Case 3: Comment Bypass ---")
    sql_3 = "SELECT * FROM view_people -- bo qua tenant check"
    print(f"Input: {sql_3}")
    
    res_3 = validator.validate_and_transform(
        raw_sql=sql_3, params={}, tenant_id=tenant_id, policy=policy, lane="template"
    )
    print(f"Output SQL: {res_3.sql}")
    
    if "--" not in res_3.sql and "commune_id = :__tenant_id" in res_3.sql:
        print("✅ SUCCESS: Comments stripped and Tenant ID injected.\n")
    else:
        print("❌ FAILURE: Comments persisted or Tenant ID missing.\n")
        sys.exit(1)

    print("🎉 ALL TENANT ISOLATION TESTS PASSED!")

if __name__ == "__main__":
    verify_tenant_isolation()
