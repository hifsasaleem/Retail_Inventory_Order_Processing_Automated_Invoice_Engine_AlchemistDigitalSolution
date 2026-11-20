import logging
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort
from config import Config, create_directories
from database import initialize_database
from services import InventoryManager, CustomerManager, OrderManager, InvoiceGenerator, ReportManager, BulkImporter

def create_app():
    create_directories()
    Config.LOG_FOLDER.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(Config.LOG_FOLDER / "system.log"),
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    initialize_database()
    app=Flask(__name__)
    app.config.from_object(Config)
    inv=InventoryManager(); customers=CustomerManager(); orders=OrderManager()
    invoices=InvoiceGenerator(); reports=ReportManager()

    @app.route("/")
    def dashboard():
        summary=inv.summary()
        with __import__("database").get_db_connection() as conn:
            revenue=conn.execute("SELECT COALESCE(SUM(CAST(grand_total AS REAL)),0) n FROM orders WHERE status='completed'").fetchone()["n"]
            recent=conn.execute("""SELECT o.*,c.name customer_name FROM orders o JOIN customers c
                ON c.customer_id=o.customer_id ORDER BY o.order_id DESC LIMIT 5""").fetchall()
        low=inv.list_products(low_stock=True,per_page=100)["products"]
        return render_template("dashboard.html",summary=summary,revenue=revenue,recent=recent,low=low)

    @app.route("/products")
    def products():
        result=inv.list_products(request.args.get("search",""),request.args.get("page",1,type=int))
        return render_template("products.html",**result,search=request.args.get("search",""))
    @app.route("/products/add",methods=["GET","POST"])
    def product_add():
        if request.method=="POST":
            try:
                inv.add_product(request.form)
                flash("Product added successfully.","success")
                return redirect(url_for("products"))
            except Exception as e: flash(str(e),"danger")
        return render_template("product_form.html",product=None)
    @app.route("/products/<int:pid>/edit",methods=["GET","POST"])
    def product_edit(pid):
        product=inv.get_product(pid)
        if not product: abort(404)
        if request.method=="POST":
            try:
                inv.update_product(pid,request.form)
                flash("Product updated.","success"); return redirect(url_for("products"))
            except Exception as e: flash(str(e),"danger")
        return render_template("product_form.html",product=product)
    @app.route("/products/<int:pid>/stock",methods=["POST"])
    def product_stock(pid):
        try: inv.adjust_stock(pid,int(request.form["quantity"]),request.form.get("notes","Manual adjustment"))
        except Exception as e: flash(str(e),"danger")
        else: flash("Stock adjusted.","success")
        return redirect(url_for("products"))
    @app.route("/products/<int:pid>/delete",methods=["POST"])
    def product_delete(pid):
        try: inv.delete_product(pid); flash("Product deleted.","success")
        except Exception as e: flash(str(e),"warning")
        return redirect(url_for("products"))

    @app.route("/customers")
    def customer_list():
        return render_template("customers.html",customers=customers.list(request.args.get("search","")),search=request.args.get("search",""))
    @app.route("/customers/add",methods=["GET","POST"])
    def customer_add():
        if request.method=="POST":
            try: customers.add(request.form); flash("Customer added.","success"); return redirect(url_for("customer_list"))
            except Exception as e: flash(str(e),"danger")
        return render_template("customer_form.html",customer=None)
    @app.route("/customers/<int:cid>/edit",methods=["GET","POST"])
    def customer_edit(cid):
        customer=customers.get(cid)
        if not customer: abort(404)
        if request.method=="POST":
            try: customers.update(cid,request.form); flash("Customer updated.","success"); return redirect(url_for("customer_list"))
            except Exception as e: flash(str(e),"danger")
        return render_template("customer_form.html",customer=customer)
    @app.route("/customers/<int:cid>/delete",methods=["POST"])
    def customer_delete(cid):
        try: customers.delete(cid); flash("Customer deleted.","success")
        except Exception as e: flash(str(e),"warning")
        return redirect(url_for("customer_list"))

    @app.route("/orders")
    def order_list():
        return render_template("orders.html",orders=orders.list_orders())
    @app.route("/orders/new",methods=["GET","POST"])
    def order_new():
        if request.method=="POST":
            try:
                product_ids=request.form.getlist("product_id[]")
                quantities=request.form.getlist("quantity[]")
                items=[{"product_id":p,"quantity":q} for p,q in zip(product_ids,quantities) if p and q]
                oid,invoice=orders.create_order(request.form["customer_id"],items,request.form.get("discount","0"))
                try: invoices.generate(oid)
                except Exception: logging.exception("Invoice generation failed for order %s",oid)
                flash(f"Order {invoice} created.","success")
                return redirect(url_for("order_list"))
            except Exception as e: flash(str(e),"danger")
        return render_template("order_form.html",customers=customers.list(),products=inv.list_products(per_page=100)["products"])
    @app.route("/orders/<int:oid>/cancel",methods=["POST"])
    def order_cancel(oid):
        try: orders.cancel_order(oid); flash("Order cancelled and stock restored.","success")
        except Exception as e: flash(str(e),"danger")
        return redirect(url_for("order_list"))
    @app.route("/orders/<int:oid>/invoice")
    def order_invoice(oid):
        try: path=invoices.generate(oid)
        except Exception as e: flash(str(e),"danger"); return redirect(url_for("order_list"))
        return send_file(path,as_attachment=True,download_name=path.name)

    @app.route("/reports")
    def report_page():
        return render_template("reports.html",summary=reports.summary_data(),
                               sales=reports.sales_data().head(10).to_dict("records"),
                               inventory=reports.inventory_data().head(10).to_dict("records"),
                               top=reports.product_sales().head(10).to_dict("records"))
    @app.route("/reports/export")
    def report_export():
        path=reports.export()
        return send_file(path/"business_reports.xlsx",as_attachment=True)
    @app.route("/reports/export/csv/<kind>")
    def report_csv(kind):
        mapping={"sales":"sales_report.csv","inventory":"inventory_report.csv"}
        if kind not in mapping: abort(404)
        path=reports.export()/mapping[kind]
        return send_file(path,as_attachment=True)
    @app.route("/import",methods=["GET","POST"])
    def bulk_import():
        if request.method=="POST":
            uploaded=request.files.get("file")
            if not uploaded or not uploaded.filename.lower().endswith(".csv"):
                flash("Choose a CSV file.","danger")
            else:
                safe_name="inventory_upload.csv"
                target=Config.DATA_FOLDER/safe_name
                uploaded.save(target)
                try:
                    count,errors=BulkImporter().import_csv(target)
                    flash(f"Imported/updated {count} product rows.","success")
                    for error in errors[:10]: flash(error,"warning")
                except Exception as e: flash(str(e),"danger")
        return render_template("import.html")

    return app

app=create_app()
if __name__=="__main__":
    app.run(debug=True)
