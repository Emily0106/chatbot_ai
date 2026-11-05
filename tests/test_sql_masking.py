import unittest
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../apps/backend/src")))

from app.core.sql.executor import SQLExecutor

class TestSQLMasking(unittest.TestCase):
    def setUp(self):
        self.executor = SQLExecutor()

    def test_mask_params(self):
        params = {
            "search_term": "%Nguyen Van A%",
            "q_ascii": "tim ong A",
            "phone": "0912345678",
            "email": "test@example.com",
            "cccd": "123456789",
            "address": "123 Street",
            "full_name": "Nguyen Van A",
            "tenant_id": "xa_demo", # Should NOT be masked
            "limit": 10 # Should NOT be masked
        }
        
        masked = self.executor._mask_params(params)
        
        # Check masked fields
        self.assertEqual(masked["search_term"], "<PII_MASKED>")
        self.assertEqual(masked["q_ascii"], "<PII_MASKED>")
        self.assertEqual(masked["phone"], "<PII_MASKED>")
        self.assertEqual(masked["email"], "<PII_MASKED>")
        self.assertEqual(masked["cccd"], "<PII_MASKED>")
        self.assertEqual(masked["address"], "<PII_MASKED>")
        self.assertEqual(masked["full_name"], "<PII_MASKED>")
        
        # Check unmasked fields
        self.assertEqual(masked["tenant_id"], "xa_demo")
        self.assertEqual(masked["limit"], 10)
        
        print("Masking test passed!")

if __name__ == "__main__":
    unittest.main()
