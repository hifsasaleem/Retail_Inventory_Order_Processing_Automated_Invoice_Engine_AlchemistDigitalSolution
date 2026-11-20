import csv
import logging
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from datetime import datetime
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from config import Config
from database import get_db_connection

CENT = Decimal("0.01")

def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid monetary amount.")
    if not result.is_finite() or result < 0:
        raise ValueError("Amount must be a finite non-negative number.")
    return result.quantize(CENT, rounding=ROUND_HALF_UP)

def row_product(row):
    from models import Product
    return Product(
        product_id=row["product_id"], sku=row["sku"], name=row["name"],
        category=row["category"], cost_price=Decimal(row["cost_price"]),
        unit_price=Decimal(row["unit_price"]), stock_quantity=row["stock_quantity"],
        reorder_threshold=row["reorder_threshold"], description=row["description"]
    )

class InventoryManager:
    def add_product(self, data):
        from models import Product
        product = Product(
            sku=data["sku"], name=data["name"], category=data["category"],
            cost_price=money(data["cost_price"]), unit_price=money(data["unit_price"]),
            stock_quantity=int(data.get("stock_quantity", 0)),
            reorder_threshold=int(data.get("reorder_threshold", 5)),
            description=data.get("description") or None
        )
        with get_db_connection() as conn:
            cur = conn.execute("""INSERT INTO products
                (sku,name,category,cost_price,unit_price,stock_quantity,reorder_threshold,description)
                VALUES (?,?,?,?,?,?,?,?)""",
                (product.sku, product.name, product.category, str(product.cost_price),
                 str(product.unit_price), product.stock_quantity, product.reorder_threshold, product.description))
            pid = cur.lastrowid
            if product.stock_quantity:
                conn.execute("""INSERT INTO stock_movements
                    (product_id,movement_type,quantity,reference,notes)
                    VALUES (?,'initial',?,'PRODUCT_CREATION','Initial stock')""",
                    (pid, product.stock_quantity))
        logging.info("Product created sku=%s id=%s", product.sku, pid)
        self.alert_for_product(pid)
        return pid

    def get_product(self, product_id):
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM products WHERE product_id=?", (product_id,)).fetchone()
        return row_product(row) if row else None

    def list_products(self, search="", page=1, per_page=10, low_stock=False):
        page = max(1, int(page))
        per_page = min(100, max(1, int(per_page)))
        term = f"%{search.strip()}%"
        where = "WHERE (sku LIKE ? OR name LIKE ? OR category LIKE ?)"
        params = [term, term, term]
        if low_stock:
            where += " AND stock_quantity <= reorder_threshold"
        with get_db_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) n FROM products {where}", params).fetchone()["n"]
            rows = conn.execute(f"SELECT * FROM products {where} ORDER BY name LIMIT ? OFFSET ?",
                                params + [per_page, (page-1)*per_page]).fetchall()
        return {"products":[row_product(r) for r in rows], "total":total,
                "page":page, "per_page":per_page,
                "total_pages":max(1,(total+per_page-1)//per_page)}

    def update_product(self, product_id, data):
        allowed = {"name","category","cost_price","unit_price","reorder_threshold","description"}
        updates = {k:v for k,v in data.items() if k in allowed}
        if not updates:
            raise ValueError("No valid product fields supplied.")
        if "name" in updates and not str(updates["name"]).strip(): raise ValueError("Name is required.")
        if "category" in updates and not str(updates["category"]).strip(): raise ValueError("Category is required.")
        for field in ("cost_price","unit_price"):
            if field in updates: updates[field] = str(money(updates[field]))
        if "reorder_threshold" in updates:
            updates["reorder_threshold"] = int(updates["reorder_threshold"])
            if updates["reorder_threshold"] < 0: raise ValueError("Threshold cannot be negative.")
        if "description" in updates: updates["description"] = updates["description"] or None
        updates["updated_at"] = datetime.now().isoformat(timespec="seconds")
        sql = ", ".join(f"{k}=?" for k in updates)
        with get_db_connection() as conn:
            cur = conn.execute(f"UPDATE products SET {sql} WHERE product_id=?",
                               list(updates.values())+[product_id])
            if cur.rowcount == 0: raise ValueError("Product not found.")
        self.alert_for_product(product_id)

    def adjust_stock(self, product_id, quantity, notes="Manual adjustment"):
        quantity = int(quantity)
        if quantity == 0: raise ValueError("Adjustment cannot be zero.")
        kind = "purchase" if quantity > 0 else "adjustment"
        with get_db_connection() as conn:
            cur = conn.execute("""UPDATE products SET stock_quantity=stock_quantity+?,
                updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND stock_quantity+? >= 0""",
                (quantity, product_id, quantity))
            if cur.rowcount != 1: raise ValueError("Product not found or insufficient stock.")
            conn.execute("""INSERT INTO stock_movements
                (product_id,movement_type,quantity,reference,notes)
                VALUES (?,?,?,?,?)""",
                (product_id, kind, abs(quantity), "MANUAL_ADJUSTMENT", notes))
        logging.info("Stock adjusted product_id=%s quantity=%s", product_id, quantity)
        self.alert_for_product(product_id)

    def delete_product(self, product_id):
        with get_db_connection() as conn:
            cur = conn.execute("DELETE FROM products WHERE product_id=?", (product_id,))
            if cur.rowcount != 1: raise ValueError("Product not found.")
        logging.info("Product deleted id=%s", product_id)

    def alert_for_product(self, product_id):
        p = self.get_product(product_id)
        if p and p.needs_restock:
            level = "OUT OF STOCK" if p.is_out_of_stock else "LOW STOCK"
            logging.warning("%s: %s (%s), quantity=%s, threshold=%s",
                            level, p.name, p.sku, p.stock_quantity, p.reorder_threshold)

    def summary(self):
        with get_db_connection() as conn:
            r = conn.execute("""SELECT COUNT(*) products,
                COALESCE(SUM(stock_quantity),0) units,
                COALESCE(SUM(CAST(cost_price AS REAL)*stock_quantity),0) stock_cost,
                SUM(CASE WHEN stock_quantity=0 THEN 1 ELSE 0 END) out_count,
                SUM(CASE WHEN stock_quantity>0 AND stock_quantity<=reorder_threshold THEN 1 ELSE 0 END) low_count
                FROM products""").fetchone()
        return dict(r)

class CustomerManager:
    def add(self, data):
        from models import Customer
        c = Customer(data["name"], data.get("email") or None, data.get("phone") or None, data.get("address") or None)
        with get_db_connection() as conn:
            cur = conn.execute("INSERT INTO customers(name,email,phone,address) VALUES(?,?,?,?)",
                               (c.name,c.email,c.phone,c.address))
            return cur.lastrowid
    def get(self, cid):
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM customers WHERE customer_id=?", (cid,)).fetchone()
    def list(self, search=""):
        term=f"%{search.strip()}%"
        with get_db_connection() as conn:
            return conn.execute("""SELECT * FROM customers WHERE name LIKE ? OR email LIKE ? OR phone LIKE ?
                ORDER BY name""",(term,term,term)).fetchall()
    def update(self, cid, data):
        from models import Customer
        c=Customer(data["name"],data.get("email") or None,data.get("phone") or None,data.get("address") or None)
        with get_db_connection() as conn:
            cur=conn.execute("UPDATE customers SET name=?,email=?,phone=?,address=? WHERE customer_id=?",
                             (c.name,c.email,c.phone,c.address,cid))
            if cur.rowcount != 1: raise ValueError("Customer not found.")
    def delete(self,cid):
        with get_db_connection() as conn:
            cur=conn.execute("DELETE FROM customers WHERE customer_id=?",(cid,))
            if cur.rowcount != 1: raise ValueError("Customer not found.")

class OrderManager:
    def create_order(self, customer_id, items, discount="0", tax_rate=None):
        discount=money(discount)
        tax_rate=Decimal(str(tax_rate if tax_rate is not None else Config.TAX_RATE))
        if not tax_rate.is_finite() or tax_rate < 0: raise ValueError("Invalid tax rate.")
        if not items: raise ValueError("Add at least one item.")
        invoice=f"INV-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        with get_db_connection() as conn:
            customer=conn.execute("SELECT customer_id FROM customers WHERE customer_id=?",(customer_id,)).fetchone()
            if not customer: raise ValueError("Select a valid customer.")
            normalized={}
            for item in items:
                pid=int(item["product_id"]); qty=int(item["quantity"])
                if qty <= 0: raise ValueError("Item quantity must be positive.")
                normalized[pid]=normalized.get(pid,0)+qty
            snapshots=[]; subtotal=Decimal("0.00")
            for pid,qty in normalized.items():
                p=conn.execute("SELECT * FROM products WHERE product_id=?",(pid,)).fetchone()
                if not p: raise ValueError(f"Product {pid} not found.")
                if p["stock_quantity"] < qty: raise ValueError(f"Insufficient stock for {p['name']}. Available: {p['stock_quantity']}.")
                unit=Decimal(p["unit_price"]); cost=Decimal(p["cost_price"])
                line=(unit*qty).quantize(CENT,rounding=ROUND_HALF_UP)
                subtotal+=line
                snapshots.append((p,qty,unit,cost,line))
            if discount > subtotal: raise ValueError("Discount cannot exceed subtotal.")
            taxable=subtotal-discount
            tax=(taxable*tax_rate).quantize(CENT,rounding=ROUND_HALF_UP)
            total=(taxable+tax).quantize(CENT,rounding=ROUND_HALF_UP)
            cur=conn.execute("""INSERT INTO orders(invoice_number,customer_id,subtotal,tax_rate,tax_amount,
                discount_amount,grand_total,status) VALUES(?,?,?,?,?,?,?,'completed')""",
                (invoice,customer_id,str(subtotal),str(tax_rate),str(tax),str(discount),str(total)))
            oid=cur.lastrowid
            for p,qty,unit,cost,line in snapshots:
                cur=conn.execute("""UPDATE products SET stock_quantity=stock_quantity-?,
                    updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND stock_quantity>=?""",(qty,p["product_id"],qty))
                if cur.rowcount != 1: raise ValueError(f"Stock changed while processing {p['name']}. Please retry.")
                conn.execute("""INSERT INTO order_items(order_id,product_id,product_name,sku,quantity,
                    unit_price,cost_price,line_total) VALUES(?,?,?,?,?,?,?,?)""",
                    (oid,p["product_id"],p["name"],p["sku"],qty,str(unit),str(cost),str(line)))
                conn.execute("""INSERT INTO stock_movements(product_id,movement_type,quantity,reference,notes)
                    VALUES(?,'sale',?,?,?)""",(p["product_id"],qty,invoice,"Order sale"))
        logging.info("Order completed invoice=%s order_id=%s",invoice,oid)
        return oid,invoice

    def cancel_order(self, order_id):
        with get_db_connection() as conn:
            order=conn.execute("SELECT * FROM orders WHERE order_id=?",(order_id,)).fetchone()
            if not order: raise ValueError("Order not found.")
            if order["status"] == "cancelled": raise ValueError("Order is already cancelled.")
            rows=conn.execute("SELECT product_id,quantity FROM order_items WHERE order_id=?",(order_id,)).fetchall()
            for row in rows:
                conn.execute("UPDATE products SET stock_quantity=stock_quantity+?,updated_at=CURRENT_TIMESTAMP WHERE product_id=?",
                             (row["quantity"],row["product_id"]))
                conn.execute("""INSERT INTO stock_movements(product_id,movement_type,quantity,reference,notes)
                    VALUES(?,'cancellation',?,?,?)""",(row["product_id"],row["quantity"],order["invoice_number"],"Order cancellation"))
            conn.execute("UPDATE orders SET status='cancelled',cancelled_at=CURRENT_TIMESTAMP WHERE order_id=?",(order_id,))
        logging.info("Order cancelled id=%s invoice=%s",order_id,order["invoice_number"])

    def get_order(self, order_id):
        with get_db_connection() as conn:
            order=conn.execute("""SELECT o.*,c.name customer_name,c.email customer_email,c.phone customer_phone,c.address customer_address
                FROM orders o JOIN customers c ON c.customer_id=o.customer_id WHERE o.order_id=?""",(order_id,)).fetchone()
            if not order: return None
            items=conn.execute("SELECT * FROM order_items WHERE order_id=?",(order_id,)).fetchall()
        return dict(order),[dict(x) for x in items]

    def list_orders(self):
        with get_db_connection() as conn:
            return conn.execute("""SELECT o.*,c.name customer_name FROM orders o
                JOIN customers c ON c.customer_id=o.customer_id ORDER BY o.order_id DESC""").fetchall()

class InvoiceGenerator:
    def generate(self, order_id):
        result=OrderManager().get_order(order_id)
        if not result: raise ValueError("Order not found.")
        order,items=result
        Config.INVOICE_FOLDER.mkdir(parents=True,exist_ok=True)
        path=Config.INVOICE_FOLDER/f"{order['invoice_number']}.pdf"
        styles=getSampleStyleSheet()
        story=[Paragraph(Config.BUSINESS_NAME,styles["Title"]),
               Paragraph(Config.BUSINESS_ADDRESS,styles["Normal"]),
               Paragraph(Config.BUSINESS_EMAIL,styles["Normal"]),Spacer(1,18),
               Paragraph(f"Invoice: {order['invoice_number']}",styles["Heading2"]),
               Paragraph(f"Date: {order['created_at']}",styles["Normal"]),
               Paragraph(f"Customer: {order['customer_name']}",styles["Normal"]),
               Paragraph(f"Email: {order['customer_email'] or '-'}",styles["Normal"]),Spacer(1,14)]
        data=[["SKU","Product","Qty","Unit Price","Line Total"]]
        for x in items:
            data.append([x["sku"],x["product_name"],str(x["quantity"]),x["unit_price"],x["line_total"]])
        table=Table(data,repeatRows=1,colWidths=[65,190,40,85,85])
        table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17243a")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),0.4,colors.grey),
            ("PADDING",(0,0),(-1,-1),7),
            ("ALIGN",(2,1),(-1,-1),"RIGHT")
        ]))
        story += [table,Spacer(1,14),
            Paragraph(f"Subtotal: {order['subtotal']}",styles["Normal"]),
            Paragraph(f"Discount: {order['discount_amount']}",styles["Normal"]),
            Paragraph(f"Tax ({Decimal(order['tax_rate'])*100}%): {order['tax_amount']}",styles["Normal"]),
            Paragraph(f"<b>Grand Total: {order['grand_total']}</b>",styles["Heading2"]),
            Paragraph(f"Order status: {order['status']}",styles["Normal"])]
        SimpleDocTemplate(str(path),pagesize=A4).build(story)
        with get_db_connection() as conn:
            conn.execute("""INSERT INTO invoice_records(order_id,invoice_number,pdf_path)
                VALUES(?,?,?) ON CONFLICT(order_id) DO UPDATE SET pdf_path=excluded.pdf_path,
                generated_at=CURRENT_TIMESTAMP""",(order_id,order["invoice_number"],str(path)))
        logging.info("Invoice generated %s",path)
        return path

