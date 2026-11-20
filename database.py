import sqlite3
from contextlib import contextmanager
from config import Config

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(str(Config.DATABASE_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def initialize_database():
    schema = """
    CREATE TABLE IF NOT EXISTS products (
        product_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        cost_price TEXT NOT NULL CHECK(CAST(cost_price AS REAL) >= 0),
        unit_price TEXT NOT NULL CHECK(CAST(unit_price AS REAL) >= 0),
        stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK(stock_quantity >= 0),
        reorder_threshold INTEGER NOT NULL DEFAULT 5 CHECK(reorder_threshold >= 0),
        description TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS customers (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE,
        phone TEXT,
        address TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT NOT NULL UNIQUE,
        customer_id INTEGER NOT NULL,
        subtotal TEXT NOT NULL,
        tax_rate TEXT NOT NULL,
        tax_amount TEXT NOT NULL,
        discount_amount TEXT NOT NULL,
        grand_total TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'completed'
          CHECK(status IN ('completed','cancelled')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        cancelled_at TEXT,
        FOREIGN KEY(customer_id) REFERENCES customers(customer_id) ON DELETE RESTRICT
    );
    CREATE TABLE IF NOT EXISTS order_items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        sku TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        unit_price TEXT NOT NULL,
        cost_price TEXT NOT NULL,
        line_total TEXT NOT NULL,
        FOREIGN KEY(order_id) REFERENCES orders(order_id) ON DELETE RESTRICT,
        FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE RESTRICT
    );
    CREATE TABLE IF NOT EXISTS stock_movements (
        movement_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        movement_type TEXT NOT NULL CHECK(movement_type IN
          ('initial','purchase','sale','cancellation','adjustment')),
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        reference TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE RESTRICT
    );
    CREATE TABLE IF NOT EXISTS invoice_records (
        invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL UNIQUE,
        invoice_number TEXT NOT NULL UNIQUE,
        pdf_path TEXT NOT NULL,
        generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(order_id) REFERENCES orders(order_id) ON DELETE RESTRICT
    );
    CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
    CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(created_at);
    CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
    CREATE INDEX IF NOT EXISTS idx_stock_product ON stock_movements(product_id);
    """
    with get_db_connection() as conn:
        conn.executescript(schema)
