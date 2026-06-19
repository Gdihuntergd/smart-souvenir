"""
Unified database module for Smart Souvenir Application.

Menggunakan pymysql sebagai driver utama.
Mendukung context manager untuk transaksi.
"""

import os
from contextlib import contextmanager

import pymysql
import pymysql.cursors

from config import DB_HOST, DB_USER, DB_PASS, DB_NAME


def get_db():
    """Membuat koneksi baru ke database MySQL."""
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


@contextmanager
def db_cursor(commit=False):
    """
    Context manager untuk database cursor.

    Usage:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute(...)
    """
    conn = get_db()
    cur = None
    try:
        cur = conn.cursor()
        yield conn, cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        conn.close()


def rupiah(value):
    """Format angka menjadi format Rupiah."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return "Rp " + f"{number:,}".replace(",", ".")


# ---------------------------------------------------------------------------
#  Database Schema Initialization
# ---------------------------------------------------------------------------

def init_db_schema():
    """
    Inisialisasi schema database untuk komponen Stock.
    Dipanggil saat startup.
    """
    try:
        print("[DB] Checking and initializing stock schema...")
        with db_cursor(commit=True) as (_, cur):
            cur.execute("""
                CREATE TABLE IF NOT EXISTS `suppliers` (
                  `id_supplier` INT AUTO_INCREMENT PRIMARY KEY,
                  `nama` VARCHAR(100) NOT NULL,
                  `alamat` TEXT NULL,
                  `hp` VARCHAR(255) NULL,
                  `email` VARCHAR(255) NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS `user_account` (
                  `id_user` INT AUTO_INCREMENT PRIMARY KEY,
                  `email` VARCHAR(100) NOT NULL UNIQUE,
                  `pass` VARCHAR(255) NOT NULL,
                  `nama` VARCHAR(100) NOT NULL,
                  `level` VARCHAR(50) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS `rfid_inbox` (
                  `id` INT AUTO_INCREMENT PRIMARY KEY,
                  `tag` VARCHAR(50) NOT NULL,
                  `consumed` TINYINT(1) DEFAULT 0,
                  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            try:
                cur.execute("SHOW COLUMNS FROM products LIKE 'supplier_id'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE products ADD COLUMN supplier_id INT NULL DEFAULT NULL")
            except Exception:
                pass

            cur.execute("SELECT COUNT(*) as cnt FROM user_account")
            if cur.fetchone()['cnt'] == 0:
                print("[DB] Inserting default admin account...")
                cur.execute("""
                    INSERT INTO user_account (email, pass, nama, level)
                    VALUES ('admin@souvenir.com', 'admin123', 'Admin Stok', 'admin')
                """)
        print("[DB] Stock schema OK")
    except Exception as e:
        print(f"[DB] Stock schema init skipped: {e}")


def ensure_kasir_schema():
    """
    Inisialisasi schema database untuk komponen Kasir.
    Dipanggil saat startup.
    """
    try:
        import hashlib
        from config import KASIR_SECRET_KEY

        print("[DB] Checking and initializing kasir schema...")
        with db_cursor(commit=True) as (_, cur):
            # Tambah kolom saldo ke member jika belum ada
            try:
                cur.execute("ALTER TABLE member ADD COLUMN saldo DECIMAL(12,2) NOT NULL DEFAULT 0")
            except Exception:
                pass

            def _hash_val(val):
                if not val:
                    return ""
                return hashlib.sha256(f"{str(val).strip()}|{KASIR_SECRET_KEY}".encode('utf-8')).hexdigest()

            def is_hash(val):
                if not val:
                    return False
                val_str = str(val).strip()
                return len(val_str) == 64 and all(c in "0123456789abcdef" for c in val_str.lower())

            # Drop FK constraint jika ada
            try:
                cur.execute("ALTER TABLE member_embeddings DROP FOREIGN KEY fk_emb_member")
            except Exception:
                pass

            # Cek data member yang belum di-hash
            try:
                cur.execute("SELECT nik, hp, alamat FROM member")
                members = cur.fetchall()
            except Exception:
                members = []

            to_migrate = []
            for m in members:
                if not is_hash(m["nik"]) or (m["hp"] and not is_hash(m["hp"])) or (m["alamat"] and not is_hash(m["alamat"])):
                    to_migrate.append(m)

            # Alter kolom ke VARCHAR(64) untuk hash
            for stmt in [
                "ALTER TABLE member MODIFY COLUMN nik VARCHAR(64) NOT NULL",
                "ALTER TABLE member MODIFY COLUMN hp VARCHAR(64) DEFAULT NULL",
                "ALTER TABLE member MODIFY COLUMN alamat VARCHAR(64) DEFAULT NULL",
                "ALTER TABLE member_embeddings MODIFY COLUMN member_nik VARCHAR(64) NOT NULL",
                "ALTER TABLE transaksi MODIFY COLUMN nik VARCHAR(64) DEFAULT NULL",
                "ALTER TABLE transaksi_detail MODIFY COLUMN nik VARCHAR(64) DEFAULT NULL",
                "ALTER TABLE transaksi_signature MODIFY COLUMN member_nik VARCHAR(64) NOT NULL",
            ]:
                try:
                    cur.execute(stmt)
                except Exception:
                    pass

            # Migrasi data lama ke hash
            for m in to_migrate:
                old_nik = m["nik"]
                new_nik = _hash_val(old_nik) if not is_hash(old_nik) else old_nik
                new_hp = _hash_val(m["hp"]) if m["hp"] and not is_hash(m["hp"]) else m["hp"]
                new_alamat = _hash_val(m["alamat"]) if m["alamat"] and not is_hash(m["alamat"]) else m["alamat"]

                cur.execute("UPDATE member SET nik=%s, hp=%s, alamat=%s WHERE nik=%s", (new_nik, new_hp, new_alamat, old_nik))
                cur.execute("UPDATE member_embeddings SET member_nik=%s WHERE member_nik=%s", (new_nik, old_nik))
                cur.execute("UPDATE transaksi SET nik=%s WHERE nik=%s", (new_nik, old_nik))
                cur.execute("UPDATE transaksi_detail SET nik=%s WHERE nik=%s", (new_nik, old_nik))
                cur.execute("UPDATE transaksi_signature SET member_nik=%s WHERE member_nik=%s", (new_nik, old_nik))

            # Tabel member_embeddings
            cur.execute("""
                CREATE TABLE IF NOT EXISTS member_embeddings (
                  id INT(11) NOT NULL AUTO_INCREMENT,
                  member_nik VARCHAR(64) NOT NULL,
                  embedding LONGTEXT NOT NULL,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP(),
                  PRIMARY KEY (id),
                  KEY idx_member_emb_nik (member_nik)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # Tabel keranjang
            cur.execute("""
                CREATE TABLE IF NOT EXISTS keranjang (
                  id INT(11) NOT NULL AUTO_INCREMENT,
                  item_id INT(11) DEFAULT NULL,
                  product_id INT(11) DEFAULT NULL,
                  rfid_tag VARCHAR(50) DEFAULT NULL,
                  nama_produk VARCHAR(255) DEFAULT NULL,
                  harga INT(11) DEFAULT 0,
                  qty INT(11) DEFAULT 1,
                  PRIMARY KEY (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # Tabel transaksi_signature
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transaksi_signature (
                  id INT(11) NOT NULL AUTO_INCREMENT,
                  id_transaksi INT(11) NOT NULL,
                  member_nik VARCHAR(64) NOT NULL,
                  signature TEXT NOT NULL,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP(),
                  PRIMARY KEY (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # Hapus kolom data_hash lama jika ada
            try:
                cur.execute("ALTER TABLE member DROP COLUMN data_hash")
            except Exception:
                pass

        print("[DB] Kasir schema OK")
    except Exception as e:
        print(f"[DB] Kasir schema init skipped: {e}")
