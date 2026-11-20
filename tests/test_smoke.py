import tempfile
import unittest
from pathlib import Path
from decimal import Decimal

class ModelSmokeTest(unittest.TestCase):
    def test_money_and_product_model(self):
        from models import Product, Customer
        p=Product("abc-1","Test Product","General",Decimal("2.50"),Decimal("5.00"),3,5)
        self.assertEqual(p.sku,"ABC-1")
        self.assertTrue(p.needs_restock)
        c=Customer("Test Customer","test@example.com")
        self.assertEqual(c.name,"Test Customer")

if __name__=="__main__":
    unittest.main()