class ReportManager:
    def sales_data(self):
        with get_db_connection() as conn:
            return pd.read_sql_query("""SELECT o.invoice_number,o.created_at,c.name customer,
                o.subtotal,o.tax_amount,o.discount_amount,o.grand_total,o.status
                FROM orders o JOIN customers c ON c.customer_id=o.customer_id
                ORDER BY o.created_at DESC""",conn)
    def product_sales(self):
        with get_db_connection() as conn:
            return pd.read_sql_query("""SELECT oi.sku,oi.product_name,
                SUM(CASE WHEN o.status='completed' THEN oi.quantity ELSE 0 END) units_sold,
                SUM(CASE WHEN o.status='completed' THEN CAST(oi.line_total AS REAL) ELSE 0 END) revenue,
                SUM(CASE WHEN o.status='completed' THEN (CAST(oi.unit_price AS REAL)-CAST(oi.cost_price AS REAL))*oi.quantity ELSE 0 END) gross_profit
                FROM order_items oi JOIN orders o ON o.order_id=oi.order_id
                GROUP BY oi.product_id,oi.sku,oi.product_name ORDER BY units_sold DESC""",conn)
    def summary_data(self):
        with get_db_connection() as conn:
            row = conn.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN status='completed' THEN CAST(grand_total AS REAL) ELSE 0 END),0) AS total_revenue,
                    COALESCE(SUM(CASE WHEN status='completed' THEN CAST(discount_amount AS REAL) ELSE 0 END),0) AS total_discounts,
                    COALESCE(SUM(CASE WHEN status='completed' THEN CAST(tax_amount AS REAL) ELSE 0 END),0) AS total_tax
                FROM orders
            """).fetchone()
            profit = conn.execute("""
                SELECT COALESCE(SUM(
                    CASE WHEN o.status='completed'
                    THEN (CAST(oi.unit_price AS REAL)-CAST(oi.cost_price AS REAL))*oi.quantity
                    ELSE 0 END
                ),0) AS gross_profit
                FROM order_items oi JOIN orders o ON o.order_id=oi.order_id
            """).fetchone()["gross_profit"]
        return {
            "total_revenue": row["total_revenue"],
            "total_discounts": row["total_discounts"],
            "total_tax": row["total_tax"],
            "gross_profit": profit
        }

    def inventory_data(self):
        with get_db_connection() as conn:
            return pd.read_sql_query("""SELECT sku,name,category,cost_price,unit_price,stock_quantity,
                reorder_threshold,CASE WHEN stock_quantity=0 THEN 'Out of stock'
                WHEN stock_quantity<=reorder_threshold THEN 'Low stock' ELSE 'In stock' END status
                FROM products ORDER BY name""",conn)
    def export(self):
        Config.REPORT_FOLDER.mkdir(parents=True,exist_ok=True)
        sales=self.sales_data(); products=self.product_sales(); inventory=self.inventory_data()
        summary=pd.DataFrame([self.summary_data()])
        sales.to_csv(Config.REPORT_FOLDER/"sales_report.csv",index=False)
        inventory.to_csv(Config.REPORT_FOLDER/"inventory_report.csv",index=False)
        with pd.ExcelWriter(Config.REPORT_FOLDER/"business_reports.xlsx",engine="openpyxl") as writer:
            summary.to_excel(writer,sheet_name="Summary",index=False)
            sales.to_excel(writer,sheet_name="Orders",index=False)
            products.to_excel(writer,sheet_name="Product Sales",index=False)
            inventory.to_excel(writer,sheet_name="Inventory",index=False)
        return Config.REPORT_FOLDER

class BulkImporter:
    def import_csv(self, file_path):
        successes=0; errors=[]
        with open(file_path,newline="",encoding="utf-8-sig") as f:
            reader=csv.DictReader(f)
            required={"sku","name","category","cost_price","unit_price","stock_quantity","reorder_threshold"}
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                raise ValueError("CSV must include: "+", ".join(sorted(required)))
            for line,row in enumerate(reader,start=2):
                try:
                    sku=row["sku"].strip().upper()
                    with get_db_connection() as conn:
                        existing=conn.execute("SELECT product_id FROM products WHERE sku=?",(sku,)).fetchone()
                    if existing:
                        # Existing SKU: update editable product fields and set stock to supplied quantity via adjustment.
                        InventoryManager().update_product(existing["product_id"],row)
                        current=InventoryManager().get_product(existing["product_id"])
                        desired=int(row["stock_quantity"])
                        delta=desired-current.stock_quantity
                        if delta: InventoryManager().adjust_stock(existing["product_id"],delta,"Bulk CSV stock update")
                    else:
                        InventoryManager().add_product(row)
                    successes+=1
                except Exception as exc:
                    errors.append(f"Line {line}: {exc}")
                    logging.exception("Bulk import error at line %s",line)
        return successes,errors
