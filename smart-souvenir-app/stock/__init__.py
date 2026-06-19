"""
Stock Blueprint — Inventory Management
=======================================
Migrasi dari stock-app-lengkap/stock-app/app.py ke Blueprint Flask.
"""

import base64
import datetime
import hashlib
import os
import re
import time

import joblib
import pyaes
import scipy.sparse as sp
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from db import db_cursor
from config import STOCK_ENCRYPTION_KEY


stock_bp = Blueprint(
    "stock",
    __name__,
    url_prefix="/stock",
    template_folder="../templates/stock",
    static_folder="../static/stock",
    static_url_path="/stock/static",
)


# ---------------------------------------------------------------------------
#  ML Model
# ---------------------------------------------------------------------------
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "PBL.joblib")


def patch_tfidf(model_step):
    if hasattr(model_step, "steps"):
        for _, step in model_step.steps:
            patch_tfidf(step)
    elif hasattr(model_step, "transformer_list"):
        for _, transformer in model_step.transformer_list:
            patch_tfidf(transformer)
    elif hasattr(model_step, "_tfidf"):
        tf_trans = model_step._tfidf
        if not hasattr(tf_trans, "_idf_diag") and "idf_" in tf_trans.__dict__:
            tf_trans._idf_diag = sp.diags(tf_trans.__dict__["idf_"])


ml_model = None
if os.path.exists(MODEL_PATH):
    print("Loading ML model from:", MODEL_PATH)
    ml_model = joblib.load(MODEL_PATH)
    try:
        patch_tfidf(ml_model)
        print("ML Model patched successfully!")
    except Exception as e:
        print("Warning: Failed to patch ML model:", e)
else:
    print("Warning: ML model PBL.joblib not found at:", MODEL_PATH)


KAMUS_NORMALISASI = {
    "btl": "botol", "bks": "bungkus", "sct": "sachet", "sach": "sachet",
    "gr": "gram", "ml": "mililiter", "pck": "pack", "pak": "pack",
    "pcs": "pieces", "pc": "pieces", "ind": "indonesia", "tbk": "terbuka",
    "pt": "perusahaan", "shmp": "shampoo", "shamp": "shampoo", "shampo": "shampoo",
    "sab": "sabun", "sbn": "sabun", "dtrj": "deterjen", "dtrgen": "deterjen",
    "kcp": "kecap", "srp": "sirup", "syrup": "sirup", "gndm": "gandum",
    "mnyk": "minyak", "indomy": "indomie", "chitatoo": "chitato",
}


def bersihkan_teks(teks):
    teks = str(teks).lower()
    teks = re.sub(r"[^a-z0-9\s]", " ", teks)
    words = teks.split()
    return " ".join(KAMUS_NORMALISASI.get(w, w) for w in words)


# ---------------------------------------------------------------------------
#  Encryption (pyaes)
# ---------------------------------------------------------------------------

def encrypt_data(plain_text, measure_time=False):
    if plain_text is None or plain_text == "":
        return (plain_text, 0) if measure_time else plain_text
    start_time = time.perf_counter()
    key = hashlib.sha256(STOCK_ENCRYPTION_KEY.encode("utf-8")).digest()
    iv = os.urandom(16)
    encrypter = pyaes.Encrypter(pyaes.AESModeOfOperationCBC(key, iv))
    cipher_text = encrypter.feed(plain_text.encode("utf-8")) + encrypter.feed()
    result = base64.b64encode(iv + cipher_text).decode("utf-8")
    elapsed = (time.perf_counter() - start_time) * 1000
    return (result, round(elapsed, 4)) if measure_time else result


