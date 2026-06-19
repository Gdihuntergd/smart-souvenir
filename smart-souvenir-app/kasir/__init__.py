"""
Kasir Blueprint — POS + Face Recognition
==========================================
Migrasi dari kasir (2)/kasir/app.py ke Blueprint Flask.
"""

import base64
import hashlib
import json
import os
import time

from flask import Blueprint, jsonify, render_template, request, current_app

from config import KASIR_SECRET_KEY, WELCOME_POINTS, EMBEDDING_ENCRYPTION_KEY
from db import db_cursor
from gate.payload_crypto import (
    PayloadCryptoConfigurationError,
    PayloadCryptoError,
    PayloadReplayError,
    decrypt_request,
    encrypt_response,
)

try:
    from Crypto.Cipher import AES
    from Crypto.PublicKey import RSA
    from Crypto.Signature import pkcs1_15
    from Crypto.Hash import SHA256
    from Crypto.Random import get_random_bytes
    from Crypto.Util.Padding import pad, unpad
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

from kasir.face_service import (
    SIMILARITY_THRESHOLD,
    detections_from_data_url,
    embedding_from_data_url,
    fast_face_boxes_from_data_url,
    score_best_match,
)


kasir_bp = Blueprint(
    "kasir",
    __name__,
    url_prefix="/kasir",
    template_folder="../templates/kasir",
    static_folder="../static/kasir",
    static_url_path="/kasir/static",
)


# ---------------------------------------------------------------------------
#  Helpers & Cryptography
# ---------------------------------------------------------------------------

def _hash_value(val):
    """Calculate cryptographic hash for member sensitive data in-place."""
    if not val:
        return ""
    val_str = str(val).strip()
    return hashlib.sha256(f"{val_str}|{KASIR_SECRET_KEY}".encode("utf-8")).hexdigest()


def _encrypt_embedding(embedding_list):
    """Encrypt face embedding list using AES-256 in CBC mode."""
    if not HAS_CRYPTO:
        return json.dumps(embedding_list, separators=(",", ":"))
    serialized = json.dumps(embedding_list, separators=(",", ":")).encode("utf-8")
    key = EMBEDDING_ENCRYPTION_KEY.encode("utf-8")[:32].ljust(32, b"\0")
    iv = get_random_bytes(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(serialized, AES.block_size))
    combined = iv + ciphertext
    return base64.b64encode(combined).decode("utf-8")


def _decrypt_embedding(encrypted_str):
    """Decrypt face embedding string using AES-256 in CBC mode."""
    if not HAS_CRYPTO:
        return json.loads(encrypted_str)
    try:
        key = EMBEDDING_ENCRYPTION_KEY.encode("utf-8")[:32].ljust(32, b"\0")
        combined = base64.b64decode(encrypted_str.encode("utf-8"))
        iv = combined[:16]
        ciphertext = combined[16:]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return json.loads(decrypted.decode("utf-8"))
    except Exception:
        try:
            return json.loads(encrypted_str)
        except Exception:
            raise RuntimeError("Gagal melakukan dekripsi data biometric")


def _get_signing_key():
    """Load or generate RSA key pair for transaction log signatures."""
    if not HAS_CRYPTO:
        return None
    key_path = os.path.join(os.path.dirname(__file__), "private_key.pem")
    pub_path = os.path.join(os.path.dirname(__file__), "public_key.pem")
    if not os.path.exists(key_path):
        key = RSA.generate(2048)
        with open(key_path, "wb") as f:
            f.write(key.export_key())
        with open(pub_path, "wb") as f:
            f.write(key.publickey().export_key())
    else:
        with open(key_path, "rb") as f:
            key = RSA.import_key(f.read())
    return key


def _sign_transaction_log(id_transaksi, member_nik, embedding_list, grand_total, date_str, time_str):
    """Generate a digital signature (RSA-SHA256) for a face payment transaction log."""
    if not HAS_CRYPTO:
        return ""
    try:
        key = _get_signing_key()
        embedding_str = json.dumps(embedding_list, separators=(",", ":"))
        embedding_hash = SHA256.new(embedding_str.encode("utf-8")).hexdigest()
        payload = f"TX:{id_transaksi}|NIK:{member_nik}|EMB:{embedding_hash}|TOTAL:{grand_total}|DATE:{date_str}|TIME:{time_str}"
        h = SHA256.new(payload.encode("utf-8"))
        signature = pkcs1_15.new(key).sign(h)
        return base64.b64encode(signature).decode("utf-8")
    except Exception as exc:
        print(f"Error signing transaction log: {exc}")
        return ""


