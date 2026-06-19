"""
Comprehensive Integration Test — Smart Souvenir App
====================================================
Alur: Stock (CRUD) → Kasir (Transaksi) → Gate (Detection + Encrypted APIs)
Semua data dummy dibersihkan setelah test selesai.
"""
import os, sys, json, time, hashlib, base64
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

# ============================================================
# Setup
# ============================================================
from app import app
from db import db_cursor

PASS = 0
FAIL = 0
ERRORS = []

# Single client for session persistence
client = app.test_client()

def report(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  [FAIL] {name} — {detail}")

def api(method, path, data=None, json_data=None):
    """Helper to call Flask test client."""
    if method == "GET":
        return client.get(path)
    elif method == "POST":
        if json_data:
            return client.post(path, json=json_data, content_type="application/json")
        elif data:
            return client.post(path, data=data)
        else:
            return client.post(path)
    elif method == "DELETE":
        return client.delete(path)

# ============================================================
# 1. STOCK MODULE TESTS
# ============================================================
print("\n" + "=" * 60)
print("1. STOCK MODULE TESTS")
print("=" * 60)

# 1.1 Login
print("\n  --- Login ---")
r = api("POST", "/stock/login", data={"email": "admin@souvenir.com", "password": "admin123"})
report("Login admin", r.status_code in (200, 302),
       f"Status: {r.status_code}")
# Verify session by accessing protected page with follow_redirects
r2 = client.get("/stock/", follow_redirects=True)
report("Login session active", r2.status_code == 200 and b'Stock' in r2.data,
       f"Status: {r2.status_code}, Has Stock: {b'Stock' in r2.data}")

# 1.2 Create supplier
print("\n  --- Supplier CRUD ---")
r = api("POST", "/stock/supplier_create", data={
    "nama": "PT Test Supplier",
    "alamat": "Jl. Test No. 123",
    "hp": "08123456789",
    "email": "supplier@test.com",
})
report("Create supplier", r.status_code in (200, 302))

# Verify supplier exists
with db_cursor() as (_, cur):
    cur.execute("SELECT * FROM suppliers WHERE nama = %s", ("PT Test Supplier",))
    test_supplier = cur.fetchone()
report("Supplier in DB", test_supplier is not None, "Supplier not found")

# Test encrypted supplier data
r = api("GET", "/stock/api/suppliers_decrypted")
data = json.loads(r.data)
report("Suppliers decrypted API", data.get("ok") == True)
if data.get("ok") and data.get("suppliers"):
    found = [s for s in data["suppliers"] if s["nama"] == "PT Test Supplier"]
    if found:
        s = found[0]
        report("Supplier alamat decrypted", s.get("alamat_decrypted") == "Jl. Test No. 123",
               f"Got: {s.get('alamat_decrypted')}")
        report("Supplier encryption timing", s.get("encrypt_time_ms", 0) >= 0)

# 1.3 Get categories
print("\n  --- Category & Product ---")
with db_cursor() as (_, cur):
    cur.execute("SELECT id, name FROM categories LIMIT 1")
    category = cur.fetchone()
if not category:
    with db_cursor(commit=True) as (_, cur):
        cur.execute("INSERT INTO categories (name) VALUES ('Test Category')")
        category = {"id": cur.lastrowid, "name": "Test Category"}
    created_category = True
else:
    created_category = False
report("Category available", category is not None)

# 1.4 Create product
r = api("POST", "/stock/product_create", data={
    "name": "Baju PENS Test",
    "category_id": category["id"],
    "price": 75000,
    "min_stock": 2,
    "supplier_id": test_supplier["id_supplier"] if test_supplier else 0,
})
report("Create product", r.status_code in (200, 302))

with db_cursor() as (_, cur):
    cur.execute("SELECT * FROM products WHERE name = %s", ("Baju PENS Test",))
    test_product = cur.fetchone()
report("Product in DB", test_product is not None, "Product not found")

# 1.5 Edit product
r = api("POST", "/stock/product_edit", data={
    "id": test_product["id"],
    "name": "Baju PENS Updated",
    "category_id": category["id"],
    "price": 80000,
    "min_stock": 3,
    "supplier_id": test_supplier["id_supplier"] if test_supplier else 0,
})
report("Edit product", r.status_code in (200, 302))

with db_cursor() as (_, cur):
    cur.execute("SELECT name, price FROM products WHERE id = %s", (test_product["id"],))
    updated = cur.fetchone()
report("Product updated name", updated and updated["name"] == "Baju PENS Updated",
       f"Got: {updated}")
report("Product updated price", updated and updated["price"] == 80000,
       f"Got: {updated['price'] if updated else 'None'}")

# 1.6 Restock with RFID tags
print("\n  --- Restock & Items ---")
rfid_tags = "AAAA1111\nBBBB2222\nCCCC3333"
r = api("POST", "/stock/restock", data={
    "product_id": test_product["id"],
    "status": "tersedia",
    "purchase_date": "2026-06-19",
    "rfid_tags": rfid_tags,
})
report("Restock with RFID", r.status_code in (200, 302))

with db_cursor() as (_, cur):
    cur.execute("SELECT * FROM items WHERE product_id = %s AND rfid_tag = %s",
                (test_product["id"], "AAAA1111"))
    item1 = cur.fetchone()
report("Item AAAA1111 created", item1 is not None)

# 1.7 Product detail API
r = api("GET", f"/stock/product_detail?id={test_product['id']}")
detail = json.loads(r.data)
report("Product detail API", detail.get("name") == "Baju PENS Updated",
       f"Got: {detail.get('name')}")
report("Product detail items count", len(detail.get("items", [])) == 3,
       f"Got {len(detail.get('items', []))}")

# 1.8 ML Category prediction
print("\n  --- ML Prediction ---")
r = api("POST", "/stock/api/predict_category", data={"name": "Indomie Goreng"})
pred = json.loads(r.data)
report("ML predict category", pred.get("ok") == True,
       f"Got: {pred.get('message', pred.get('category_name'))}")

# 1.9 RFID inbox
print("\n  --- RFID Inbox ---")
r = api("GET", "/stock/api/insert_rfid?uid=DEADBEEF")
report("Insert RFID inbox", r.status_code == 200)

r = api("GET", "/stock/api/rfid_push?limit=10")
rfid_data = json.loads(r.data)
report("RFID push", rfid_data.get("ok") == True and len(rfid_data.get("tags", [])) > 0,
       f"Got: {rfid_data}")

r = api("GET", "/stock/api/rfid_clear")
report("RFID clear", json.loads(r.data).get("ok") == True)

# 1.10 Item delete
r = api("POST", "/stock/item_delete", data={"id": item1["id"]})
report("Delete item", json.loads(r.data).get("success") == True)

# ============================================================
# 2. KASIR MODULE TESTS
# ============================================================
print("\n" + "=" * 60)
print("2. KASIR MODULE TESTS")
print("=" * 60)

# 2.1 Scan RFID (add to cart)
print("\n  --- Cart & Scanner ---")
r = api("GET", "/kasir/api/scan_rfid?uid=BBBB2222")
scan_data = json.loads(r.data)
report("Scan RFID BBBB2222", scan_data.get("ok") == True,
       f"Got: {scan_data.get('message')}")

r = api("GET", "/kasir/api/scan_rfid?uid=CCCC3333")
scan_data2 = json.loads(r.data)
report("Scan RFID CCCC3333", scan_data2.get("ok") == True,
       f"Got: {scan_data2.get('message')}")

# 2.2 Get cart
r = api("GET", "/kasir/api/cart")
cart = json.loads(r.data)
report("Cart has items", cart.get("ok") == True and cart.get("count", 0) >= 2,
       f"Count: {cart.get('count')}")
report("Cart total > 0", cart.get("total", 0) > 0,
       f"Total: {cart.get('total')}")

# 2.3 Simulate scan
r = api("POST", "/kasir/api/scan_rfid/simulate")
sim = json.loads(r.data)
report("Simulate scan", sim.get("ok") == True, f"Got: {sim.get('message', sim.get('error'))}")

# 2.4 Cart delete
r = api("POST", "/kasir/api/cart/delete", json_data={"id": cart["items"][-1]["id"]})
report("Delete cart item", json.loads(r.data).get("ok") == True)

# Get updated cart
r = api("GET", "/kasir/api/cart")
cart_after = json.loads(r.data)
report("Cart after simulate+delete", cart_after.get("count", 0) == cart.get("count", 0),
       f"Before: {cart.get('count')}, After: {cart_after.get('count')}")

# 2.5 Register member
print("\n  --- Member ---")
r = api("POST", "/kasir/api/member/register", json_data={
    "name": "Test Member",
    "nik": "3507123456789001",
    "phone": "081234567890",
    "address": "Jl. Member Test No. 456",
})
reg = json.loads(r.data)
report("Register member", reg.get("ok") == True,
       f"Got: {reg.get('error', reg.get('message'))}")
report("Welcome points", reg.get("welcome_points") == 100)

# 2.6 Member lookup
r = api("GET", "/kasir/api/member/lookup?phone=081234567890")
lookup = json.loads(r.data)
report("Member lookup", lookup.get("ok") == True and lookup.get("member") is not None,
       f"Got: {lookup.get('message')}")
member_nik = lookup["member"]["nik"] if lookup.get("member") else None
report("Member points = 100", lookup.get("member", {}).get("points") == 100)

# 2.7 Verify hash consistency
with db_cursor() as (_, cur):
    cur.execute("SELECT nik, hp, alamat FROM member WHERE nama = %s", ("Test Member",))
    member_row = cur.fetchone()
if member_row:
    expected_hash = hashlib.sha256(
        f"3507123456789001|kasir-face-recognition-dev-key-2026".encode()
    ).hexdigest()
    report("NIK hash correct", member_row["nik"] == expected_hash,
           f"Expected: {expected_hash[:20]}..., Got: {member_row['nik'][:20]}...")

# 2.8 Top up
r = api("POST", "/kasir/api/member/topup", json_data={
    "nik": member_nik,
    "amount": 50000,
})
topup = json.loads(r.data)
report("Top up member", topup.get("ok") == True and topup.get("new_saldo") == 50000,
       f"Got: {topup}")

# 2.9 Payment process (QR)
print("\n  --- Payment ---")
r = api("GET", "/kasir/api/cart")
cart_for_pay = json.loads(r.data)

cart_items = []
for item in cart_for_pay.get("items", []):
    cart_items.append({
        "product_id": item["product_id"],
        "quantity": item["qty"],
        "price": item["harga"],
        "rfid_tag": item["rfid_tag"],
    })

r = api("POST", "/kasir/api/payment/process", json_data={
    "cart": cart_items,
    "subtotal": cart_for_pay["total"],
    "final_total": cart_for_pay["total"],
    "is_member": True,
    "phone": "081234567890",
    "payment_mode": "regular",
    "redeem_points": 0,
    "earned_points": 50,
})
payment = json.loads(r.data)
report("Payment process", payment.get("ok") == True,
       f"Got: {payment.get('error')}")

# Verify transaction exists
if payment.get("ok"):
    with db_cursor() as (_, cur):
        cur.execute("SELECT * FROM transaksi WHERE id_transaksi = %s",
                    (payment["id_transaksi"],))
        txn = cur.fetchone()
    report("Transaction in DB", txn is not None)

    # Verify items marked as terjual
    with db_cursor() as (_, cur):
        cur.execute("SELECT status FROM items WHERE rfid_tag = %s", ("BBBB2222",))
        item_status = cur.fetchone()
    report("Item marked terjual", item_status and item_status["status"] == "terjual",
           f"Status: {item_status}")

# Verify cart is cleared
r = api("GET", "/kasir/api/cart")
empty_cart = json.loads(r.data)
report("Cart cleared after payment", empty_cart.get("count", 0) == 0,
       f"Count: {empty_cart.get('count')}")

# Verify member points updated
r = api("GET", "/kasir/api/member/lookup?phone=081234567890")
updated_member = json.loads(r.data)
report("Member points updated", updated_member.get("member", {}).get("points") == 150,
       f"Points: {updated_member.get('member', {}).get('points')}")

# ============================================================
# 3. GATE MODULE TESTS
# ============================================================
print("\n" + "=" * 60)
print("3. GATE MODULE TESTS")
print("=" * 60)

# 3.1 Gate status
print("\n  --- Gate Control ---")
r = api("GET", "/gate/api/gate/status")
status = json.loads(r.data)
report("Gate status API", "status" in status)
report("Gate default open", status.get("status") == "open")

# 3.2 Toggle gate
r = api("POST", "/gate/api/gate/toggle")
toggle = json.loads(r.data)
report("Gate toggle", toggle.get("success") == True and toggle.get("status") == "closed")

r = api("POST", "/gate/api/gate/toggle")
toggle2 = json.loads(r.data)
report("Gate toggle back", toggle2.get("status") == "open")

# 3.3 Camera status
print("\n  --- Camera ---")
r = api("GET", "/gate/api/camera/status")
cam_status = json.loads(r.data)
report("Camera status API", "is_running" in cam_status)

# 3.4 Secure detection check (AES-128-GCM)
print("\n  --- Secure APIs (AES-128-GCM) ---")
from gate.payload_crypto import decrypt_request, encrypt_response, _hex_key_from_env, _load_device_keys

# Simulate ESP32 request
import os as _os
import gate.payload_crypto as _pcrypto
_pcrypto._last_counters.clear()
_os.environ["GATE_DEVICE_ID"] = "gate-esp32-01"
_os.environ["GATE_REQUEST_KEY_HEX"] = "7618561da88c350b55ff32bae357efaa"
_os.environ["GATE_RESPONSE_KEY_HEX"] = "8005e397a404c83377939a188a403c11"

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

req_key = bytes.fromhex("7618561da88c350b55ff32bae357efaa")
res_key = bytes.fromhex("8005e397a404c83377939a188a403c11")
boot_id_hex = "A1B2C3D4"
boot_bytes = bytes.fromhex(boot_id_hex)
counter = 999
nonce = boot_bytes + counter.to_bytes(8, "big")
aad = f"gate-esp32-01|{boot_id_hex}|{counter}|/gate/api/secure/detection-check".encode()

plaintext = json.dumps({"event": "person_detection", "ir_detected": True}).encode()
aesgcm_req = AESGCM(req_key)
encrypted = aesgcm_req.encrypt(nonce, plaintext, aad)
# AESGCM returns ciphertext+tag, split them
ct_bytes = encrypted[:-16]
tag_bytes = encrypted[-16:]

envelope = {
    "device_id": "gate-esp32-01",
    "boot_id": boot_id_hex,
    "counter": counter,
    "nonce": base64.b64encode(nonce).decode(),
    "ciphertext": base64.b64encode(ct_bytes).decode(),
    "tag": base64.b64encode(tag_bytes).decode(),
}

r = api("POST", "/gate/api/secure/detection-check", json_data=envelope)
report("Secure detection HTTP 200", r.status_code == 200,
       f"Status: {r.status_code}")

resp_data = json.loads(r.data)
report("Secure detection has ciphertext", "ciphertext" in resp_data,
       f"Keys: {list(resp_data.keys())}")

# Decrypt response
if "ciphertext" in resp_data:
    try:
        aesgcm_res = AESGCM(res_key)
        resp_nonce = base64.b64decode(resp_data["nonce"])
        resp_ct = base64.b64decode(resp_data["ciphertext"])
        resp_tag = base64.b64decode(resp_data["tag"])
        resp_plaintext = aesgcm_res.decrypt(resp_nonce, resp_ct + resp_tag, aad)
        resp_payload = json.loads(resp_plaintext)
        report("Secure detection decrypted", "ok" in resp_payload,
               f"Payload: {resp_payload}")
    except Exception as e:
        report("Secure detection decrypted", False, str(e))

# 3.5 Secure RFID check
print("\n  --- Secure RFID Check ---")
# Clear replay detection state
import gate.payload_crypto as _pc
_pc._last_counters.clear()
counter2 = 500
nonce2 = boot_bytes + counter2.to_bytes(8, "big")
aad2 = f"gate-esp32-01|{boot_id_hex}|{counter2}|/kasir/api/secure/rfid-check".encode()
rfid_plaintext = json.dumps({"event": "rfid_validation", "rfid": "BBBB2222"}).encode()
encrypted2 = AESGCM(req_key).encrypt(nonce2, rfid_plaintext, aad2)
ct2_bytes = encrypted2[:-16]
tag2_bytes = encrypted2[-16:]

envelope2 = {
    "device_id": "gate-esp32-01",
    "boot_id": boot_id_hex,
    "counter": counter2,
    "nonce": base64.b64encode(nonce2).decode(),
    "ciphertext": base64.b64encode(ct2_bytes).decode(),
    "tag": base64.b64encode(tag2_bytes).decode(),
}

r = api("POST", "/kasir/api/secure/rfid-check", json_data=envelope2)
report("Secure RFID check HTTP 200", r.status_code == 200,
       f"Status: {r.status_code}")

resp2 = json.loads(r.data)
if "ciphertext" in resp2:
    try:
        resp2_nonce = base64.b64decode(resp2["nonce"])
        resp2_ct = base64.b64decode(resp2["ciphertext"])
        resp2_tag = base64.b64decode(resp2["tag"])
        resp2_plain = AESGCM(res_key).decrypt(resp2_nonce, resp2_ct + resp2_tag, aad2)
        resp2_payload = json.loads(resp2_plain)
        report("Secure RFID decrypted ok", resp2_payload.get("ok") == True,
               f"Payload: {resp2_payload}")
        report("RFID allowed (item was bought)", resp2_payload.get("allowed") == True,
               f"Allowed: {resp2_payload.get('allowed')}, Msg: {resp2_payload.get('message')}")
    except Exception as e:
        report("Secure RFID decrypted", False, str(e))

# 3.6 Visitor logs & stats
print("\n  --- Logs & Stats ---")
r = api("GET", "/gate/api/logs")
logs = json.loads(r.data)
report("Visitor logs API", "logs" in logs)

r = api("GET", "/gate/api/stats")
stats = json.loads(r.data)
report("Stats API", "today" in stats)

# 3.7 Gate pages
print("\n  --- Gate Pages ---")
r = api("GET", "/gate/")
report("Gate dashboard page", r.status_code == 200 and len(r.data) > 5000)

r = api("GET", "/gate/logs")
report("Gate logs page", r.status_code == 200)

r = api("GET", "/gate/settings")
report("Gate settings page", r.status_code == 200)

# ============================================================
# 4. CROSS-MODULE TESTS
# ============================================================
print("\n" + "=" * 60)
print("4. CROSS-MODULE & HEALTH")
print("=" * 60)

r = api("GET", "/health")
health = json.loads(r.data)
report("Health check", health.get("ok") == True)

r = api("GET", "/kasir/")
report("Kasir page", r.status_code == 200)

r = api("GET", "/stock/login")
report("Stock login page (redirects when logged in)", r.status_code in (200, 302))

# ============================================================
# 5. CLEANUP — Hapus Semua Data Dummy
# ============================================================
print("\n" + "=" * 60)
print("5. CLEANUP")
print("=" * 60)

with db_cursor(commit=True) as (_, cur):
    # Hapus transaksi dummy
    cur.execute("DELETE t, td FROM transaksi t LEFT JOIN transaksi_detail td ON td.id_transaksi = t.id_transaksi WHERE t.tanggal = CURDATE()")
    cur.execute("DELETE FROM transaksi_signature WHERE created_at >= CURDATE()")
    print("  [CLEAN] Transaksi & detail")

    # Hapus buyed
    cur.execute("DELETE FROM buyed WHERE verified_at_gate >= CURDATE()")
    print("  [CLEAN] Buyed")

    # Hapus cart
    cur.execute("DELETE FROM keranjang")
    print("  [CLEAN] Keranjang")

    # Hapus items test
    cur.execute("DELETE FROM items WHERE rfid_tag IN ('AAAA1111', 'BBBB2222', 'CCCC3333')")
    print("  [CLEAN] Items test")

    # Hapus product test
    cur.execute("DELETE FROM products WHERE name LIKE '%Baju PENS%'")
    print("  [CLEAN] Product test")

    # Hapus supplier test
    cur.execute("DELETE FROM suppliers WHERE nama = 'PT Test Supplier'")
    print("  [CLEAN] Supplier test")

    # Hapus member test
    cur.execute("DELETE FROM member_embeddings WHERE member_nik IN (SELECT nik FROM member WHERE nama = 'Test Member')")
    cur.execute("DELETE FROM member WHERE nama = 'Test Member'")
    print("  [CLEAN] Member test")

    # Hapus category test jika dibuat
    if created_category:
        cur.execute("DELETE FROM categories WHERE name = 'Test Category'")
        print("  [CLEAN] Category test")

    # Hapus rfid_inbox
    cur.execute("DELETE FROM rfid_inbox")
    print("  [CLEAN] RFID inbox")

# ============================================================
# REPORT
# ============================================================
print("\n" + "=" * 60)
print("TEST RESULTS")
print("=" * 60)
print(f"  PASSED : {PASS}")
print(f"  FAILED : {FAIL}")
print(f"  TOTAL  : {PASS + FAIL}")

if ERRORS:
    print("\n  ERRORS:")
    for e in ERRORS:
        print(f"    - {e}")
else:
    print("\n  ALL TESTS PASSED!")

print("=" * 60)