def decrypt_data(encrypted_text, measure_time=False):
    if encrypted_text is None or encrypted_text == "":
        return (encrypted_text, 0) if measure_time else encrypted_text
    start_time = time.perf_counter()
    try:
        encrypted_text = str(encrypted_text).strip()
        if len(encrypted_text) < 40:
            elapsed = (time.perf_counter() - start_time) * 1000
            return (encrypted_text, round(elapsed, 4)) if measure_time else encrypted_text
        is_base64 = all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in encrypted_text)
        if not is_base64:
            elapsed = (time.perf_counter() - start_time) * 1000
            return (encrypted_text, round(elapsed, 4)) if measure_time else encrypted_text
        data = base64.b64decode(encrypted_text)
        if len(data) <= 16:
            elapsed = (time.perf_counter() - start_time) * 1000
            return (encrypted_text, round(elapsed, 4)) if measure_time else encrypted_text
        iv = data[:16]
        cipher_text = data[16:]
        key = hashlib.sha256(STOCK_ENCRYPTION_KEY.encode("utf-8")).digest()
        decrypter = pyaes.Decrypter(pyaes.AESModeOfOperationCBC(key, iv))
        decrypted_bytes = decrypter.feed(cipher_text) + decrypter.feed()
        result = decrypted_bytes.decode("utf-8")
        elapsed = (time.perf_counter() - start_time) * 1000
        return (result, round(elapsed, 4)) if measure_time else result
    except Exception:
        elapsed = (time.perf_counter() - start_time) * 1000
        return (encrypted_text, round(elapsed, 4)) if measure_time else encrypted_text


# ---------------------------------------------------------------------------
#  Auth
# ---------------------------------------------------------------------------

def _login_required():
    if not session.get("is_admin"):
        return False
    return True


@stock_bp.before_request
def check_login():
    allowed = [
        "/stock/login", "/stock/login.php",
        "/stock/api/insert_rfid", "/stock/api/insert_rfid.php",
        "/stock/api/predict_category", "/stock/api/predict_category.php",
        "/stock/api/rfid_push", "/stock/api/rfid_push.php",
        "/stock/api/rfid_clear", "/stock/api/rfid_clear.php",
        "/stock/product_detail", "/stock/product_detail.php",
    ]
    path = request.path
    is_allowed = any(path == p or path.endswith(p) for p in allowed)
    if not is_allowed and request.endpoint and "static" not in str(request.endpoint) and not session.get("is_admin"):
        return redirect(url_for("stock.login"))


# ---------------------------------------------------------------------------
#  Auth Routes
# ---------------------------------------------------------------------------

@stock_bp.route("/login", methods=["GET", "POST"])
@stock_bp.route("/login.php", methods=["GET", "POST"])
def login():
    if session.get("is_admin"):
        return redirect(url_for("stock.index"))
    error = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not email or not password:
            error = "Email dan password wajib diisi."
        else:
            with db_cursor() as (_, cur):
                cur.execute("SELECT * FROM user_account WHERE email = %s LIMIT 1", (email,))
                user = cur.fetchone()
            if user:
                if password == user["pass"] and user["level"] == "admin":
                    session["is_admin"] = True
                    session["user_id"] = user["id_user"]
                    session["user_name"] = user["nama"]
                    session["user_email"] = user["email"]
                    session["user_level"] = user["level"]
                    return redirect(url_for("stock.index"))
                else:
                    error = "Email / password salah atau Anda tidak memiliki akses admin."
            else:
                error = "Akun tidak ditemukan."
    return render_template("login.html", error=error)


@stock_bp.route("/logout")
@stock_bp.route("/logout.php")
def logout():
    session.clear()
    return redirect("/kasir/")


# ---------------------------------------------------------------------------
#  Dashboard
# ---------------------------------------------------------------------------

