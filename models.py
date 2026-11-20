from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass
class Product:
    sku: str
    name: str
    category: str
    cost_price: Decimal
    unit_price: Decimal
    stock_quantity: int = 0
    reorder_threshold: int = 5
    product_id: Optional[int] = None
    description: Optional[str] = None

    def __post_init__(self):
        self.sku = self.sku.strip().upper()
        self.name = self.name.strip()
        self.category = self.category.strip()
        self.cost_price = Decimal(str(self.cost_price))
        self.unit_price = Decimal(str(self.unit_price))
        if not self.sku or not self.name or not self.category:
            raise ValueError("SKU, product name and category are required.")
        if not self.cost_price.is_finite() or not self.unit_price.is_finite():
            raise ValueError("Prices must be valid numbers.")
        if self.cost_price < 0 or self.unit_price < 0:
            raise ValueError("Prices cannot be negative.")
        if isinstance(self.stock_quantity, bool) or not isinstance(self.stock_quantity, int) or self.stock_quantity < 0:
            raise ValueError("Stock must be a non-negative integer.")
        if isinstance(self.reorder_threshold, bool) or not isinstance(self.reorder_threshold, int) or self.reorder_threshold < 0:
            raise ValueError("Reorder threshold must be a non-negative integer.")

    @property
    def profit_per_unit(self):
        return self.unit_price - self.cost_price

    @property
    def is_out_of_stock(self):
        return self.stock_quantity == 0

    @property
    def needs_restock(self):
        return self.stock_quantity <= self.reorder_threshold

@dataclass
class Customer:
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    customer_id: Optional[int] = None

    def __post_init__(self):
        self.name = self.name.strip()
        self.email = self.email.strip().lower() if self.email else None
        if not self.name:
            raise ValueError("Customer name is required.")
        if self.email and ("@" not in self.email or self.email.startswith("@") or self.email.endswith("@")):
            raise ValueError("Enter a valid email address.")
