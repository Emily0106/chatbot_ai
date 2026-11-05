import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../apps/backend/src")))

from app.api.routes.sql_debug import debug_sql_plan, DebugSQLRequest

async def verify():
    print("Verifying SQL Debug Endpoint...")
    
    # Case 1: Standard with PII and Comment
    req = DebugSQLRequest(
        sql="SELECT * FROM view_people WHERE name = 'Hacker' -- bypass",
        tenant_id="xa_demo",
        params={"phone": "0912345678", "normal": "value"}
    )
    res = await debug_sql_plan(req)
    
    print(f"Status: {res.status}")
    print(f"Safe SQL: {res.safe_sql}")
    print(f"Masked Params: {res.params_masked}")
    
    if res.status != "ALLOWED":
        print("FAILURE: Should be ALLOWED")
        sys.exit(1)
        
    if "commune_id = :__tenant_id" not in res.safe_sql:
        print("FAILURE: Tenant ID not injected")
        sys.exit(1)
        
    if "--" in res.safe_sql:
        print("FAILURE: Comments not stripped")
        sys.exit(1)
        
    if res.params_masked.get("phone") != "<PII_MASKED>":
        print(f"FAILURE: PII not masked. Got {res.params_masked.get('phone')}")
        sys.exit(1)
        
    if res.params_masked.get("normal") != "value":
        print(f"FAILURE: Normal param masked incorrectly.")
        sys.exit(1)
        
    print("SUCCESS: Debug endpoint works as expected.")

if __name__ == "__main__":
    asyncio.run(verify())