@stock_bp.route("/")
@stock_bp.route("/index.php")
def index():
    with db_cursor() as (_, cur):
        cur.execute("SELECT COUNT(*) as cnt FROM products")
        total_produk = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM items")
        total_item = cur.fetchone()["cnt"]
        cur.execute("""
            SELECT p.id, SUM(i.status='tersedia') AS avail, p.min_stock
            FROM products p LEFT JOIN items i ON i.product_id=p.id
            GROUP BY p.id
        """)
        summary_rows = cur.fetchall()
        stok_tersedia = stok_menipis = stok_habis = 0
        for row in summary_rows:
            avail = int(row["avail"] or 0)
            min_stock = int(row["min_stock"] or 0)
            if avail == 0:
                stok_habis += 1
            elif 0 < avail <= min_stock:
                stok_menipis += 1
            else:
                stok_tersedia += 1
        cur.execute("SELECT id, name FROM categories ORDER BY name")
        cats = cur.fetchall()
        cur.execute("SELECT id_supplier, nama FROM suppliers ORDER BY nama")
        suppliers = cur.fetchall()
        cur.execute("""
            SELECT v.*, c.name AS category_name, s.nama AS supplier_name
            FROM (
              SELECT p.id, p.name, p.category_id, p.price, p.min_stock, p.supplier_id,
                SUM(CASE WHEN i.status = 'tersedia' THEN 1 ELSE 0 END) AS available_cnt,
                MAX(i.updated_at) AS last_update
              FROM products p LEFT JOIN items i ON i.product_id = p.id
              GROUP BY p.id, p.name, p.category_id, p.price, p.min_stock, p.supplier_id
            ) AS v
            LEFT JOIN categories c ON c.id = v.category_id
            LEFT JOIN suppliers s ON s.id_supplier = v.supplier_id
            ORDER BY v.name
        """)
        rows = cur.fetchall()
        for r in rows:
            avail = int(r["available_cnt"] or 0)
            min_st = int(r["min_stock"] or 0)
            status = "Habis" if avail == 0 else ("Menipis" if avail <= min_st else "Tersedia")
            r["status"] = status
            r["badge_class"] = "danger" if status == "Habis" else ("warning" if status == "Menipis" else "success")
            last = "-"
            if r["last_update"]:
                dt = r["last_update"]
                if isinstance(dt, str):
                    dt = datetime.datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
                last = dt.strftime("%d/%m/%Y pukul %H.%M")
            r["formatted_last_update"] = last
        cur.execute("""
            SELECT p.id, p.name, SUM(CASE WHEN i.status = 'tersedia' THEN 1 ELSE 0 END) AS avail
            FROM products p LEFT JOIN items i ON i.product_id = p.id
            GROUP BY p.id, p.name ORDER BY p.name
        """)
        plist = cur.fetchall()
    current_date = datetime.date.today().strftime("%Y-%m-%d")
    return render_template(
        "index.html",
        total_produk=total_produk, total_item=total_item,
        stok_tersedia=stok_tersedia, stok_menipis=stok_menipis, stok_habis=stok_habis,
        cats=cats, suppliers=suppliers, rows=rows, plist=plist, current_date=current_date,
    )


# ---------------------------------------------------------------------------
#  Product CRUD
# ---------------------------------------------------------------------------

@stock_bp.route("/product_create", methods=["POST"])
@stock_bp.route("/product_create.php", methods=["POST"])
def product_create():
    name = request.form.get("name", "").strip()
    category_id = int(request.form.get("category_id", 0))
    price = int(request.form.get("price", 0))
    min_stock = int(request.form.get("min_stock", 0))
    supplier_id = int(request.form.get("supplier_id", 0))
    if supplier_id <= 0:
        supplier_id = None
    if name and category_id:
        with db_cursor(commit=True) as (_, cur):
            cur.execute("SELECT id FROM categories WHERE id = %s LIMIT 1", (category_id,))
            if cur.fetchone():
                cur.execute(
                    "INSERT INTO products (name, category_id, price, min_stock, supplier_id) VALUES (%s, %s, %s, %s, %s)",
                    (name, category_id, price, min_stock, supplier_id),
                )
    return redirect(url_for("stock.index"))


