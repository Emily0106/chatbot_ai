import unittest
from app.core.sql.validator import SQLValidator
from app.core.sql.types import SQLPolicy, Lane

class TestRootLimit(unittest.TestCase):
    def setUp(self):
        self.validator = SQLValidator()
        self.policy = SQLPolicy(
            tenant_column="commune_id",
            allowed_relations=["view_people"],
            max_limit=50,
            forbid_set_ops=True
        )
        self.tenant_id = "test_tenant"

    def test_no_limit(self):
        """Case 1: No Limit -> Added LIMIT 50"""
        raw = "SELECT * FROM view_people"
        safe = self.validator.validate_and_transform(
            raw_sql=raw,
            params={},
            tenant_id=self.tenant_id,
            policy=self.policy,
            lane="template"
        )
        print(f"\n[Case 1] Input: {raw}")
        print(f"[Case 1] Output: {safe.sql}")
        self.assertIn("LIMIT 50", safe.sql)

    def test_huge_limit(self):
        """Case 2: Huge Limit (1000) -> Capped at LIMIT 50"""
        raw = "SELECT * FROM view_people LIMIT 1000"
        safe = self.validator.validate_and_transform(
            raw_sql=raw,
            params={},
            tenant_id=self.tenant_id,
            policy=self.policy,
            lane="template"
        )
        print(f"\n[Case 2] Input: {raw}")
        print(f"[Case 2] Output: {safe.sql}")
        self.assertIn("LIMIT 50", safe.sql)

    def test_small_limit(self):
        """Case 3: Small Limit (10) -> Kept as LIMIT 10"""
        raw = "SELECT * FROM view_people LIMIT 10"
        safe = self.validator.validate_and_transform(
            raw_sql=raw,
            params={},
            tenant_id=self.tenant_id,
            policy=self.policy,
            lane="template"
        )
        print(f"\n[Case 3] Input: {raw}")
        print(f"[Case 3] Output: {safe.sql}")
        self.assertIn("LIMIT 10", safe.sql)

    def test_subquery_limit(self):
        """Case 4: Subquery with huge limit -> Root capped, subquery preserved"""
        # Note: Subqueries are allowed by default in this test setup (forbid_subquery=False in default policy, but we set it in setUp)
        # We need to enable subqueries for this test
        policy = SQLPolicy(
            tenant_column="commune_id",
            allowed_relations=["view_people"],
            max_limit=50,
            forbid_subquery=False
        )
        
        raw = "SELECT * FROM (SELECT * FROM view_people LIMIT 1000) AS sub"
        safe = self.validator.validate_and_transform(
            raw_sql=raw,
            params={},
            tenant_id=self.tenant_id,
            policy=policy,
            lane="template"
        )
        print(f"\n[Case 4] Input: {raw}")
        print(f"[Case 4] Output: {safe.sql}")
        
        # Root must have LIMIT 50
        self.assertTrue(safe.sql.endswith("LIMIT 50"))
        
        # Inner LIMIT 1000 should be preserved (or at least not capped by root logic)
        # Note: sqlglot might reformat, but 1000 should be there
        self.assertIn("LIMIT 1000", safe.sql)

if __name__ == "__main__":
    unittest.main()
