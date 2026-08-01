"""
config.py — Central configuration for BCA2A Attendance Bot
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

ADMIN_CHAT_ID: int = int(os.getenv("ADMIN_CHAT_ID", "0"))

_cr_raw = os.getenv("CR_CHAT_IDS", "")
CR_CHAT_IDS: list[int] = [
    int(x.strip()) for x in _cr_raw.split(",") if x.strip().isdigit()
]

# All users who can mark attendance
AUTHORIZED_USERS: list[int] = list({ADMIN_CHAT_ID} | set(CR_CHAT_IDS)) if ADMIN_CHAT_ID != 0 else []

# ── Authorized Users ──────────────────────────
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0))

import json
_cr_creds_raw = os.getenv("CR_CREDENTIALS", "{}")
try:
    CR_CREDENTIALS = json.loads(_cr_creds_raw)
except Exception:
    CR_CREDENTIALS = {}

# ── Google Sheets ─────────────────────────────────────────────────────────────
SPREADSHEET_ID: str  = os.getenv("SPREADSHEET_ID", "")
CREDENTIALS_FILE: str = os.getenv("CREDENTIALS_FILE", "credentials.json")

# ── College / Class Info ──────────────────────────────────────────────────────
COLLEGE_NAME = "Techno India University — West Bengal"
CLASS_NAME   = "SOF BCA2A — 2nd Year, 3rd Semester"
ROOM_NO      = "LT-207"

# ── Attendance Marks ─────────────────────────────────────────────────────────
PRESENT_MARK = "P"
ABSENT_MARK  = "A"

# ── Student ID validation ─────────────────────────────────────────────────────
STUDENT_ID_LENGTH = 12
STUDENT_ID_PREFIX = "2510170020"