@stock_bp.route("/product_edit", methods=["GET", "POST"])
@stock_bp.route("/product_edit.php", methods=["GET", "POST"])
def product_edit():
    prod_id = int(request.args.get("id", 0) or request.form.get("id", 0))
    if prod_id <= 0:
        return redirect(url_for("stock.index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category_id = int(request.form.get("category_id", 0))
        price = int(request.form.get("price", 0))
        min_stock = int(request.form.get("min_stock", 0))
        supplier_id = int(request.form.get("supplier_id", 0))
        if supplier_id <= 0:
            supplier_id = None
        if name and category_id:
            with db_cursor(commit=True) as (_, cur):
                cur.execute(
                    "UPDATE products SET name = %s, category_id = %s, price = %s, min_stock = %s, supplier_id = %s WHERE id = %s",
                    (name, category_id, price, min_stock, supplier_id, prod_id),
                )
        return redirect(url_for("stock.index"))
    else:
        with db_cursor() as (_, cur):
            cur.execute("SELECT * FROM products WHERE id = %s", (prod_id,))
            product = cur.fetchone()
            if not product:
                return redirect(url_for("stock.index"))
            cur.execute("SELECT id, name FROM categories ORDER BY name")
            cats = cur.fetchall()
            cur.execute("SELECT id_supplier, nama FROM suppliers ORDER BY nama")
            suppliers = cur.fetchall()
        return render_template("product_edit.html", product=product, cats=cats, suppliers=suppliers)


@stock_bp.route("/product_delete", methods=["POST"])
@stock_bp.route("/product_delete.php", methods=["POST"])
def product_delete():
    prod_id = int(request.form.get("id", 0))
    if prod_id > 0:
        with db_cursor(commit=True) as (_, cur):
            cur.execute("DELETE FROM items WHERE product_id = %s", (prod_id,))
            cur.execute("DELETE FROM products WHERE id = %s", (prod_id,))
    return redirect(url_for("stock.index"))


@stock_bp.route("/product_delete_bulk", methods=["POST"])
@stock_bp.route("/product_delete_bulk.php", methods=["POST"])
def product_delete_bulk():
    ids_raw = request.form.get("ids", "").strip()
    if ids_raw:
        ids = [int(x.strip()) for x in ids_raw.split(",") if x.strip()]
        if ids:
            with db_cursor(commit=True) as (_, cur):
                placeholders = ",".join(["%s"] * len(ids))
                cur.execute(f"DELETE FROM items WHERE product_id IN ({placeholders})", tuple(ids))
                cur.execute(f"DELETE FROM products WHERE id IN ({placeholders})", tuple(ids))
    return redirect(url_for("stock.index"))


# ---------------------------------------------------------------------------
#  Item Management
# ---------------------------------------------------------------------------

@stock_bp.route("/item_delete", methods=["POST"])
@stock_bp.route("/item_delete.php", methods=["POST"])
def item_delete():
    item_id = int(request.form.get("id", 0))
    if item_id <= 0:
        return jsonify({"success": False, "message": "ID tidak valid"})
    with db_cursor(commit=True) as (_, cur):
        cur.execute("DELETE FROM items WHERE id = %s", (item_id,))
    return jsonify({"success": True})


@stock_bp.route("/restock", methods=["POST"])
@stock_bp.route("/restock.php", methods=["POST"])
def restock():
    product_id = int(request.form.get("product_id", 0))
    condition = "baru"
    status = request.form.get("status", "tersedia")
    purchase_date = request.form.get("purchase_date") or datetime.date.today().strftime("%Y-%m-%d")
    qty = max(1, int(request.form.get("qty", 1)))
    if product_id <= 0:
        return redirect(url_for("stock.index"))
    rfid_tags_raw = request.form.get("rfid_tags", "").strip()
    rfid_list = []
    if rfid_tags_raw:
        rfid_list = [line.strip() for line in re.split(r"\r\n|\r|\n", rfid_tags_raw) if line.strip()]
        qty = len(rfid_list)
    with db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT name FROM products WHERE id = %s", (product_id,))
        prod = cur.fetchone()
        product_name = prod["name"] if prod else "PROD"
        if not rfid_list:
            cur.execute(
                "SELECT rfid_tag FROM items WHERE product_id = %s AND rfid_tag LIKE '%%-%%' ORDER BY id DESC LIMIT 1",
                (product_id,),
            )
            last_code_row = cur.fetchone()
            last_code = last_code_row["rfid_tag"] if last_code_row else None
            if last_code:
                if "-" in last_code:
                    prefix, seq_part = last_code.split("-", 1)
                    try:
                        last_seq = int(seq_part.lstrip("0") or 0)
                    except ValueError:
                        last_seq = 0
                else:
                    prefix = last_code
                    last_seq = 0
            else:
                first_word = product_name.upper().split()[0] if product_name.split() else "PRD"
                first_word = re.sub(r"[^A-Z0-9]", "", first_word)
                first_word = (first_word[:3] if first_word else "PRD").ljust(3, "X")
                prefix = first_word + "001"
                last_seq = 0
            for i in range(1, qty + 1):
                seq = last_seq + i
                code = prefix + "-" + str(seq).zfill(4)
                try:
                    cur.execute(
                        "INSERT INTO items (product_id, rfid_tag, `condition`, `status`, purchase_date) VALUES (%s, %s, %s, %s, %s)",
                        (product_id, code, condition, status, purchase_date),
                    )
                except Exception:
                    fallback = code + "-" + os.urandom(2).hex()
                    cur.execute(
                        "INSERT INTO items (product_id, rfid_tag, `condition`, `status`, purchase_date) VALUES (%s, %s, %s, %s, %s)",
                        (product_id, fallback, condition, status, purchase_date),
                    )
        else:
            for tag in rfid_list:
                rfid = tag.upper().strip()
                try:
                    cur.execute(
                        "INSERT INTO items (product_id, rfid_tag, `condition`, `status`, purchase_date) VALUES (%s, %s, %s, %s, %s)",
                        (product_id, rfid, condition, status, purchase_date),
                    )
                except Exception:
                    fallback = rfid + "-" + os.urandom(2).hex()
                    cur.execute(
                        "INSERT INTO items (product_id, rfid_tag, `condition`, `status`, purchase_date) VALUES (%s, %s, %s, %s, %s)",
                        (product_id, fallback, condition, status, purchase_date),
                    )
                try:
                    cur.execute("DELETE FROM rfid_inbox")
                except Exception:
                    pass
    return redirect(url_for("stock.index"))


# ---------------------------------------------------------------------------
#  Supplier Management
# ---------------------------------------------------------------------------

@stock_bp.route("/supplier_create", methods=["POST"])
@stock_bp.route("/supplier_create.php", methods=["POST"])
def supplier_create():
    nama = request.form.get("nama", "").strip()
    alamat = encrypt_data(request.form.get("alamat", "").strip())
    hp = request.form.get("hp", "").strip()
    email = encrypt_data(request.form.get("email", "").strip())
    if nama:
        with db_cursor(commit=True) as (_, cur):
            cur.execute(
                "INSERT INTO suppliers (nama, alamat, hp, email) VALUES (%s, %s, %s, %s)",
                (nama, alamat if alamat else None, hp if hp else None, email if email else None),
            )
    return redirect(url_for("stock.index"))


# ---------------------------------------------------------------------------
#  Product Detail API
# ---------------------------------------------------------------------------

@stock_bp.route("/product_detail")
@stock_bp.route("/product_detail.php")
def product_detail():
    prod_id = int(request.args.get("id", 0))
    if prod_id <= 0:
        return jsonify({"error": "Bad request"}), 400
    with db_cursor() as (_, cur):
        cur.execute(
            "SELECT p.id, p.name, c.name AS category FROM products p LEFT JOIN categories c ON c.id = p.category_id WHERE p.id = %s",
            (prod_id,),
        )
        p = cur.fetchone()
        if not p:
            return jsonify({"error": "Not found"}), 404
        cur.execute(
            """
            SELECT SUM(status='tersedia') AS tersedia, SUM(status='dipesan') AS dipesan,
                   SUM(status='terjual') AS terjual, SUM(status='maintenance') AS maintenance
            FROM items WHERE product_id = %s
            """,
            (prod_id,),
        )
        s = cur.fetchone() or {"tersedia": 0, "dipesan": 0, "terjual": 0, "maintenance": 0}
        cur.execute(
            "SELECT id, rfid_tag AS item_code, `condition`, `status`, purchase_date, created_at FROM items WHERE product_id = %s ORDER BY id DESC LIMIT 200",
            (prod_id,),
        )
        items = cur.fetchall()
    formatted_items = []
    for it in items:
        ts_date = None
        if it["purchase_date"]:
            d = it["purchase_date"]
            if isinstance(d, str):
                ts_date = datetime.datetime.strptime(d, "%Y-%m-%d")
            else:
                ts_date = datetime.datetime.combine(d, datetime.time.min)
        ts_time = it["created_at"]
        if isinstance(ts_time, str):
            ts_time = datetime.datetime.strptime(ts_time, "%Y-%m-%d %H:%M:%S")
        if ts_date or ts_time:
            date_part = (ts_date or ts_time).strftime("%d/%m/%Y")
            time_part = ts_time.strftime("%H.%M") if ts_time else "00.00"
            formatted = f"{date_part} pukul {time_part}"
        else:
            formatted = "-"
        formatted_items.append({
            "id": int(it["id"]), "item_code": it["item_code"], "condition": it["condition"],
            "status": it["status"], "purchase_date": formatted,
        })
    return jsonify({
        "name": p["name"], "category": p["category"],
        "summary": {
            "tersedia": int(s["tersedia"] or 0), "dipesan": int(s["dipesan"] or 0),
            "terjual": int(s["terjual"] or 0), "maintenance": int(s["maintenance"] or 0),
        },
        "items": formatted_items,
    })


# ---------------------------------------------------------------------------
#  ML Prediction API
# ---------------------------------------------------------------------------

@stock_bp.route("/api/predict_category", methods=["POST"])
@stock_bp.route("/api/predict_category.php", methods=["POST"])
def api_predict_category():
    name = request.form.get("name", "").strip()
    supplier = request.form.get("supplier", "").strip()
    if not name:
        return jsonify({"ok": False, "message": "Nama produk kosong"})
    if not ml_model:
        return jsonify({"ok": False, "message": "Model ML tidak termuat di server"})
    try:
        teks_input = bersihkan_teks(f"{name} {supplier}")
        scores = ml_model.decision_function([teks_input])[0]
        max_score = float(max(scores))
        hasil = str(ml_model.predict([teks_input])[0])
        if max_score < 0.02 or hasil == "Luar Kategori":
            return jsonify({"ok": False, "message": "Produk di luar kategori model"})
        with db_cursor() as (_, cur):
            cur.execute("SELECT id, name FROM categories WHERE name = %s LIMIT 1", (hasil,))
            category = cur.fetchone()
        if not category:
            return jsonify({"ok": False, "message": f'Kategori "{hasil}" belum ada di database'})
        return jsonify({"ok": True, "category_id": int(category["id"]), "category_name": category["name"], "score": max_score})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


# ---------------------------------------------------------------------------
#  RFID APIs
# ---------------------------------------------------------------------------

@stock_bp.route("/api/rfid_push")
@stock_bp.route("/api/rfid_push.php")
def api_rfid_push():
    try:
        limit = max(1, min(200, int(request.args.get("limit", 50))))
        with db_cursor(commit=True) as (_, cur):
            cur.execute("SELECT id, tag FROM rfid_inbox WHERE consumed = 0 ORDER BY id ASC LIMIT %s", (limit,))
            rows = cur.fetchall()
            if not rows:
                return jsonify({"ok": True, "tags": []})
            ids = [int(row["id"]) for row in rows]
            id_list = ",".join(map(str, ids))
            cur.execute(f"UPDATE rfid_inbox SET consumed = 1 WHERE id IN ({id_list})")
        tags = list(set(row["tag"].strip() for row in rows if row["tag"].strip()))
        return jsonify({"ok": True, "tags": tags})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@stock_bp.route("/api/rfid_clear")
@stock_bp.route("/api/rfid_clear.php")
def api_rfid_clear():
    try:
        with db_cursor(commit=True) as (_, cur):
            cur.execute("DELETE FROM rfid_inbox")
        return jsonify({"ok": True, "message": "rfid_inbox cleared"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@stock_bp.route("/api/insert_rfid", methods=["GET", "POST"])
@stock_bp.route("/api/insert_rfid.php", methods=["GET", "POST"])
def api_insert_rfid():
    uid = request.args.get("uid", "").strip() or request.form.get("uid", "").strip() or (request.get_json(silent=True) or {}).get("uid", "").strip()
    if not uid:
        return "UID kosong", 400
    uid = re.sub(r"[^A-F0-9]", "", uid.upper())[:32]
    if not uid:
        return "UID tidak valid", 400
    with db_cursor(commit=True) as (_, cur):
        cur.execute("INSERT INTO rfid_inbox (tag) VALUES (%s)", (uid,))
    return "OK"


@stock_bp.route("/api/suppliers_decrypted")
@stock_bp.route("/api/suppliers_decrypted.php")
def api_suppliers_decrypted():
    """Get all suppliers with both encrypted (raw) and decrypted data."""
    with db_cursor() as (_, cur):
        cur.execute("SELECT id_supplier, nama, alamat, hp, email FROM suppliers ORDER BY nama")
        suppliers_raw = cur.fetchall()
    suppliers_result = []
    total_encrypt_time = total_decrypt_time = 0
    for s in suppliers_raw:
        alamat_raw = s["alamat"] or ""
        hp_raw = s["hp"] or ""
        email_raw = s["email"] or ""
        alamat_decrypted, alamat_dt = decrypt_data(alamat_raw, measure_time=True)
        email_decrypted, email_dt = decrypt_data(email_raw, measure_time=True)
        total_decrypt_time += alamat_dt + email_dt
        _, alamat_et = encrypt_data(alamat_decrypted, measure_time=True)
        _, email_et = encrypt_data(email_decrypted, measure_time=True)
        total_encrypt_time += alamat_et + email_et
        def format_encrypted(val, max_len=60):
            if not val:
                return ""
            return (val[:max_len] + "...") if len(val) > max_len else val
        suppliers_result.append({
            "id": s["id_supplier"], "nama": s["nama"],
            "alamat_encrypted": format_encrypted(alamat_raw), "hp_encrypted": hp_raw,
            "email_encrypted": format_encrypted(email_raw),
            "alamat_decrypted": alamat_decrypted or "-", "hp_decrypted": hp_raw or "-",
            "email_decrypted": email_decrypted or "-",
            "encrypt_time_ms": round(alamat_et + email_et, 4), "decrypt_time_ms": round(alamat_dt + email_dt, 4),
        })
    return jsonify({
        "ok": True, "suppliers": suppliers_result,
        "total_suppliers": len(suppliers_result),
        "total_encrypt_time_ms": round(total_encrypt_time, 4),
        "total_decrypt_time_ms": round(total_decrypt_time, 4),
        "avg_encrypt_time_ms": round(total_encrypt_time / len(suppliers_result), 4) if suppliers_result else 0,
        "avg_decrypt_time_ms": round(total_decrypt_time / len(suppliers_result), 4) if suppliers_result else 0,
    })