def _json_error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _camera_image():
    """Extract base64 image from JSON body."""
    payload = request.get_json(silent=True) or {}
    return payload.get("image")


def _fetch_member_embeddings():
    """Fetch all embeddings joined with member names for recognition."""
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT e.id, e.member_nik, e.embedding, m.nama
            FROM member_embeddings e
            JOIN member m ON m.nik = e.member_nik
            ORDER BY e.id ASC
            """
        )
        rows = cur.fetchall()
        decrypted_rows = []
        for r in rows:
            try:
                decrypted = _decrypt_embedding(r["embedding"])
                r["embedding"] = json.dumps(decrypted, separators=(",", ":"))
                decrypted_rows.append(r)
            except Exception as exc:
                print(f"Error decrypting embedding for NIK {r['member_nik']}: {exc}")
        return decrypted_rows


def clean_uid(uid, limit=64):
    import re
    uid = re.sub(r"[^A-Fa-f0-9]", "", uid or "").upper()
    return uid[:limit]


# ---------------------------------------------------------------------------
#  Pages
# ---------------------------------------------------------------------------

@kasir_bp.get("/")
def index():
    return render_template("kasir.html")


# ---------------------------------------------------------------------------
#  API — Cart & Scanner
# ---------------------------------------------------------------------------

@kasir_bp.get("/api/cart")
def api_cart():
    """Return current cart contents from keranjang table."""
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT id, item_id, product_id, rfid_tag, nama_produk, harga, qty
            FROM keranjang ORDER BY id ASC
            """
        )
        rows = cur.fetchall()
    total = sum(r["harga"] * r["qty"] for r in rows)
    return jsonify({"ok": True, "items": rows, "total": total, "count": len(rows)})


@kasir_bp.get("/api/scan_rfid")
@kasir_bp.get("/api/scan_rfid.php")
def api_scan_rfid():
    """Scan RFID tag -> find product -> add to cart."""
    uid = request.args.get("uid", "").strip().upper()
    uid = "".join(c for c in uid if c in "0123456789ABCDEF")
    if not uid:
        return jsonify({"ok": False, "items": [], "message": "UID kosong"})
    with db_cursor(commit=True) as (_, cur):
        cur.execute(
            """
            SELECT i.id AS item_id, i.product_id, i.rfid_tag,
                   p.name AS nama_produk, p.price AS harga
            FROM items i
            JOIN products p ON p.id = i.product_id
            WHERE i.rfid_tag LIKE %s AND i.status = 'tersedia'
            LIMIT 1
            """,
            (uid + "%",),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"ok": True, "items": [], "message": "Tag RFID tidak terdaftar"})
        cur.execute(
            """
            INSERT INTO keranjang (item_id, product_id, rfid_tag, nama_produk, harga, qty)
            VALUES (%s, %s, %s, %s, %s, 1)
            """,
            (row["item_id"], row["product_id"], row["rfid_tag"], row["nama_produk"], row["harga"]),
        )
        cur.execute("UPDATE items SET status = 'dipesan' WHERE id = %s", (row["item_id"],))
        item = {
            "id": int(row["item_id"]),
            "product_id": row["product_id"],
            "rfid_tag": row["rfid_tag"],
            "name": row["nama_produk"],
            "price": int(row["harga"]),
            "emoji": "item",
            "qty": 1,
        }
    return jsonify({"ok": True, "items": [item], "message": "Produk berhasil ditambahkan ke keranjang"})


