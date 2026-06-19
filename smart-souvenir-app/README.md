# 🏪 Smart Souvenir — Unified POS & Inventory System

> Sistem Point-of-Sale terpadu dengan Face Recognition, Manajemen Stok berbasis ML, dan Gate Detection berbasis YOLOv8 untuk toko souvenir.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3119/)
[![Flask](https://img.shields.io/badge/Flask-3.1.3-black?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 📖 Daftar Isi

- [Gambaran Umum](#-gambaran-umum)
- [Fitur](#-fitur)
- [Arsitektur Sistem](#-arsitektur-sistem)
- [Teknologi](#-teknologi)
- [Prasyarat](#-prasyarat)
- [Instalasi](#-instalasi)
- [Konfigurasi](#-konfigurasi)
- [Menjalankan Aplikasi](#-menjalankan-aplikasi)
- [Struktur URL](#-struktur-url)
- [API Endpoints](#-api-endpoints)
- [Integrasi ESP32](#-integrasi-esp32)
- [Skema Database](#-skema-database)
- [Keamanan & Enkripsi](#-keamanan--enkripsi)
- [Testing](#-testing)
- [Struktur Project](#-struktur-project)
- [Troubleshooting](#-troubleshooting)
- [Tim Pengembang](#-tim-pengembang)

---

## 🎯 Gambaran Umum

**Smart Souvenir** adalah sistem terpadu yang mengintegrasikan 3 komponen utama dalam satu aplikasi Flask:

| Komponen | Fungsi | Teknologi Kunci |
|----------|--------|-----------------|
| **Kasir (POS)** | Point-of-Sale dengan pembayaran Face Recognition | DeepFace, TensorFlow, AES-256-CBC, RSA |
| **Stok (Inventory)** | Manajemen inventori dengan prediksi kategori otomatis | scikit-learn (LinearSVC), pyaes AES-256-CBC |
| **Gate (Detection)** | Deteksi pengunjung real-time dan validasi RFID di gate | YOLOv8, AES-128-GCM, Socket.IO |

Ketiga komponen terhubung ke satu database MySQL (`smart_souvenir_complete`) dan berjalan dalam satu server Flask di port **5000**.

---

## ✨ Fitur

### 🛒 Kasir (POS)
- **RFID Scanner** — Scan barcode produk langsung ke keranjang
- **Face Recognition** — Login member dan pembayaran via verifikasi wajah (DeepFace Facenet512)
- **Member System** — Registrasi, top-up saldo, sistem poin (earn/redeem)
- **Multi-Payment** — QR (QRIS), Face Pay (potong saldo otomatis), dan tunai
- **Enkripsi** — Data member di-hash (SHA-256), embedding wajah dienkripsi (AES-256-CBC), transaksi ditandatangani (RSA-SHA256)
- **Digital Signature** — Setiap transaksi face-pay memiliki signature RSA untuk audit trail

### 📦 Stok (Inventory)
- **CRUD Produk** — Tambah, edit, hapus produk dengan kategori dan supplier
- **Restock RFID** — Tambah item dengan scan RFID atau auto-generate kode
- **Prediksi Kategori ML** — Model LinearSVC memprediksi kategori produk secara otomatis
- **Supplier Management** — Data supplier dienkripsi (alamat & email menggunakan AES-256-CBC)
- **Dashboard** — Statistik stok tersedia, menipis, dan habis secara real-time

### 🚪 Gate (Detection)
- **YOLOv8 Detection** — Deteksi pengunjung (Pria/Wanita) secara real-time
- **Multi-Camera** — USB Camera, IP Camera (RTSP), dan Browser Webcam
- **MJPEG Stream** — Live video feed dengan bounding box overlay
- **Secure API** — Endpoint terenkripsi AES-128-GCM untuk komunikasi ESP32
- **Replay Protection** — Counter monotonik mencegah serangan replay
- **Visitor Logging** — Log pengunjung dengan statistik per jam

---

## 🏗️ Arsitektur Sistem

```
┌─────────────────────────────────────────────────────────────┐
│                    Flask Application (app.py)                │
│                    Port 5000 — 0.0.0.0                      │
├──────────────────┬──────────────────┬───────────────────────┤
│   Kasir Blueprint│  Stock Blueprint │   Gate Blueprint      │
│   /kasir/*       │  /stock/*        │   /gate/*             │
├──────────────────┼──────────────────┼───────────────────────┤
│ Face Service     │ ML Model         │ YOLOv8 Detector       │
│ (DeepFace)       │ (scikit-learn)   │ (ultralytics)         │
├──────────────────┴──────────────────┴───────────────────────┤
│                    Database Layer (db.py)                    │
│              MySQL — smart_souvenir_complete                 │
│              SQLite — gate.db (visitor logs)                 │
├─────────────────────────────────────────────────────────────┤
│                    ESP32 Devices                            │
│  Scan_Kasir.ino │ Scan_Stok.ino │ Scan_Gate.ino            │
└─────────────────────────────────────────────────────────────┘
```

### Alur Kerja

```
1. STOK: Admin tambah produk → restock dengan RFID → produk siap dijual
                ↓
2. KASIR: Pelanggan scan RFID → produk masuk keranjang → pilih metode bayar
                ↓
3. GATE: Pelanggan keluar → IR sensor + YOLO deteksi → RFID divalidasi → gate terbuka
```

---

## 🛠️ Teknologi

### Backend
| Teknologi | Versi | Fungsi |
|-----------|-------|--------|
| Python | 3.11.x | Runtime |
| Flask | 3.1.3 | Web framework |
| Flask-SocketIO | 5.6.1 | Real-time WebSocket |
| Flask-SQLAlchemy | 3.1.1 | ORM untuk Gate (SQLite) |
| PyMySQL | 1.1.2 | MySQL driver |

### AI / Machine Learning
| Teknologi | Versi | Fungsi |
|-----------|-------|--------|
| TensorFlow | 2.17.1 | Backend DeepFace |
| DeepFace | 0.0.95 | Face recognition (Facenet512) |
| Ultralytics (YOLOv8) | 8.4.71 | Person detection (Pria/Wanita) |
| PyTorch | 2.5.1+cpu | Backend YOLO |
| scikit-learn | 1.4.2 | Prediksi kategori produk |
| OpenCV | 4.11.0 | Image processing |

### Keamanan & Enkripsi
| Teknologi | Fungsi |
|-----------|--------|
| PyCryptodome | AES-256-CBC (embedding wajah), RSA-SHA256 (signature transaksi) |
| pyaes | AES-256-CBC (data supplier) |
| cryptography | AES-128-GCM (payload ESP32) |
| hashlib | SHA-256 (hash data member) |

### Frontend
| Teknologi | Fungsi |
|-----------|--------|
| HTML5 / CSS3 / JavaScript | UI |
| Bootstrap 5.3 | CSS framework (Stock) |
| Glassmorphism CSS | Custom design (Kasir) |
| Chart.js | Grafik statistik (Gate) |
| Lucide Icons | Ikon (Kasir) |
| Font Awesome | Ikon (Gate) |
| Socket.IO | Real-time updates (Gate) |

### Hardware (ESP32)
| Komponen | Fungsi |
|----------|--------|
| ESP32 + MFRC522 | RFID scanner |
| ESP32 + Servo | Gate otomatis |
| ESP32 + IR Sensor | Deteksi gerak |
| ESP32 + Buzzer | Notifikasi suara |
| ESP32 + LCD I2C | Display status |

---

## 📋 Prasyarat

- **Python 3.11.x** (WAJIB — DeepFace/TensorFlow tidak kompatibel dengan Python 3.14)
- **MySQL / MariaDB** (XAMPP atau standalone)
- **Git** (untuk clone repository)
- **Webcam** (opsional, untuk face recognition dan gate detection)

### Cek Python Version
```bash
python --version
# Harus: Python 3.11.x

# Jika punya banyak versi Python:
py -3.11 --version
```

---

## 🚀 Instalasi

### 1. Clone Repository
```bash
git clone https://github.com/<username>/smart-souvenir.git
cd smart-souvenir
```

### 2. Buat Virtual Environment (Python 3.11)
```bash
py -3.11 -m venv .venv

# Aktifkan venv:
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

> ⚠️ **PyTorch** harus diinstall secara terpisah untuk versi CPU:
> ```bash
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
> ```

### 4. Setup Database
Pastikan MySQL/MariaDB berjalan, lalu buat database:
```sql
CREATE DATABASE smart_souvenir_complete CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
```

Database schema akan dibuat otomatis saat pertama kali menjalankan aplikasi.

### 5. Konfigurasi Environment
Salin dan edit file `.env`:
```bash
cp .env.example .env
```

Edit nilai-nilai di `.env` sesuai kebutuhan (lihat [Konfigurasi](#-konfigurasi)).

---

## ⚙️ Konfigurasi

File `.env` berisi semua konfigurasi aplikasi:

```env
# Database
DB_HOST=127.0.0.1
DB_USER=root
DB_PASS=
DB_NAME=smart_souvenir_complete

# Flask Session
SECRET_KEY=smart-souvenir-unified-key-2026

# Kasir — Hash Key (WAJIB sama dengan data lama!)
KASIR_SECRET_KEY=kasir-face-recognition-dev-key-2026

# Kasir — Face Embedding Encryption
EMBEDDING_ENCRYPTION_KEY=trinity-kasir-face-crypt-key-32

# Stock — Supplier Data Encryption
STOCK_ENCRYPTION_KEY=smart-souvenir-stock-app-key-32

# Gate — ESP32 AES-128-GCM
GATE_DEVICE_ID=gate-esp32-01
GATE_REQUEST_KEY_HEX=7618561da88c350b55ff32bae357efaa
GATE_RESPONSE_KEY_HEX=8005e397a404c83377939a188a403c11
```

### ⚠️ Penting untuk Enkripsi

| Key | Digunakan Oleh | Keterangan |
|-----|---------------|------------|
| `KASIR_SECRET_KEY` | Hash NIK, HP, alamat member | **HARUS** sama dengan data yang sudah ada di database! |
| `EMBEDDING_ENCRYPTION_KEY` | Enkripsi face embedding (AES-256-CBC) | 32 karakter |
| `STOCK_ENCRYPTION_KEY` | Enkripsi data supplier (AES-256-CBC via pyaes) | Key diturunkan via SHA-256 |
| `GATE_REQUEST_KEY_HEX` | Dekripsi request dari ESP32 (AES-128-GCM) | 16 byte hex (32 karakter) |
| `GATE_RESPONSE_KEY_HEX` | Enkripsi response ke ESP32 (AES-128-GCM) | 16 byte hex (32 karakter) |

---

## ▶️ Menjalankan Aplikasi

```bash
# Pastikan MySQL berjalan dan venv aktif
cd smart-souvenir-app
python app.py
```

Server akan berjalan di:
```
http://localhost:5000
```

### URL Akses

| Halaman | URL | Deskripsi |
|---------|-----|-----------|
| **Kasir (POS)** | `http://localhost:5000/kasir/` | Point-of-Sale |
| **Stok (Inventory)** | `http://localhost:5000/stock/` | Manajemen stok (perlu login) |
| **Gate (Detection)** | `http://localhost:5000/gate/` | Dashboard deteksi |
| **Health Check** | `http://localhost:5000/health` | Status server |

### Login Stok
| Field | Value |
|-------|-------|
| Email | `admin@souvenir.com` |
| Password | `admin123` |

---

## 🔗 Struktur URL

### Kasir — `/kasir/`
```
GET  /kasir/                           → Halaman POS utama
GET  /kasir/api/cart                   → Isi keranjang
GET  /kasir/api/scan_rfid?uid=...     → Scan RFID ke keranjang
POST /kasir/api/scan_rfid/simulate    → Simulasi scan
POST /kasir/api/cart/delete            → Hapus item keranjang
GET  /kasir/api/member/lookup?phone=.. → Cari member
POST /kasir/api/member/register        → Daftar member baru
POST /kasir/api/member/enroll-face     → Daftarkan wajah member
POST /kasir/api/member/topup           → Top up saldo member
POST /kasir/api/face/detect            → Deteksi wajah (bounding box)
POST /kasir/api/face/verify            → Verifikasi wajah (recognize)
POST /kasir/api/payment/process        → Proses pembayaran QR
POST /kasir/api/payment/face-pay       → Proses pembayaran Face Pay
POST /kasir/api/secure/rfid-check      → Validasi RFID terenkripsi (ESP32)
```

### Stok — `/stock/`
```
GET  /stock/                           → Dashboard inventori
GET  /stock/login                      → Halaman login admin
POST /stock/product_create             → Tambah produk
GET  /stock/product_edit?id=...        → Edit produk
POST /stock/product_delete             → Hapus produk
POST /stock/product_delete_bulk        → Hapus massal
POST /stock/restock                    → Restock item
POST /stock/supplier_create            → Tambah supplier
GET  /stock/product_detail?id=...      → Detail produk (JSON)
POST /stock/api/predict_category       → Prediksi kategori ML
GET  /stock/api/insert_rfid?uid=...    → Insert RFID ke inbox
GET  /stock/api/rfid_push              → Ambil RFID dari inbox
GET  /stock/api/rfid_clear             → Kosongkan RFID inbox
GET  /stock/api/suppliers_decrypted    → Supplier + dekripsi data
```

### Gate — `/gate/`
```
GET  /gate/                            → Dashboard deteksi
GET  /gate/logs                        → Log pengunjung
GET  /gate/settings                    → Pengaturan
GET  /gate/api/gate/status             → Status gate
POST /gate/api/gate/toggle             → Buka/tutup gate
POST /gate/api/camera/start            → Mulai kamera
POST /gate/api/camera/stop             → Hentikan kamera
GET  /gate/api/camera/status           → Status kamera
POST /gate/api/detection/run           → Jalankan deteksi manual
GET  /gate/api/detection/check         → Cek deteksi (cache/realtime)
POST /gate/api/secure/detection-check  → Deteksi terenkripsi (ESP32)
GET  /gate/api/logs                    → Log pengunjung (JSON)
GET  /gate/api/stats                   → Statistik pengunjung
GET  /gate/video/feed                  → MJPEG live stream
GET  /gate/video/detection             → MJPEG dengan bounding box
```

---

## 📡 Integrasi ESP32

### Scan_Kasir.ino — RFID Scanner Kasir
```cpp
const char* serverName = "http://<IP_SERVER>:5000/kasir/api/scan_rfid.php";
```
Mengirim UID RFID via HTTP GET → produk ditambahkan ke keranjang.

### Scan_Stok.ino — RFID Scanner Restock
```cpp
String serverName = "http://<IP_SERVER>:5000/stock/api/insert_rfid.php";
```
Mengirim UID RFID ke inbox → admin memilih produk untuk restock.

### Scan_Gate.ino — Gate RFID + ML Detection
```cpp
constexpr char RFID_API_URL[] = "http://<IP_SERVER>:5000/kasir/api/secure/rfid-check";
constexpr char ML_API_URL[]   = "http://<IP_SERVER>:5000/gate/api/secure/detection-check";
```
Menggunakan **AES-128-GCM** untuk enkripsi payload. Key harus sama dengan `.env`.

### Konfigurasi ESP32
```cpp
// WiFi
constexpr char WIFI_SSID[] = "nama-wifi";
constexpr char WIFI_PASSWORD[] = "password-wifi";

// AES Keys (harus sama dengan .env server)
constexpr uint8_t REQUEST_KEY[16] = {
    0x76, 0x18, 0x56, 0x1D,
    0xA8, 0x8C, 0x35, 0x0B,
    0x55, 0xFF, 0x32, 0xBA,
    0xE3, 0x57, 0xEF, 0xAA
};
```

---

## 🗄️ Skema Database

Database: `smart_souvenir_complete` (MySQL/MariaDB)

```sql
-- Produk & Stok
products     (id, name, category_id, price, min_stock, supplier_id)
categories   (id, name)
items        (id, product_id, rfid_tag, condition, status, purchase_date)
suppliers    (id_supplier, nama, alamat[encrypted], hp, email[encrypted])
rfid_inbox   (id, tag, consumed)

-- Kasir & Transaksi
keranjang           (id, item_id, product_id, rfid_tag, nama_produk, harga, qty)
transaksi           (id_transaksi, product_id, qty, nik, grand_total, tanggal, jam)
transaksi_detail    (id, id_transaksi, product_id, nik, diskon, status_transaksi, sub_total)
buyed               (id, id_transaksi, product_id, rfid_tag, verified_at_gate)
transaksi_signature (id, id_transaksi, member_nik, signature)

-- Member & Face Recognition
member              (nik[hashed], nama, jk, alamat[hashed], hp[hashed], total_poin, saldo)
member_embeddings   (id, member_nik[hashed], embedding[encrypted], created_at)

-- Autentikasi
user_account        (id_user, email, pass, nama, level)

-- Gate (SQLite: gate.db)
visitor_logs  (id, detected_at, visitor_count, confidence_avg, gate_status, detection_data)
gate_stats    (id, date, total_visitors, total_detections, avg_confidence, peak_hour)
```

---

## 🔐 Keamanan & Enkripsi

### 1. Member Data Hashing (SHA-256)
```
Hash = SHA256(value + "|" + KASIR_SECRET_KEY)
```
Data sensitif (NIK, HP, alamat) disimpan sebagai hash 64 karakter.

### 2. Face Embedding Encryption (AES-256-CBC)
```
Key    = EMBEDDING_ENCRYPTION_KEY[:32] (padded)
IV     = random 16 bytes
Output = base64(IV + ciphertext)
```
Embedding wajah (512 dimensi) dienkripsi sebelum disimpan ke database.

### 3. Supplier Data Encryption (AES-256-CBC via pyaes)
```
Key    = SHA256(STOCK_ENCRYPTION_KEY)
IV     = random 16 bytes
Output = base64(IV + ciphertext)
```
Alamat dan email supplier dienkripsi, HP disimpan plaintext.

### 4. ESP32 Payload Encryption (AES-128-GCM)
```
Nonce = boot_id (4 byte) + counter (8 byte)
AAD   = device_id|boot_id|counter|endpoint_path
```
Komunikasi ESP32 menggunakan enkripsi terpisah untuk request dan response.

### 5. Transaction Signature (RSA-SHA256)
```
Payload = "TX:{id}|NIK:{nik}|EMB:{hash}|TOTAL:{total}|DATE:{date}|TIME:{time}"
Signature = RSA-SHA256(private_key, payload)
```
Setiap transaksi face-pay ditandatangani secara digital untuk audit trail.

---

## 🧪 Testing

### Jalankan Integration Test
```bash
python test_integration.py
```

Test mencakup **59 test case** meliputi:

| Modul | Test Coverage |
|-------|--------------|
| **Stock** (21 test) | Login, CRUD supplier, CRUD product, restock RFID, ML prediction, RFID inbox, enkripsi supplier |
| **Kasir** (18 test) | Scan RFID, cart CRUD, register member, hash verification, topup, payment process, points system |
| **Gate** (13 test) | Gate toggle, camera status, AES-128-GCM secure detection, AES-128-GCM secure RFID check, visitor logs, dashboard pages |
| **Cross** (3 test) | Health check, kasir page, stock login |
| **Cleanup** (4 test) | Hapus semua data dummy setelah test |

### Contoh Output
```
============================================================
TEST RESULTS
============================================================
  PASSED : 59
  FAILED : 0
  TOTAL  : 59

  ALL TESTS PASSED!
============================================================
```

---

## 📁 Struktur Project

```
smart-souvenir-app/
├── app.py                          # Entry point — Flask app factory
├── config.py                       # Konfigurasi terpusat (keys, DB, dll)
├── db.py                           # Database layer + schema initialization
├── requirements.txt                # Dependencies Python 3.11
├── .env                            # Environment variables (JANGAN di-commit!)
├── test_integration.py             # Integration test (59 test cases)
│
├── kasir/                          # Blueprint: Point-of-Sale
│   ├── __init__.py                 # Routes & business logic (650+ baris)
│   └── face_service.py             # DeepFace wrapper (detection, embedding, matching)
│
├── stock/                          # Blueprint: Inventory Management
│   └── __init__.py                 # Routes, CRUD, ML prediction, enkripsi
│
├── gate/                           # Blueprint: Gate Detection System
│   ├── __init__.py                 # Routes & state machine (1500+ baris)
│   ├── config.py                   # Gate configuration
│   ├── database.py                 # SQLAlchemy models (visitor_logs, gate_stats)
│   ├── camera_handler.py           # USB/IP/Browser camera handler
│   ├── payload_crypto.py           # AES-128-GCM encrypt/decrypt
│   └── models/
│       ├── placeholder_detector.py # YOLOv8 detector wrapper
│       └── best1.pt               # Model YOLOv8 (Pria/Wanita)
│
├── ml/                             # Machine Learning (Stock)
│   ├── PBL.joblib                  # Model prediksi kategori (LinearSVC)
│   ├── train_model.py              # Script training model
│   └── expand_dataset.py           # Generator dataset sintetis
│
├── templates/
│   ├── kasir/                      # Template POS
│   │   ├── base.html
│   │   └── kasir.html              # UI utama kasir
│   └── stock/                      # Template Inventory
│       ├── layout.html
│       ├── index.html              # Dashboard stok
│       ├── login.html
│       └── product_edit.html
│
└── static/
    ├── kasir/
    │   ├── css/styles.css          # Glassmorphism design
    │   └── js/
    │       ├── app.js              # Cart management
    │       ├── member.js           # Member registration & face enroll
    │       ├── face_camera.js      # Face detection camera
    │       └── payment.js          # Payment flow
    └── stock/
        ├── css/styles.css          # Dark theme glassmorphism
        └── js/app.js               # Dashboard interactivity
```

---

## 🔧 Troubleshooting

### Python Version Error
```
ERROR: No matching distribution found for deepface
```
**Solusi:** Gunakan Python 3.11.x, bukan 3.14.
```bash
py -3.11 -m venv .venv
```

### PyTorch DLL Error
```
OSError: [WinError 1114] DLL initialization routine failed
```
**Solusi:** Install PyTorch CPU-only:
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

### MySQL Connection Refused
```
pymysql.err.OperationalError: (2003, "Can't connect to MySQL server")
```
**Solusi:** Pastikan MySQL/MariaDB berjalan di port 3306.

### scikit-learn Version Warning
```
InconsistentVersionWarning: Trying to unpickle estimator from version 1.3.2
```
**Solusi:** Warning ini aman diabaikan. Model tetap berfungsi normal.

### Gate Dashboard Blank Page
**Solusi:** Pastikan CDN (Socket.IO, Chart.js) bisa diakses. Jika tidak ada internet, fitur real-time dan grafik akan dinonaktifkan otomatis.

---

## 👥 Tim Pengembang

| NIM | Nama | Kontribusi |
|-----|------|------------|
| — | Tim Smart Souvenir | Pengembangan sistem terpadu |

### Project Asal
Sistem ini merupakan integrasi dari 3 project terpisah yang dikembangkan dalam mata kuliah:
- **Praktikum Pengembangan Perangkat Lunak (PPL)** — Kasir POS
- **Praktikum Sistem Terdistribusi** — Gate Detection + ESP32
- **Praktikum Komputasi Bergerak** — Mobile Smart Souvenir
- **Integrasi** — Penggabungan menjadi satu sistem terpadu

---

## 📄 License

This project is developed for educational purposes at **Politeknik Elektronika Negeri Surabaya (PENS)**.

---

<div align="center">
  <strong>🏪 Smart Souvenir — Integrated POS, Inventory & Gate System</strong>
  <br>
  <sub>Built with ❤️ using Flask, DeepFace, YOLOv8, and ESP32</sub>
</div>
