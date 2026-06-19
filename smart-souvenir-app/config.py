"""
Unified configuration for Smart Souvenir Application.

Menggabungkan konfigurasi dari:
- flask-smart-souvenir (Gate)
- kasir (2) (Kasir POS + Face Recognition)
- stock-app-lengkap (Stock Management)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
#  Flask Session Key (boleh bebas, hanya untuk session cookie)
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "smart-souvenir-unified-key-2026")


# ---------------------------------------------------------------------------
#  Database (MySQL)
# ---------------------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "smart_souvenir_complete")


# ---------------------------------------------------------------------------
#  Kasir — Business Rules
# ---------------------------------------------------------------------------
POINTS_PER_RUPIAH = int(os.getenv("POINTS_PER_RUPIAH", "1000"))
WELCOME_POINTS = int(os.getenv("WELCOME_POINTS", "100"))


# ---------------------------------------------------------------------------
#  Kasir — Security
#  KASIR_SECRET_KEY dipakai untuk hash member (NIK, HP, alamat).
#  HARUS sama dengan original: kasir-face-recognition-dev-key-2026
# ---------------------------------------------------------------------------
KASIR_SECRET_KEY = os.getenv(
    "KASIR_SECRET_KEY", "kasir-face-recognition-dev-key-2026"
)
EMBEDDING_ENCRYPTION_KEY = os.getenv(
    "EMBEDDING_ENCRYPTION_KEY", "trinity-kasir-face-crypt-key-32"
)


# ---------------------------------------------------------------------------
#  Stock — Encryption
# ---------------------------------------------------------------------------
STOCK_ENCRYPTION_KEY = os.getenv(
    "STOCK_ENCRYPTION_KEY", "smart-souvenir-stock-app-key-32"
)


# ---------------------------------------------------------------------------
#  Gate — Configuration
# ---------------------------------------------------------------------------
GATE_DEVICE_ID = os.getenv("GATE_DEVICE_ID", "gate-esp32-01")
GATE_REQUEST_KEY_HEX = os.getenv(
    "GATE_REQUEST_KEY_HEX", "7618561da88c350b55ff32bae357efaa"
)
GATE_RESPONSE_KEY_HEX = os.getenv(
    "GATE_RESPONSE_KEY_HEX", "8005e397a404c83377939a188a403c11"
)


# ---------------------------------------------------------------------------
#  Flask App Config (dict untuk app.config.update)
# ---------------------------------------------------------------------------
FLASK_CONFIG = {
    "SECRET_KEY": SECRET_KEY,
    "SQLALCHEMY_DATABASE_URI": os.getenv("GATE_DATABASE_URL", "sqlite:///gate.db"),
    "SQLALCHEMY_TRACK_MODIFICATIONS": False,
    "SESSION_COOKIE_HTTPONLY": True,
    "SESSION_COOKIE_SAMESITE": "Lax",
    "SESSION_COOKIE_SECURE": os.getenv("SESSION_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
    "PERMANENT_SESSION_LIFETIME": 60 * 60 * 8,
    "MAX_CONTENT_LENGTH": int(os.getenv("MAX_CONTENT_LENGTH", str(16 * 1024 * 1024))),
    "JSON_SORT_KEYS": False,
}
