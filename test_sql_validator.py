import asyncio
from app.core.sql.validator import SQLValidator

def test_validator():
    v = SQLValidator()
    
    # Case 1: Valid Query
    sql = "SELECT full_name, phone FROM view_people WHERE code = 'A'"
    res = v.validate_and_fix(sql, tenant_id="xa_demo")
    print(f"Case 1 (Valid): {res.valid}")
    print(f"  Modified: {res.modified_sql}")
    assert res.valid
    assert "commune_id = 'xa_demo'" in res.modified_sql
    assert "LIMIT 50" in res.modified_sql

    # Case 2: Missing WHERE
    sql = "SELECT * FROM view_people"
    res = v.validate_and_fix(sql, tenant_id="xa_demo")
    print(f"Case 2 (No WHERE): {res.valid}")
    print(f"  Modified: {res.modified_sql}")
    assert "WHERE commune_id = 'xa_demo'" in res.modified_sql

    # Case 3: Dangerous Query
    sql = "DROP TABLE view_people"
    res = v.validate_and_fix(sql, tenant_id="xa_demo")
    print(f"Case 3 (DROP): {res.valid}")
    print(f"  Error: {res.error}")
    assert not res.valid

    # Case 4: Existing Limit
    sql = "SELECT * FROM view_people LIMIT 1000"
    res = v.validate_and_fix(sql, tenant_id="xa_demo")
    print(f"Case 4 (High Limit): {res.valid}")
    print(f"  Modified: {res.modified_sql}")
    assert "LIMIT 50" in res.modified_sql

if __name__ == "__main__":
    test_validator()
