import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-before-deployment")
    DATABASE_PATH = BASE_DIR / "database" / "store.db"
    INVOICE_FOLDER = BASE_DIR / "invoices"
    REPORT_FOLDER = BASE_DIR / "reports"
    LOG_FOLDER = BASE_DIR / "logs"
    DATA_FOLDER = BASE_DIR / "data"
    TAX_RATE = "0.10"
    BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Retail Inventory Management")
    BUSINESS_ADDRESS = os.environ.get("BUSINESS_ADDRESS", "Your Business Address")
    BUSINESS_EMAIL = os.environ.get("BUSINESS_EMAIL", "business@example.com")

def create_directories():
    for path in (
        Config.DATABASE_PATH.parent, Config.INVOICE_FOLDER,
        Config.REPORT_FOLDER, Config.LOG_FOLDER, Config.DATA_FOLDER
    ):
        path.mkdir(parents=True, exist_ok=True)
