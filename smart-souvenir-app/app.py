"""
Smart Souvenir — Unified Flask Application
============================================
Menggabungkan 3 komponen:
1. Kasir POS + Face Recognition (dari kasir(2))
2. Stock Management + ML (dari stock-app-lengkap)
3. Gate Detection System (dari flask-smart-souvenir)

Database: MySQL — smart_souvenir_complete
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from functools import wraps
from typing import Any, Callable, TypeVar

from dotenv import load_dotenv

load_dotenv()

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
)
from werkzeug.security import check_password_hash

from config import FLASK_CONFIG
from db import db_cursor, rupiah


ViewFunction = TypeVar("ViewFunction", bound=Callable[..., Any])


def env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def clean_uid(uid, limit=64):
    uid = re.sub(r"[^A-Fa-f0-9]", "", uid or "").upper()
    return uid[:limit]


def normalize_rfid(rfid: str | None) -> str:
    return (rfid or "").replace(" ", "").strip().upper()


def verify_admin_password(stored_password: str | None, submitted_password: str) -> bool:
    stored = str(stored_password or "")
    if not stored:
        return False
    hashed_prefixes = ("scrypt:", "pbkdf2:", "argon2:")
    if stored.startswith(hashed_prefixes):
        try:
            return check_password_hash(stored, submitted_password)
        except ValueError:
            return False
    return stored == submitted_password


def login_required(view: ViewFunction) -> ViewFunction:
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect("/stock/login")
        return view(*args, **kwargs)
    return wrapped  # type: ignore[return-value]


def create_app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.config.update(FLASK_CONFIG)
    flask_app.jinja_env.filters["rupiah"] = rupiah

    # --- Register Blueprints ---
    from kasir import kasir_bp
    from stock import stock_bp
    from gate import gate_bp, init_gate_db
    from gate.database import db as gate_db
    from db import init_db_schema, ensure_kasir_schema

    # Gate SQLAlchemy must be initialized before blueprint registration
    gate_db.init_app(flask_app)

    flask_app.register_blueprint(kasir_bp)
    flask_app.register_blueprint(stock_bp)
    flask_app.register_blueprint(gate_bp)

    # Init gate database tables
    init_gate_db(flask_app)

    # Init stock & kasir MySQL schema
    init_db_schema()
    ensure_kasir_schema()

    # --- Root & Health ---
    @flask_app.get("/")
    def root():
        return redirect("/kasir/")

    @flask_app.get("/health")
    def health_check():
        return jsonify({
            "ok": True,
            "service": "smart-souvenir-unified",
            "time": datetime.now().isoformat(),
        })

    return flask_app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
