# Retail Inventory, Order Processing & Automated Invoice Management System

A Flask-based retail management application built with Python OOP, SQLite, ReportLab, pandas and openpyxl.

## Features

- Product CRUD, SKU search, pagination and stock adjustments.
- Low-stock and out-of-stock alerts in the application log.
- Customer management.
- Multi-item order processing with stock validation and atomic SQLite transactions.
- Automatic stock deduction and one-time stock restoration on cancellation.
- PDF invoices saved under `invoices/INV-....pdf`.
- Sales, product performance, gross-profit and inventory reports.
- Excel and CSV exports.
- Bulk CSV product import/update with row-level error logging.
- Audit/error logging in `logs/system.log`.

## Requirements

- Python 3.10 or newer recommended.
- pip.
- Internet connection for the Bootstrap CDN used by the HTML templates (the backend itself does not require an external service).

## Setup

### Windows (PowerShell)

```powershell
cd Retail_Inventory_System
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

### macOS / Linux

```bash
cd Retail_Inventory_System
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python app.py
```

The database and required folders are initialized automatically at first startup.

Open: http://127.0.0.1:5000/

## First-use workflow

1. Open **Customers** and add at least one customer.
2. Open **Products** and add products with SKU, category, cost price, selling price, stock and reorder threshold.
3. Open **Create Order**, select a customer, add one or more product rows, set an optional discount and confirm.
4. The system validates stock and creates the order in a database transaction. A PDF invoice is generated automatically.
5. Open **Orders** to download invoices or cancel an order. Cancellation restores stock once only.
6. Open **Reports** to download the Excel workbook or CSV reports.
7. Open **Bulk Import** to upload a CSV.

## Bulk CSV format

Required headers:

```csv
sku,name,category,cost_price,unit_price,stock_quantity,reorder_threshold,description
```

A sample file is available at `static/sample_products.csv`. Existing SKUs are updated; their stock is adjusted to the quantity in the CSV and recorded as a stock movement.

## Project structure

```text
Retail_Inventory_System/
├── app.py                 # Flask application and routes
├── config.py              # Application configuration and paths
├── database.py            # SQLite connection and schema initialization
├── models.py              # Product and Customer OOP models
├── services.py            # Inventory, customers, orders, invoices, reports, import
├── templates/             # Jinja2 HTML templates
├── static/                # CSS and sample CSV
├── database/store.db      # Created automatically
├── invoices/              # Generated PDF invoices
├── reports/               # Generated Excel and CSV reports
├── logs/system.log        # Audit and error log
├── data/                  # Uploaded import files
└── tests/                 # Smoke tests
```

## Database schema

- `products`: SKU, name, category, cost and selling prices, stock, reorder threshold.
- `customers`: name and contact details.
- `orders`: invoice number, customer, subtotal, tax, discount, grand total and status.
- `order_items`: product snapshot, quantity, unit price, cost price and line total.
- `stock_movements`: initial stock, purchases, sales, cancellations and adjustments.
- `invoice_records`: generated invoice path and invoice number.

Foreign keys are enabled for every SQLite connection. Prices are stored as decimal strings to avoid SQLite floating-point storage for transaction calculations. Order calculations use Python `Decimal`.

## Run tests

```bash
python -m unittest discover -s tests -v
```

## Configuration

Environment variables supported:

- `SECRET_KEY`: set a strong random value before deployment.
- `BUSINESS_NAME`
- `BUSINESS_ADDRESS`
- `BUSINESS_EMAIL`

Example (macOS/Linux):

```bash
export SECRET_KEY="replace-with-a-long-random-secret"
export BUSINESS_NAME="Your Store"
export BUSINESS_ADDRESS="Your Business Address"
export BUSINESS_EMAIL="you@example.com"
python app.py
```

PowerShell:

```powershell
$env:SECRET_KEY="replace-with-a-long-random-secret"
$env:BUSINESS_NAME="Your Store"
$env:BUSINESS_ADDRESS="Your Business Address"
$env:BUSINESS_EMAIL="you@example.com"
python app.py
```

## Important production notes

This is a local academic project starter/application, not a hardened public deployment. Before internet deployment, add administrator authentication, CSRF protection, role-based authorization, secure upload limits and validation, HTTPS, backups, and a production WSGI server. Do not use Flask's debug server in production.

The dashboard revenue and report values are gross sales/revenue measures. Gross profit is calculated from the saved item-level cost and selling-price snapshots, less order discounts; it is not net profit after operating expenses. Tax rate defaults to 10% and can be changed in `config.py`.
