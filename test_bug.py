import os
from datetime import date
from sheets_manager import SheetsManager
import config

try:
    sheets = SheetsManager(config.CREDENTIALS_FILE, config.SPREADSHEET_ID)
    print("SheetsManager initialized")
    filepath = sheets.generate_sheet_image(date.today())
    print(f"Generated filepath: {filepath}")
except Exception as e:
    print(f"Exception: {e}")