@kasir_bp.post("/api/scan_rfid/simulate")
def api_scan_rfid_simulate():
    """Simulate RFID tag scan by finding a random available product."""
    with db_cursor(commit=True) as (_, cur):
        cur.execute(
            """
            SELECT i.id AS item_id, i.product_id, i.rfid_tag,
                   p.name AS nama_produk, p.price AS harga
            FROM items i
            JOIN products p ON p.id = i.product_id
            WHERE i.status = 'tersedia'
            ORDER BY RAND()
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Tidak ada barang dengan status 'tersedia' di database."})
        cur.execute(
            """
            INSERT INTO keranjang (item_id, product_id, rfid_tag, nama_produk, harga, qty)
            VALUES (%s, %s, %s, %s, %s, 1)
            """,
            (row["item_id"], row["product_id"], row["rfid_tag"], row["nama_produk"], row["harga"]),
        )
        item = {
            "id": int(row["item_id"]),
            "product_id": row["product_id"],
            "rfid_tag": row["rfid_tag"],
            "name": row["nama_produk"],
            "price": int(row["harga"]),
            "emoji": "🛍️",
            "qty": 1,
        }
    return jsonify({"ok": True, "item": item, "message": f"Simulasi scan berhasil: {row['nama_produk']}"})


@kasir_bp.post("/api/cart/delete")
def api_cart_delete():
    """Delete item from keranjang by id."""
    item_id = request.form.get("id") or (request.get_json(silent=True) or {}).get("id")
    if not item_id:
        return _json_error("ID tidak diberikan")
    with db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT item_id FROM keranjang WHERE id = %s LIMIT 1", (item_id,))
        row = cur.fetchone()
        cur.execute("DELETE FROM keranjang WHERE id = %s", (item_id,))
        if row:
            cur.execute("SELECT COUNT(*) AS total FROM keranjang WHERE item_id = %s", (row["item_id"],))
            remaining = cur.fetchone()
            if int(remaining["total"] or 0) == 0:
                cur.execute("UPDATE items SET status = 'tersedia' WHERE id = %s AND status = 'dipesan'", (row["item_id"],))
    return jsonify({"ok": True, "message": "Item dihapus"})


# ---------------------------------------------------------------------------
#  API — Member
# ---------------------------------------------------------------------------

@kasir_bp.get("/api/member/lookup")
def api_member_lookup():
    """Lookup member by phone number."""
    phone = request.args.get("phone", "").strip()
    if len(phone) == 64 and all(c in "0123456789abcdefABCDEF" for c in phone):
        hashed_phone = phone.lower()
    else:
        digits = "".join(c for c in phone if c.isdigit())
        if digits.startswith("62") and len(digits) > 2:
            digits = "0" + digits[2:]
        if not digits:
            return jsonify({"ok": False, "member": None, "message": "Nomor HP kosong"})
        hashed_phone = _hash_value(digits)
    with db_cursor() as (_, cur):
        cur.execute(
            "SELECT nik, nama, alamat, hp, total_poin, saldo FROM member WHERE hp = %s LIMIT 1",
            (hashed_phone,),
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"ok": True, "member": None, "message": "Nomor tidak terdaftar"})
    has_face = False
    with db_cursor() as (_, cur):
        cur.execute("SELECT COUNT(*) AS cnt FROM member_embeddings WHERE member_nik = %s", (row["nik"],))
        cnt = cur.fetchone()
        has_face = cnt and cnt["cnt"] > 0
    return jsonify({
        "ok": True,
        "member": {
            "nik": row["nik"],
            "name": row["nama"],
            "phone": row["hp"],
            "points": int(row["total_poin"] or 0),
            "saldo": float(row["saldo"] or 0),
            "has_face": has_face,
        },
    })


@kasir_bp.post("/api/member/register")
def api_member_register():
    """Register a new member."""
    data = request.form if request.form else (request.get_json(silent=True) or {})
    name = str(data.get("name", "")).strip()
    nik = str(data.get("nik", "")).strip()
    phone = str(data.get("phone", "")).strip()
    address = str(data.get("address", "")).strip()
    if not name or not nik or not phone:
        return _json_error("Nama, NIK, dan HP wajib diisi")
    phone_digits = "".join(c for c in phone if c.isdigit())
    if phone_digits.startswith("62") and len(phone_digits) > 2:
        phone_digits = "0" + phone_digits[2:]
    hashed_nik = _hash_value(nik)
    hashed_phone = _hash_value(phone_digits)
    hashed_address = _hash_value(address)
    with db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT nik FROM member WHERE nik = %s OR hp = %s LIMIT 1", (hashed_nik, hashed_phone))
        if cur.fetchone():
            return _json_error("NIK atau HP sudah terdaftar")
        cur.execute(
            """
            INSERT INTO member (nik, nama, jk, alamat, hp, total_poin, saldo)
            VALUES (%s, %s, NULL, %s, %s, %s, 0)
            """,
            (hashed_nik, name, hashed_address, hashed_phone, WELCOME_POINTS),
        )
    return jsonify({"ok": True, "welcome_points": WELCOME_POINTS, "nik": hashed_nik})


@kasir_bp.post("/api/member/enroll-face")
def api_member_enroll_face():
    """Enroll face data for an existing member using camera capture."""
    data = request.get_json(silent=True) or {}
    nik = data.get("nik", "").strip()
    image_data = data.get("image")
    if not nik:
        return _json_error("NIK member wajib diisi")
    if not image_data:
        return _json_error("Gambar wajah belum tersedia")
    with db_cursor() as (_, cur):
        cur.execute("SELECT nik, nama FROM member WHERE nik = %s", (nik,))
        member = cur.fetchone()
        if not member:
            return _json_error("Member tidak ditemukan")
    try:
        embedding = embedding_from_data_url(image_data)
    except Exception as exc:
        return _json_error(f"Gagal memproses wajah: {exc}")
    try:
        encrypted_embedding = _encrypt_embedding(embedding)
    except Exception as exc:
        return _json_error(f"Gagal mengenkripsi template biometric: {exc}")
    with db_cursor(commit=True) as (_, cur):
        cur.execute(
            "INSERT INTO member_embeddings (member_nik, embedding) VALUES (%s, %s)",
            (nik, encrypted_embedding),
        )
    return jsonify({"ok": True, "message": f"Data wajah berhasil disimpan untuk {member['nama']}"})


@kasir_bp.post("/api/member/topup")
def api_member_topup():
    """Top up member balance (saldo)."""
    data = request.get_json(silent=True) or {}
    nik = data.get("nik", "").strip()
    amount = data.get("amount", 0)
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return _json_error("Jumlah top-up tidak valid")
    if not nik:
        return _json_error("NIK member wajib diisi")
    if amount <= 0:
        return _json_error("Jumlah top-up harus lebih dari 0")
    with db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT nik, saldo FROM member WHERE nik = %s", (nik,))
        member = cur.fetchone()
        if not member:
            return _json_error("Member tidak ditemukan")
        new_saldo = float(member["saldo"] or 0) + amount
        cur.execute("UPDATE member SET saldo = %s WHERE nik = %s", (new_saldo, nik))
    return jsonify({"ok": True, "new_saldo": new_saldo})


# ---------------------------------------------------------------------------
#  API — Face Recognition
# ---------------------------------------------------------------------------

@kasir_bp.post("/api/face/detect")
def api_face_detect():
    """Fast face detection (bounding boxes only, no recognition)."""
    image_data = _camera_image()
    if not image_data:
        return _json_error("Gambar dari kamera belum tersedia")
    try:
        result = fast_face_boxes_from_data_url(image_data)
    except Exception as exc:
        return jsonify({
            "ok": True, "status": "NO_FACE", "label": "WAJAH TIDAK TERDETEKSI",
            "message": str(exc), "frame": None, "detections": [],
        })
    count = len(result["detections"])
    return jsonify({
        "ok": True,
        "status": "DETECTING" if count else "NO_FACE",
        "label": f"{count} WAJAH TERPANTAU" if count else "WAJAH TIDAK TERPANTAU",
        "frame": {"width": result["width"], "height": result["height"]},
        "detections": result["detections"],
    })


@kasir_bp.post("/api/face/verify")
def api_face_verify():
    """Recognize face from camera image and return matched member info."""
    image_data = _camera_image()
    if not image_data:
        return _json_error("Gambar dari kamera belum tersedia")
    rows = _fetch_member_embeddings()
    if not rows:
        return jsonify({"ok": True, "status": "NO_DATA", "message": "Belum ada data wajah member terdaftar", "member": None})
    try:
        frame_result = detections_from_data_url(image_data)
    except Exception as exc:
        return jsonify({"ok": True, "status": "NO_FACE", "message": str(exc), "member": None})
    best_overall = None
    for item in frame_result["detections"]:
        best = score_best_match(item["embedding"], rows)
        if best and (best_overall is None or best["score"] > best_overall["score"]):
            best_overall = best
    if best_overall and best_overall["score"] >= SIMILARITY_THRESHOLD:
        with db_cursor() as (_, cur):
            cur.execute("SELECT nik, nama, alamat, hp, total_poin, saldo FROM member WHERE nik = %s", (best_overall["member_nik"],))
            member = cur.fetchone()
        if member:
            return jsonify({
                "ok": True, "status": "MEMBER", "message": f"Wajah dikenali: {member['nama']}",
                "score": round(best_overall["score"], 4), "threshold": SIMILARITY_THRESHOLD,
                "member": {
                    "nik": member["nik"], "name": member["nama"], "phone": member["hp"],
                    "points": int(member["total_poin"] or 0), "saldo": float(member["saldo"] or 0), "has_face": True,
                },
            })
    return jsonify({
        "ok": True, "status": "NOT_RECOGNIZED", "message": "Wajah tidak dikenali sebagai member",
        "score": round(best_overall["score"], 4) if best_overall else None,
        "threshold": SIMILARITY_THRESHOLD, "member": None,
    })


# ---------------------------------------------------------------------------
#  API — Payment Processing
# ---------------------------------------------------------------------------

@kasir_bp.post("/api/payment/process")
def api_payment_process():
    """Process payment transaction (QR-based, non-face)."""
    data = request.get_json(silent=True) or {}
    cart = data.get("cart", [])
    subtotal = int(data.get("subtotal", 0))
    final_total = int(data.get("final_total", 0))
    is_member = bool(data.get("is_member"))
    phone = str(data.get("phone", "")).strip()
    payment_mode = data.get("payment_mode", "regular")
    redeem_points = int(data.get("redeem_points", 0))
    earned_points = int(data.get("earned_points", 0))
    if not cart or subtotal <= 0 or final_total < 0:
        return _json_error("Data transaksi tidak valid")
    with db_cursor(commit=True) as (conn, cur):
        nik = None
        member_row = None
        if is_member and phone:
            if len(phone) == 64 and all(c in "0123456789abcdefABCDEF" for c in phone):
                query_phone = phone.lower()
            else:
                digits = "".join(c for c in phone if c.isdigit())
                if digits.startswith("62") and len(digits) > 2:
                    digits = "0" + digits[2:]
                query_phone = _hash_value(digits)
            cur.execute("SELECT * FROM member WHERE hp = %s FOR UPDATE", (query_phone,))
            member_row = cur.fetchone()
            if not member_row:
                return _json_error("Member tidak ditemukan")
            nik = member_row["nik"]
            if payment_mode == "redeem" and redeem_points > int(member_row["total_poin"] or 0):
                return _json_error("Poin tidak mencukupi")
        cur.execute(
            """
            INSERT INTO transaksi (product_id, qty, nik, grand_total, tanggal, jam, id_user)
            VALUES (NULL, 0, %s, %s, CURDATE(), CURTIME(), NULL)
            """,
            (nik, final_total),
        )
        id_transaksi = cur.lastrowid
        remaining_discount = max(0, redeem_points)
        for c in cart:
            product_id = int(c.get("product_id", 0))
            qty = max(1, int(c.get("quantity", 1)))
            price = int(c.get("price", 0))
            rfid_tag = c.get("rfid_tag")
            line_total = price * qty
            diskon_row = 0
            if remaining_discount > 0:
                diskon_row = min(remaining_discount, line_total)
                remaining_discount -= diskon_row
            sub_total_row = line_total - diskon_row
            cur.execute(
                """
                INSERT INTO transaksi_detail
                (id_transaksi, product_id, nik, tanggal_pembelian, jam_pembelian, diskon, status_transaksi, sub_total)
                VALUES (%s, %s, %s, CURDATE(), CURTIME(), %s, 1, %s)
                """,
                (id_transaksi, product_id, nik, diskon_row, sub_total_row),
            )
            if rfid_tag:
                cur.execute("UPDATE items SET status = 'terjual' WHERE rfid_tag = %s LIMIT 1", (rfid_tag,))
                cur.execute("INSERT INTO buyed (id_transaksi, product_id, rfid_tag) VALUES (%s, %s, %s)", (id_transaksi, product_id, rfid_tag))
        if is_member and member_row:
            new_points = max(0, int(member_row["total_poin"] or 0) - redeem_points + earned_points)
            cur.execute("UPDATE member SET total_poin = %s WHERE nik = %s", (new_points, nik))
        cur.execute("DELETE FROM keranjang")
    return jsonify({"ok": True, "id_transaksi": id_transaksi})


@kasir_bp.post("/api/payment/face-pay")
def api_payment_face_pay():
    """Pay via face recognition — verify face, deduct saldo, process transaction."""
    data = request.get_json(silent=True) or {}
    image_data = data.get("image")
    cart = data.get("cart", [])
    subtotal = int(data.get("subtotal", 0))
    final_total = int(data.get("final_total", 0))
    payment_mode = data.get("payment_mode", "regular")
    redeem_points = int(data.get("redeem_points", 0))
    earned_points = int(data.get("earned_points", 0))
    if not image_data:
        return _json_error("Gambar wajah belum tersedia")
    if not cart or subtotal <= 0 or final_total < 0:
        return _json_error("Data transaksi tidak valid")
    rows = _fetch_member_embeddings()
    if not rows:
        return _json_error("Belum ada data wajah member terdaftar")
    try:
        frame_result = detections_from_data_url(image_data)
    except Exception as exc:
        return _json_error(f"Wajah tidak terdeteksi: {exc}")
    best_overall = None
    for item in frame_result["detections"]:
        best = score_best_match(item["embedding"], rows)
        if best and (best_overall is None or best["score"] > best_overall["score"]):
            best_overall = best
    if not best_overall or best_overall["score"] < SIMILARITY_THRESHOLD:
        return _json_error("Wajah tidak dikenali sebagai member terdaftar")
    member_nik = best_overall["member_nik"]
    with db_cursor(commit=True) as (conn, cur):
        cur.execute("SELECT * FROM member WHERE nik = %s FOR UPDATE", (member_nik,))
        member_row = cur.fetchone()
        if not member_row:
            return _json_error("Member tidak ditemukan")
        current_saldo = float(member_row["saldo"] or 0)
        if current_saldo < final_total:
            return _json_error(f"Saldo tidak mencukupi. Saldo: Rp {current_saldo:,.0f}, Total: Rp {final_total:,.0f}")
        if payment_mode == "redeem" and redeem_points > int(member_row["total_poin"] or 0):
            return _json_error("Poin tidak mencukupi")
        new_saldo = current_saldo - final_total
        cur.execute("UPDATE member SET saldo = %s WHERE nik = %s", (new_saldo, member_nik))
        cur.execute(
            """
            INSERT INTO transaksi (product_id, qty, nik, grand_total, tanggal, jam, id_user)
            VALUES (NULL, 0, %s, %s, CURDATE(), CURTIME(), NULL)
            """,
            (member_nik, final_total),
        )
        id_transaksi = cur.lastrowid
        remaining_discount = max(0, redeem_points)
        for c in cart:
            product_id = int(c.get("product_id", 0))
            qty = max(1, int(c.get("quantity", 1)))
            price = int(c.get("price", 0))
            rfid_tag = c.get("rfid_tag")
            line_total = price * qty
            diskon_row = 0
            if remaining_discount > 0:
                diskon_row = min(remaining_discount, line_total)
                remaining_discount -= diskon_row
            sub_total_row = line_total - diskon_row
            cur.execute(
                """
                INSERT INTO transaksi_detail
                (id_transaksi, product_id, nik, tanggal_pembelian, jam_pembelian, diskon, status_transaksi, sub_total)
                VALUES (%s, %s, %s, CURDATE(), CURTIME(), %s, 1, %s)
                """,
                (id_transaksi, product_id, member_nik, diskon_row, sub_total_row),
            )
            if rfid_tag:
                cur.execute("UPDATE items SET status = 'terjual' WHERE rfid_tag = %s LIMIT 1", (rfid_tag,))
                cur.execute("INSERT INTO buyed (id_transaksi, product_id, rfid_tag) VALUES (%s, %s, %s)", (id_transaksi, product_id, rfid_tag))
        new_points = max(0, int(member_row["total_poin"] or 0) - redeem_points + earned_points)
        cur.execute("UPDATE member SET total_poin = %s WHERE nik = %s", (new_points, member_nik))
        cur.execute("DELETE FROM keranjang")
        embedding_val = []
        for r in rows:
            if r["id"] == best_overall["embedding_id"]:
                embedding_val = json.loads(r["embedding"])
                break
        cur.execute("SELECT CURDATE() AS cur_date, CURTIME() AS cur_time")
        date_time_row = cur.fetchone()
        date_str = str(date_time_row["cur_date"])
        time_str = str(date_time_row["cur_time"])
        sig_str = _sign_transaction_log(id_transaksi, member_nik, embedding_val, final_total, date_str, time_str)
        cur.execute(
            """
            INSERT INTO transaksi_signature (id_transaksi, member_nik, signature)
            VALUES (%s, %s, %s)
            """,
            (id_transaksi, member_nik, sig_str),
        )
    return jsonify({
        "ok": True, "id_transaksi": id_transaksi, "member_name": member_row["nama"],
        "new_saldo": new_saldo, "new_points": new_points, "score": round(best_overall["score"], 4),
    })


# ---------------------------------------------------------------------------
#  Helpers for secure endpoint
# ---------------------------------------------------------------------------

def _elapsed_us(start_ns):
    return max(0, (time.perf_counter_ns() - start_ns) // 1000)


def normalize_rfid(rfid):
    return (rfid or "").replace(" ", "").strip().upper()


# ---------------------------------------------------------------------------
#  Secure RFID gate endpoint (AES-128-GCM payload)
# ---------------------------------------------------------------------------

@kasir_bp.post("/api/secure/rfid-check")
def secure_rfid_check():
    """
    Endpoint terenkripsi untuk validasi RFID gate keluar.
    POST /kasir/api/secure/rfid-check
    """
    endpoint_path = "/kasir/api/secure/rfid-check"
    envelope = request.get_json(silent=True)

    decrypt_started = time.perf_counter_ns()

    try:
        crypto_context = decrypt_request(envelope, endpoint_path)
    except PayloadReplayError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except PayloadCryptoConfigurationError as exc:
        current_app.logger.error("Konfigurasi secure RFID tidak valid: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
    except PayloadCryptoError as exc:
        current_app.logger.warning("Secure RFID request ditolak: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 400

    server_decrypt_us = _elapsed_us(decrypt_started)
    process_started = time.perf_counter_ns()

    try:
        event_name = str(crypto_context.payload.get("event", "")).strip()

        if event_name != "rfid_validation":
            business_payload = {
                "ok": False, "allowed": False,
                "message": "Event harus rfid_validation", "already_verified": False,
            }
            business_status = 422
        else:
            rfid = normalize_rfid(crypto_context.payload.get("rfid", ""))

            if not rfid:
                business_payload = {
                    "ok": False, "allowed": False,
                    "message": "RFID kosong", "already_verified": False,
                }
                business_status = 400
            else:
                with db_cursor(commit=True) as (_, cur):
                    cur.execute(
                        """
                        SELECT id, verified_at_gate
                        FROM buyed
                        WHERE REPLACE(UPPER(rfid_tag), ' ', '') = %s
                        ORDER BY id DESC LIMIT 1 FOR UPDATE
                        """,
                        (rfid,),
                    )
                    row = cur.fetchone()

                    already_verified = bool(row and int(row["verified_at_gate"] or 0) == 1)

                    if row and not already_verified:
                        cur.execute(
                            "UPDATE buyed SET verified_at_gate = 1, updated_at = NOW() WHERE id = %s",
                            (row["id"],),
                        )

                if row:
                    business_payload = {
                        "ok": True, "allowed": True,
                        "message": "RFID valid, sudah dibeli",
                        "already_verified": already_verified,
                    }
                    business_status = 200
                else:
                    business_payload = {
                        "ok": True, "allowed": False,
                        "message": "RFID tidak ditemukan di tabel buyed",
                        "already_verified": False,
                    }
                    business_status = 404

    except Exception:
        current_app.logger.exception("Pemrosesan secure RFID gagal")
        business_payload = {
            "ok": False, "allowed": False,
            "message": "Internal secure RFID error", "already_verified": False,
        }
        business_status = 500

    server_process_us = _elapsed_us(process_started)

    response_plaintext = dict(business_payload)
    response_plaintext["service_http_code"] = business_status
    response_plaintext["server_decrypt_us"] = server_decrypt_us
    response_plaintext["server_process_us"] = server_process_us

    encrypt_started = time.perf_counter_ns()

    try:
        response_envelope = encrypt_response(crypto_context, response_plaintext)
    except (PayloadCryptoError, PayloadCryptoConfigurationError) as exc:
        current_app.logger.exception("Enkripsi response secure RFID gagal")
        return jsonify({"ok": False, "error": str(exc)}), 500

    response_envelope["server_encrypt_us"] = _elapsed_us(encrypt_started)

    return jsonify(response_envelope), 200
