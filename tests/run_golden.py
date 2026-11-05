import json
import asyncio
import sys
import os
from typing import List, Dict, Any

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../apps/backend/src")))

from app.core.sql.validator import SQLValidator
from app.core.sql.types import SQLPolicy, SecurityError, ValidationError

DEFAULT_POLICY = SQLPolicy(
    tenant_column="commune_id",
    allowed_relations=["view_people", "view_budget", "structured_rows"],
    max_limit=50,
    statement_timeout_ms=2000,
    forbid_set_ops=True
)

async def run_golden_tests():
    json_path = os.path.join(os.path.dirname(__file__), "tests/data/golden_sql.json")
    with open(json_path, "r") as f:
        cases = json.load(f)
    
    validator = SQLValidator()
    passed = 0
    failed = 0
    
    print(f"Running {len(cases)} Golden SQL Tests...")
    
    for case in cases:
        cid = case["id"]
        inp = case["input"]
        tid = case["tenant_id"]
        
        print(f"[{cid}] Testing...", end=" ")
        
        case_failed = False
        try:
            safe = validator.validate_and_transform(
                raw_sql=inp,
                params={},
                tenant_id=tid,
                policy=DEFAULT_POLICY,
                lane="manual"
            )
            
            # Check if error was expected
            if "expected_error" in case:
                print(f"FAILED. Expected error '{case['expected_error']}' but got success.")
                failed += 1
                continue
                
            # Check SQL content
            if "expected_sql_contains" in case:
                for sub in case["expected_sql_contains"]:
                    if sub not in safe.sql:
                        print(f"FAILED. SQL missing '{sub}'. Got: {safe.sql}")
                        case_failed = True
                        break
            if case_failed:
                failed += 1
                continue
            
            # Check Params
            if "expected_params" in case:
                for k, v in case["expected_params"].items():
                    if safe.params.get(k) != v:
                        print(f"FAILED. Param mismatch {k}={safe.params.get(k)} != {v}")
                        case_failed = True
                        break
            if case_failed:
                failed += 1
                continue
            
            print("PASSED")
            passed += 1
            
        except (SecurityError, ValidationError) as e:
            if "expected_error" in case:
                if case["expected_error"] in str(e):
                    print("PASSED")
                    passed += 1
                else:
                    print(f"FAILED. Expected error '{case['expected_error']}' but got '{str(e)}'")
                    failed += 1
            else:
                print(f"FAILED. Unexpected error: {str(e)}")
                failed += 1
        except Exception as e:
            print(f"FAILED. System error: {str(e)}")
            failed += 1

    print(f"\nResult: {passed}/{len(cases)} Passed.")
    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_golden_tests())
