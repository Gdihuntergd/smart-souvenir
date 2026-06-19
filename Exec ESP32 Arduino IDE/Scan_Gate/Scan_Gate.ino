/*
 * SMART SOUVENIR - ESP32 GATE OOP
 * ==============================================================
 * Arsitektur class:
 *   - DisplayService   : LCD I2C
 *   - WiFiService      : koneksi dan reconnect Wi-Fi
 *   - ApiClient        : API deep learning dan validasi RFID
 *   - IRSensor         : pembacaan sensor IR
 *   - RFIDService      : pembacaan UID MFRC522
 *   - BuzzerService    : alarm non-blocking
 *   - GateActuator     : servo gate non-blocking
 *   - SmartGateController : state machine dan aturan bisnis
 *
 * Alur gate masuk:
 *   IR masuk aktif + deep learning mendeteksi orang -> gate dibuka.
 *   RFID tidak digunakan pada gate masuk.
 *
 * Alur gate keluar:
 *   IR keluar aktif + deep learning mendeteksi orang -> cek RFID opsional.
 *   - RFID tidak terbaca dalam jendela scan -> dianggap tanpa barang,
 *     gate dibuka.
 *   - RFID terbaca -> wajib lolos validasi pembayaran sebelum gate dibuka.
 *
 * Keamanan payload:
 *   - HTTP tetap digunakan sebagai transport.
 *   - Body request dan response dienkripsi AES-128-GCM.
 *   - Nonce = boot ID 4 byte + counter 8 byte.
 *   - AAD mengikat device, boot, counter, dan endpoint.
 *   - Waktu komputasi ditampilkan dalam mikrodetik pada Serial Monitor.
 *
 * Library:
 *   ESP32Servo
 *   LiquidCrystal_I2C
 *   MFRC522
 *   ArduinoJson 6.x
 *   Mbed TLS bawaan ESP32 Arduino Core
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#include <SPI.h>
#include <MFRC522.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <mbedtls/base64.h>
#include <mbedtls/gcm.h>
#include <vector>
#include <cstring>
#include <cstdlib>

// =============================================================
// KONFIGURASI
// =============================================================
namespace AppConfig {

// Wi-Fi
constexpr char WIFI_SSID[] = "wudeheli";
constexpr char WIFI_PASSWORD[] = "kalau0000";

// Secure API - payload terenkripsi, transport tetap HTTP.
constexpr char RFID_API_URL[] = "http://192.168.100.74:5000/kasir/api/secure/rfid-check";

constexpr char ML_API_URL[] = "http://192.168.100.74:5000/gate/api/secure/detection-check";

constexpr char DEVICE_ID[] = "gate-esp32-01";

// AES-128 key = 16 byte. Nilai harus sama dengan file .env Flask.
// Ganti key ini sebelum deployment nyata.
constexpr uint8_t REQUEST_KEY[16] = {
    0x76, 0x18, 0x56, 0x1D,
    0xA8, 0x8C, 0x35, 0x0B,
    0x55, 0xFF, 0x32, 0xBA,
    0xE3, 0x57, 0xEF, 0xAA
};

constexpr uint8_t RESPONSE_KEY[16] = {
    0x80, 0x05, 0xE3, 0x97,
    0xA4, 0x04, 0xC8, 0x33,
    0x77, 0x93, 0x9A, 0x18,
    0x8A, 0x40, 0x3C, 0x11
};

// Pin
constexpr uint8_t SERVO_MASUK_PIN = 13;
constexpr uint8_t IR_MASUK_PIN = 22;

constexpr uint8_t RFID_SS_PIN = 5;
constexpr uint8_t RFID_RST_PIN = 4;

constexpr uint8_t SERVO_KELUAR_PIN = 26;
constexpr uint8_t BUZZER_PIN = 27;
constexpr uint8_t IR_KELUAR_PIN = 34;

constexpr uint8_t I2C_SDA_PIN = 32;
constexpr uint8_t I2C_SCL_PIN = 33;

// LCD
constexpr uint8_t LCD_ADDRESS = 0x27;
constexpr uint8_t LCD_COLUMNS = 16;
constexpr uint8_t LCD_ROWS = 2;

// IR
constexpr int IR_ACTIVE_LEVEL = LOW;

// Servo
constexpr int SERVO_CLOSED_ANGLE = 0;
constexpr int SERVO_OPEN_ANGLE = 90;
constexpr uint16_t SERVO_MIN_PULSE_US = 500;
constexpr uint16_t SERVO_MAX_PULSE_US = 2400;
constexpr unsigned long SERVO_STEP_INTERVAL_MS = 10;

// Gate
constexpr unsigned long MIN_GATE_OPEN_MS = 1000;
constexpr unsigned long IR_CLEAR_HOLD_MS = 1500;
constexpr unsigned long EXIT_IR_RELEASE_TIMEOUT_MS = 1500;

// RFID
constexpr unsigned long RFID_WAIT_TIMEOUT_MS = 10000;
constexpr unsigned long RFID_DEBOUNCE_MS = 800;

// Gate keluar memberi waktu singkat untuk membaca RFID.
// Jika tidak ada RFID terbaca, pengguna dianggap tidak membawa barang.
constexpr unsigned long EXIT_RFID_SCAN_WINDOW_MS = 2500;
constexpr bool ALLOW_EXIT_WITHOUT_RFID = true;

// Pesan pasif (tanpa buzzer) untuk kegagalan validasi kamera.
constexpr unsigned long PASSIVE_MESSAGE_DISPLAY_MS = 1500;
constexpr unsigned long IR_LOST_GRACE_MS = 500;

// ML
constexpr unsigned long ML_RETRY_INTERVAL_MS = 450;
constexpr unsigned long ML_VALIDATION_TIMEOUT_MS = 4500;
constexpr uint8_t ML_MAX_ATTEMPTS = 6;

// HTTP
constexpr unsigned long HTTP_CONNECT_TIMEOUT_MS = 3000;
constexpr unsigned long HTTP_RESPONSE_TIMEOUT_MS = 5000;

// Alarm dan reconnect
constexpr unsigned long ACCESS_DENIED_DISPLAY_MS = 3500;
constexpr unsigned long BUZZER_DURATION_MS = 3000;
constexpr unsigned long WIFI_RECONNECT_INTERVAL_MS = 10000;

// false = jumlah orang > 0 diterima.
// true  = wajib tepat satu orang.
constexpr bool REQUIRE_SINGLE_PERSON = false;

}  // namespace AppConfig

// =============================================================
// DATA TRANSFER OBJECT
// =============================================================
struct MLResult {
  bool requestOk = false;
  bool personDetected = false;
  int personCount = 0;
  int httpCode = 0;
  String error;
};

struct RFIDValidationResult {
  bool requestOk = false;
  bool allowed = false;
  int httpCode = 0;
  String message;
};

// =============================================================
// DISPLAY SERVICE
// =============================================================
class DisplayService {
 public:
  DisplayService(uint8_t address, uint8_t columns, uint8_t rows)
      : lcd_(address, columns, rows), columns_(columns) {}

  void begin(uint8_t sdaPin, uint8_t sclPin) {
    Wire.begin(sdaPin, sclPin);
    lcd_.init();
    lcd_.backlight();
  }

  void show(const String& line1, const String& line2) {
    printLine(0, line1);
    printLine(1, line2);
  }

  void showIdle(bool wifiConnected) {
    show(
        "Smart Souvenir",
        wifiConnected ? "Gate siap" : "WiFi terputus"
    );
  }

 private:
  LiquidCrystal_I2C lcd_;
  uint8_t columns_;

  void printLine(uint8_t row, String text) {
    if (text.length() > columns_) {
      text = text.substring(0, columns_);
    }

    while (text.length() < columns_) {
      text += ' ';
    }

    lcd_.setCursor(0, row);
    lcd_.print(text);
  }
};

// =============================================================
// WIFI SERVICE
// =============================================================
class WiFiService {
 public:
  WiFiService(
      const char* ssid,
      const char* password,
      unsigned long reconnectIntervalMs
  )
      : ssid_(ssid),
        password_(password),
        reconnectIntervalMs_(reconnectIntervalMs) {}

  void begin(DisplayService& display) {
    WiFi.mode(WIFI_STA);
    WiFi.persistent(false);
    WiFi.setAutoReconnect(true);
    WiFi.setSleep(false);

    display.show("Menghubungkan", "WiFi...");

    Serial.print(F("[WIFI] Menghubungkan ke "));
    Serial.println(ssid_);

    WiFi.begin(ssid_, password_);

    const unsigned long startedAt = millis();

    while (
        !connected() &&
        millis() - startedAt < 20000UL
    ) {
      delay(250);
      Serial.print('.');
    }

    Serial.println();

    if (connected()) {
      Serial.print(F("[WIFI] Terhubung. IP ESP32: "));
      Serial.println(WiFi.localIP());
    } else {
      Serial.println(F("[WIFI] Koneksi awal gagal."));
    }
  }

  void update() {
    if (connected()) {
      return;
    }

    if (
        millis() - lastReconnectAt_ <
        reconnectIntervalMs_
    ) {
      return;
    }

    lastReconnectAt_ = millis();

    Serial.println(F("[WIFI] Mencoba reconnect..."));

    WiFi.disconnect();
    WiFi.begin(ssid_, password_);
  }

  bool connected() const {
    return WiFi.status() == WL_CONNECTED;
  }

 private:
  const char* ssid_;
  const char* password_;
  unsigned long reconnectIntervalMs_;
  unsigned long lastReconnectAt_ = 0;
};

// =============================================================
// IR SENSOR
// =============================================================
class IRSensor {
 public:
  IRSensor(uint8_t pin, int activeLevel)
      : pin_(pin), activeLevel_(activeLevel) {}

  void begin() {
    pinMode(pin_, INPUT);
  }

  bool active() const {
    return digitalRead(pin_) == activeLevel_;
  }

 private:
  uint8_t pin_;
  int activeLevel_;
};

// =============================================================
// BUZZER SERVICE
// =============================================================
class BuzzerService {
 public:
  BuzzerService(uint8_t pin, unsigned long durationMs)
      : pin_(pin), durationMs_(durationMs) {}

  void begin() {
    pinMode(pin_, OUTPUT);
    digitalWrite(pin_, LOW);
  }

  void start() {
    active_ = true;
    startedAt_ = millis();
    digitalWrite(pin_, HIGH);
  }

  void stop() {
    active_ = false;
    digitalWrite(pin_, LOW);
  }

  void update() {
    if (
        active_ &&
        millis() - startedAt_ >= durationMs_
    ) {
      stop();
    }
  }

  bool active() const {
    return active_;
  }

 private:
  uint8_t pin_;
  unsigned long durationMs_;
  bool active_ = false;
  unsigned long startedAt_ = 0;
};

// =============================================================
// GATE ACTUATOR
// =============================================================
class GateActuator {
 public:
  GateActuator(
      uint8_t pin,
      int closedAngle,
      int openAngle,
      unsigned long stepIntervalMs
  )
      : pin_(pin),
        closedAngle_(closedAngle),
        openAngle_(openAngle),
        currentAngle_(closedAngle),
        targetAngle_(closedAngle),
        stepIntervalMs_(stepIntervalMs) {}

  void begin(
      uint16_t minPulseUs,
      uint16_t maxPulseUs
  ) {
    servo_.attach(pin_, minPulseUs, maxPulseUs);
    servo_.write(closedAngle_);
  }

  void open() {
    targetAngle_ = openAngle_;
  }

  void close() {
    targetAngle_ = closedAngle_;
  }

  void update() {
    if (currentAngle_ == targetAngle_) {
      return;
    }

    if (
        millis() - lastStepAt_ <
        stepIntervalMs_
    ) {
      return;
    }

    lastStepAt_ = millis();

    currentAngle_ +=
        currentAngle_ < targetAngle_ ? 1 : -1;

    servo_.write(currentAngle_);
  }

  bool isOpen() const {
    return currentAngle_ == openAngle_;
  }

  bool isClosed() const {
    return currentAngle_ == closedAngle_;
  }

  bool isOpening() const {
    return targetAngle_ == openAngle_ && !isOpen();
  }

  bool isClosing() const {
    return targetAngle_ == closedAngle_ && !isClosed();
  }

 private:
  Servo servo_;
  uint8_t pin_;

  int closedAngle_;
  int openAngle_;
  int currentAngle_;
  int targetAngle_;

  unsigned long stepIntervalMs_;
  unsigned long lastStepAt_ = 0;
};

// =============================================================
// RFID SERVICE
// =============================================================
class RFIDService {
 public:
  RFIDService(
      uint8_t ssPin,
      uint8_t rstPin,
      unsigned long debounceMs
  )
      : reader_(ssPin, rstPin),
        debounceMs_(debounceMs) {}

  void begin() {
    SPI.begin();
    reader_.PCD_Init();
  }

  bool readUid(String& uidResult) {
    if (
        millis() - lastReadAt_ <
        debounceMs_
    ) {
      return false;
    }

    if (!reader_.PICC_IsNewCardPresent()) {
      return false;
    }

    if (!reader_.PICC_ReadCardSerial()) {
      return false;
    }

    lastReadAt_ = millis();
    uidResult = uidToHex(reader_.uid);

    Serial.print(F("[RFID] UID terbaca: "));
    Serial.println(uidResult);

    reader_.PICC_HaltA();
    reader_.PCD_StopCrypto1();

    return true;
  }

 private:
  MFRC522 reader_;
  unsigned long debounceMs_;
  unsigned long lastReadAt_ = 0;

  String uidToHex(const MFRC522::Uid& uid) const {
    String result;
    result.reserve(uid.size * 2);

    for (byte i = 0; i < uid.size; i++) {
      if (uid.uidByte[i] < 0x10) {
        result += '0';
      }

      result += String(uid.uidByte[i], HEX);
    }

    result.toUpperCase();
    return result;
  }
};

// =============================================================
// SECURE PAYLOAD DATA
// =============================================================
struct SecureEnvelope {
  String bootId;
  uint64_t counter = 0;
  String nonceBase64;
  String ciphertextBase64;
  String tagBase64;
};

struct CryptoTiming {
  uint64_t jsonSerializeUs = 0;
  uint64_t aesEncryptUs = 0;
  uint64_t base64EncodeUs = 0;
  uint64_t httpRoundTripUs = 0;
  uint64_t envelopeParseUs = 0;
  uint64_t base64DecodeUs = 0;
  uint64_t aesDecryptUs = 0;
  uint64_t jsonParseUs = 0;
  uint64_t totalUs = 0;

  uint64_t serverDecryptUs = 0;
  uint64_t serverProcessUs = 0;
  uint64_t serverEncryptUs = 0;
};

// =============================================================
// PAYLOAD CRYPTO - AES-128-GCM
// =============================================================
class PayloadCrypto {
 public:
  PayloadCrypto(
      const uint8_t* requestKey,
      const uint8_t* responseKey,
      const char* deviceId
  )
      : requestKey_(requestKey),
        responseKey_(responseKey),
        deviceId_(deviceId) {}

  void begin() {
    bootId_ = esp_random();

    // Hindari boot ID nol agar log dan diagnosis lebih jelas.
    if (bootId_ == 0) {
      bootId_ = 1;
    }

    counter_ = 0;

    Serial.print(F("[CRYPTO] Device ID: "));
    Serial.println(deviceId_);
    Serial.print(F("[CRYPTO] Boot ID  : "));
    Serial.println(bootIdHex());
    Serial.println(F("[CRYPTO] AES-128-GCM siap."));
  }

  const char* deviceId() const {
    return deviceId_;
  }

  String bootIdHex() const {
    char buffer[9];
    snprintf(buffer, sizeof(buffer), "%08lX", static_cast<unsigned long>(bootId_));
    return String(buffer);
  }

  uint64_t nextCounter() {
    counter_++;

    if (counter_ == 0) {
      // Overflow praktis tidak akan tercapai, tetapi jangan pernah memakai 0.
      counter_ = 1;
    }

    return counter_;
  }

  bool encryptRequest(
      const String& plaintext,
      const String& aad,
      uint64_t counter,
      SecureEnvelope& output,
      CryptoTiming& timing,
      String& error
  ) const {
    uint8_t nonce[12];
    buildNonce(counter, nonce);

    const size_t plaintextLength = plaintext.length();
    std::vector<uint8_t> ciphertext(plaintextLength);
    uint8_t tag[16] = {0};

    mbedtls_gcm_context context;
    mbedtls_gcm_init(&context);

    int result = mbedtls_gcm_setkey(
        &context,
        MBEDTLS_CIPHER_ID_AES,
        requestKey_,
        128
    );

    if (result != 0) {
      mbedtls_gcm_free(&context);
      error = "mbedtls_gcm_setkey encrypt gagal: " + String(result);
      return false;
    }

    const uint64_t startedAt = esp_timer_get_time();

    result = mbedtls_gcm_crypt_and_tag(
        &context,
        MBEDTLS_GCM_ENCRYPT,
        plaintextLength,
        nonce,
        sizeof(nonce),
        reinterpret_cast<const uint8_t*>(aad.c_str()),
        aad.length(),
        reinterpret_cast<const uint8_t*>(plaintext.c_str()),
        ciphertext.data(),
        sizeof(tag),
        tag
    );

    timing.aesEncryptUs = esp_timer_get_time() - startedAt;
    mbedtls_gcm_free(&context);

    if (result != 0) {
      error = "AES-GCM encrypt gagal: " + String(result);
      return false;
    }

    const uint64_t base64StartedAt = esp_timer_get_time();

    if (
        !base64Encode(nonce, sizeof(nonce), output.nonceBase64) ||
        !base64Encode(
            ciphertext.data(),
            ciphertext.size(),
            output.ciphertextBase64
        ) ||
        !base64Encode(tag, sizeof(tag), output.tagBase64)
    ) {
      error = "Base64 encode gagal";
      return false;
    }

    timing.base64EncodeUs =
        esp_timer_get_time() - base64StartedAt;

    output.bootId = bootIdHex();
    output.counter = counter;
    return true;
  }

  bool decryptResponse(
      const SecureEnvelope& input,
      const String& aad,
      String& plaintext,
      CryptoTiming& timing,
      String& error
  ) const {
    std::vector<uint8_t> nonce;
    std::vector<uint8_t> ciphertext;
    std::vector<uint8_t> tag;

    const uint64_t base64StartedAt = esp_timer_get_time();

    if (
        !base64Decode(input.nonceBase64, nonce) ||
        !base64Decode(input.ciphertextBase64, ciphertext) ||
        !base64Decode(input.tagBase64, tag)
    ) {
      error = "Base64 decode response gagal";
      return false;
    }

    timing.base64DecodeUs =
        esp_timer_get_time() - base64StartedAt;

    if (nonce.size() != 12) {
      error = "Nonce response bukan 12 byte";
      return false;
    }

    if (tag.size() != 16) {
      error = "Tag response bukan 16 byte";
      return false;
    }

    uint8_t expectedNonce[12];
    buildNonce(input.counter, expectedNonce);

    if (memcmp(nonce.data(), expectedNonce, sizeof(expectedNonce)) != 0) {
      error = "Nonce response tidak cocok";
      return false;
    }

    std::vector<uint8_t> decrypted(ciphertext.size() + 1, 0);

    mbedtls_gcm_context context;
    mbedtls_gcm_init(&context);

    int result = mbedtls_gcm_setkey(
        &context,
        MBEDTLS_CIPHER_ID_AES,
        responseKey_,
        128
    );

    if (result != 0) {
      mbedtls_gcm_free(&context);
      error = "mbedtls_gcm_setkey decrypt gagal: " + String(result);
      return false;
    }

    const uint64_t startedAt = esp_timer_get_time();

    result = mbedtls_gcm_auth_decrypt(
        &context,
        ciphertext.size(),
        nonce.data(),
        nonce.size(),
        reinterpret_cast<const uint8_t*>(aad.c_str()),
        aad.length(),
        tag.data(),
        tag.size(),
        ciphertext.data(),
        decrypted.data()
    );

    timing.aesDecryptUs = esp_timer_get_time() - startedAt;
    mbedtls_gcm_free(&context);

    if (result != 0) {
      error = "AES-GCM decrypt/tag gagal: " + String(result);
      return false;
    }

    plaintext = String(
        reinterpret_cast<const char*>(decrypted.data())
    );

    return true;
  }

 private:
  const uint8_t* requestKey_;
  const uint8_t* responseKey_;
  const char* deviceId_;

  uint32_t bootId_ = 0;
  uint64_t counter_ = 0;

  void buildNonce(uint64_t counter, uint8_t nonce[12]) const {
    // Network byte order / big endian:
    // 4 byte boot ID + 8 byte message counter.
    nonce[0] = static_cast<uint8_t>((bootId_ >> 24) & 0xFF);
    nonce[1] = static_cast<uint8_t>((bootId_ >> 16) & 0xFF);
    nonce[2] = static_cast<uint8_t>((bootId_ >> 8) & 0xFF);
    nonce[3] = static_cast<uint8_t>(bootId_ & 0xFF);

    for (uint8_t index = 0; index < 8; index++) {
      nonce[4 + index] = static_cast<uint8_t>(
          (counter >> (56 - (index * 8))) & 0xFF
      );
    }
  }

  static bool base64Encode(
      const uint8_t* input,
      size_t inputLength,
      String& output
  ) {
    const size_t capacity = 4 * ((inputLength + 2) / 3) + 1;
    std::vector<uint8_t> buffer(capacity, 0);
    size_t outputLength = 0;

    const int result = mbedtls_base64_encode(
        buffer.data(),
        buffer.size(),
        &outputLength,
        input,
        inputLength
    );

    if (result != 0) {
      return false;
    }

    buffer[outputLength] = '\0';
    output = String(reinterpret_cast<const char*>(buffer.data()));
    return true;
  }

  static bool base64Decode(
      const String& input,
      std::vector<uint8_t>& output
  ) {
    if (input.length() == 0) {
      return false;
    }

    // Hasil decode Base64 selalu lebih kecil atau sama dari input.
    output.assign(input.length(), 0);
    size_t outputLength = 0;

    const int result = mbedtls_base64_decode(
        output.data(),
        output.size(),
        &outputLength,
        reinterpret_cast<const uint8_t*>(input.c_str()),
        input.length()
    );

    if (result != 0) {
      output.clear();
      return false;
    }

    output.resize(outputLength);
    return true;
  }
};

// =============================================================
// API CLIENT - SECURE HTTP PAYLOAD
// =============================================================
class ApiClient {
 public:
  ApiClient(
      const char* mlUrl,
      const char* rfidUrl,
      unsigned long connectTimeoutMs,
      unsigned long responseTimeoutMs,
      PayloadCrypto& crypto
  )
      : mlUrl_(mlUrl),
        rfidUrl_(rfidUrl),
        connectTimeoutMs_(connectTimeoutMs),
        responseTimeoutMs_(responseTimeoutMs),
        crypto_(crypto) {}

  MLResult detectPerson() {
    MLResult result;
    CryptoTiming timing;
    String responsePlaintext;

    StaticJsonDocument<192> requestDocument;
    requestDocument["event"] = "person_detection";
    requestDocument["ir_detected"] = true;

    if (!performSecurePost(
            mlUrl_,
            requestDocument,
            responsePlaintext,
            result.httpCode,
            result.error,
            timing
        )) {
      return result;
    }

    StaticJsonDocument<768> document;
    const uint64_t parseStartedAt = esp_timer_get_time();

    const DeserializationError jsonError =
        deserializeJson(document, responsePlaintext);

    timing.jsonParseUs = esp_timer_get_time() - parseStartedAt;
    timing.totalUs = esp_timer_get_time() - requestStartedAtUs_;

    if (jsonError) {
      result.error = "JSON ML hasil decrypt tidak valid";
      Serial.print(F("[ML] JSON error: "));
      Serial.println(jsonError.c_str());
      printTiming("PERSON DETECTION", timing);
      return result;
    }

    result.requestOk = document["ok"] | true;
    result.personDetected = document["person_detected"] | false;
    result.personCount = document["count"] | 0;

    if (result.personCount == 0) {
      result.personCount = document["person_count"] | 0;
    }

    const char* errorText = document["error"] | "";
    result.error = errorText;

    timing.serverDecryptUs = document["server_decrypt_us"] | 0ULL;
    timing.serverProcessUs = document["server_process_us"] | 0ULL;

    Serial.print(F("[ML SECURE] person_detected: "));
    Serial.println(result.personDetected ? F("true") : F("false"));
    Serial.print(F("[ML SECURE] count: "));
    Serial.println(result.personCount);

    printTiming("PERSON DETECTION", timing);
    return result;
  }

  RFIDValidationResult validateRFID(const String& uid) {
    RFIDValidationResult result;
    CryptoTiming timing;
    String responsePlaintext;
    String error;

    StaticJsonDocument<256> requestDocument;
    requestDocument["event"] = "rfid_validation";
    requestDocument["ir_detected"] = true;
    requestDocument["rfid"] = uid;

    if (!performSecurePost(
            rfidUrl_,
            requestDocument,
            responsePlaintext,
            result.httpCode,
            error,
            timing
        )) {
      result.message = error;
      return result;
    }

    StaticJsonDocument<768> document;
    const uint64_t parseStartedAt = esp_timer_get_time();

    const DeserializationError jsonError =
        deserializeJson(document, responsePlaintext);

    timing.jsonParseUs = esp_timer_get_time() - parseStartedAt;
    timing.totalUs = esp_timer_get_time() - requestStartedAtUs_;

    if (jsonError) {
      result.message = "JSON RFID hasil decrypt tidak valid";
      Serial.print(F("[RFID SECURE] JSON error: "));
      Serial.println(jsonError.c_str());
      printTiming("RFID VALIDATION", timing);
      return result;
    }

    result.requestOk = true;
    result.allowed = document["allowed"] | false;
    result.message = String(document["message"] | "");

    timing.serverDecryptUs = document["server_decrypt_us"] | 0ULL;
    timing.serverProcessUs = document["server_process_us"] | 0ULL;

    Serial.print(F("[RFID SECURE] allowed: "));
    Serial.println(result.allowed ? F("true") : F("false"));
    Serial.print(F("[RFID SECURE] message: "));
    Serial.println(result.message);

    printTiming("RFID VALIDATION", timing);
    return result;
  }

 private:
  const char* mlUrl_;
  const char* rfidUrl_;
  unsigned long connectTimeoutMs_;
  unsigned long responseTimeoutMs_;
  PayloadCrypto& crypto_;

  uint64_t requestStartedAtUs_ = 0;

  bool performSecurePost(
      const String& url,
      JsonDocument& plaintextDocument,
      String& responsePlaintext,
      int& httpCode,
      String& error,
      CryptoTiming& timing
  ) {
    requestStartedAtUs_ = esp_timer_get_time();

    if (WiFi.status() != WL_CONNECTED) {
      error = "WiFi tidak terhubung";
      Serial.println(F("[HTTP SECURE] WiFi tidak terhubung."));
      return false;
    }

    const String endpointPath = extractEndpointPath(url);
    const uint64_t counter = crypto_.nextCounter();
    const String counterText = uint64ToString(counter);

    const String aad =
        String(crypto_.deviceId()) + "|" +
        crypto_.bootIdHex() + "|" +
        counterText + "|" +
        endpointPath;

    String plaintext;
    const uint64_t jsonStartedAt = esp_timer_get_time();
    serializeJson(plaintextDocument, plaintext);
    timing.jsonSerializeUs = esp_timer_get_time() - jsonStartedAt;

    SecureEnvelope requestEnvelope;

    if (!crypto_.encryptRequest(
            plaintext,
            aad,
            counter,
            requestEnvelope,
            timing,
            error
        )) {
      Serial.print(F("[CRYPTO] "));
      Serial.println(error);
      return false;
    }

    StaticJsonDocument<1536> envelopeDocument;
    envelopeDocument["device_id"] = crypto_.deviceId();
    envelopeDocument["boot_id"] = requestEnvelope.bootId;
    envelopeDocument["counter"] = counterText;
    envelopeDocument["nonce"] = requestEnvelope.nonceBase64;
    envelopeDocument["ciphertext"] = requestEnvelope.ciphertextBase64;
    envelopeDocument["tag"] = requestEnvelope.tagBase64;

    String requestBody;
    serializeJson(envelopeDocument, requestBody);

    WiFiClient client;
    HTTPClient http;

    Serial.print(F("[HTTP SECURE] POST "));
    Serial.println(url);
    Serial.print(F("[HTTP SECURE] Plaintext bytes : "));
    Serial.println(plaintext.length());
    Serial.print(F("[HTTP SECURE] Ciphertext bytes: "));
    Serial.println(plaintext.length());
    Serial.print(F("[HTTP SECURE] Envelope bytes  : "));
    Serial.println(requestBody.length());

    if (!http.begin(client, url)) {
      error = "http.begin gagal";
      return false;
    }

    http.setConnectTimeout(connectTimeoutMs_);
    http.setTimeout(responseTimeoutMs_);
    http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Accept", "application/json");

    const uint64_t httpStartedAt = esp_timer_get_time();
    httpCode = http.POST(requestBody);
    timing.httpRoundTripUs = esp_timer_get_time() - httpStartedAt;

    const String responseBody = http.getString();
    http.end();

    Serial.print(F("[HTTP SECURE] Status: "));
    Serial.println(httpCode);

    if (httpCode != HTTP_CODE_OK) {
      error = "HTTP " + String(httpCode) + ": " + responseBody;
      Serial.println(error);
      return false;
    }

    StaticJsonDocument<2048> responseDocument;
    const uint64_t envelopeParseStartedAt = esp_timer_get_time();

    const DeserializationError envelopeError =
        deserializeJson(responseDocument, responseBody);

    timing.envelopeParseUs =
        esp_timer_get_time() - envelopeParseStartedAt;

    if (envelopeError) {
      error = "Envelope response JSON tidak valid";
      Serial.println(error);
      return false;
    }

    SecureEnvelope responseEnvelope;
    responseEnvelope.bootId = String(responseDocument["boot_id"] | "");
    responseEnvelope.counter = parseUint64(
        String(responseDocument["counter"] | "0")
    );
    responseEnvelope.nonceBase64 = String(responseDocument["nonce"] | "");
    responseEnvelope.ciphertextBase64 =
        String(responseDocument["ciphertext"] | "");
    responseEnvelope.tagBase64 = String(responseDocument["tag"] | "");

    timing.serverEncryptUs = responseDocument["server_encrypt_us"] | 0ULL;

    const String responseDeviceId =
        String(responseDocument["device_id"] | "");

    if (responseDeviceId != crypto_.deviceId()) {
      error = "Device ID response tidak cocok";
      return false;
    }

    if (responseEnvelope.bootId != crypto_.bootIdHex()) {
      error = "Boot ID response tidak cocok";
      return false;
    }

    if (responseEnvelope.counter != counter) {
      error = "Counter response tidak cocok";
      return false;
    }

    if (!crypto_.decryptResponse(
            responseEnvelope,
            aad,
            responsePlaintext,
            timing,
            error
        )) {
      Serial.print(F("[CRYPTO] "));
      Serial.println(error);
      return false;
    }

    return true;
  }

  static String extractEndpointPath(const String& url) {
    const int schemeIndex = url.indexOf("://");
    const int pathIndex = url.indexOf(
        '/',
        schemeIndex >= 0 ? schemeIndex + 3 : 0
    );

    if (pathIndex < 0) {
      return "/";
    }

    return url.substring(pathIndex);
  }

  static String uint64ToString(uint64_t value) {
    char buffer[24];
    snprintf(
        buffer,
        sizeof(buffer),
        "%llu",
        static_cast<unsigned long long>(value)
    );
    return String(buffer);
  }

  static uint64_t parseUint64(const String& value) {
    return strtoull(value.c_str(), nullptr, 10);
  }

  static float microsecondsToMilliseconds(uint64_t value) {
    return static_cast<float>(value) / 1000.0f;
  }

  static void printTimeLine(const char* label, uint64_t value) {
    Serial.printf(
        "%-22s: %llu us | %.3f ms\n",
        label,
        static_cast<unsigned long long>(value),
        microsecondsToMilliseconds(value)
    );
  }

  static void printTiming(
      const char* operation,
      const CryptoTiming& timing
  ) {
    const uint64_t aesTotal =
        timing.aesEncryptUs + timing.aesDecryptUs;

    const uint64_t localCryptoTotal =
        timing.aesEncryptUs +
        timing.base64EncodeUs +
        timing.base64DecodeUs +
        timing.aesDecryptUs;

    Serial.println();
    Serial.println(F("================================================"));
    Serial.print(F(" SECURE PAYLOAD TIMING - "));
    Serial.println(operation);
    Serial.println(F("================================================"));

    printTimeLine("JSON serialize", timing.jsonSerializeUs);
    printTimeLine("AES-GCM encrypt", timing.aesEncryptUs);
    printTimeLine("Base64 encode", timing.base64EncodeUs);
    printTimeLine("HTTP round-trip", timing.httpRoundTripUs);
    printTimeLine("Envelope parse", timing.envelopeParseUs);
    printTimeLine("Base64 decode", timing.base64DecodeUs);
    printTimeLine("AES-GCM decrypt", timing.aesDecryptUs);
    printTimeLine("JSON parse", timing.jsonParseUs);

    Serial.println(F("------------------------------------------------"));
    printTimeLine("AES total ESP32", aesTotal);
    printTimeLine("Crypto+Base64 ESP32", localCryptoTotal);
    printTimeLine("Total request ESP32", timing.totalUs);

    Serial.println(F("------------------------------------------------"));
    printTimeLine("Server decrypt", timing.serverDecryptUs);
    printTimeLine("Server process", timing.serverProcessUs);
    printTimeLine("Server encrypt", timing.serverEncryptUs);
    Serial.println(F("================================================"));
    Serial.println();
  }
};

// =============================================================
// SMART GATE CONTROLLER
// =============================================================
class SmartGateController {
 public:
  enum class State : uint8_t {
    IdleClosed,

    EntranceValidating,
    EntranceWaitClear,
    EntranceOpening,
    EntranceOpenWait,
    EntranceClosing,

    ExitValidatingPerson,
    ExitOptionalRFID,
    ExitWaitClear,
    ExitOpening,
    ExitOpenWait,
    ExitClosing,

    AccessDenied
  };

  SmartGateController(
      DisplayService& display,
      WiFiService& wifi,
      ApiClient& api,
      RFIDService& rfid,
      IRSensor& entranceIR,
      IRSensor& exitIR,
      GateActuator& entranceGate,
      GateActuator& exitGate,
      BuzzerService& buzzer
  )
      : display_(display),
        wifi_(wifi),
        api_(api),
        rfid_(rfid),
        entranceIR_(entranceIR),
        exitIR_(exitIR),
        entranceGate_(entranceGate),
        exitGate_(exitGate),
        buzzer_(buzzer) {}

  void begin() {
    display_.showIdle(wifi_.connected());
    transitionTo(State::IdleClosed);
  }

  void update() {
    wifi_.update();
    buzzer_.update();

    entranceGate_.update();
    exitGate_.update();

    const bool entranceDetected = entranceIR_.active();
    const bool exitDetected = exitIR_.active();

    handleAntiTrap(entranceDetected, exitDetected);
    handleState(entranceDetected, exitDetected);
  }

 private:
  DisplayService& display_;
  WiFiService& wifi_;
  ApiClient& api_;
  RFIDService& rfid_;
  IRSensor& entranceIR_;
  IRSensor& exitIR_;
  GateActuator& entranceGate_;
  GateActuator& exitGate_;
  BuzzerService& buzzer_;

  State state_ = State::IdleClosed;

  unsigned long stateStartedAt_ = 0;
  unsigned long irClearStartedAt_ = 0;
  unsigned long lastMLAttemptAt_ = 0;

  uint8_t mlAttemptCount_ = 0;
  bool mlHadSuccessfulResponse_ = false;

  String pendingRFID_;

  static const char* stateName(State state) {
    switch (state) {
      case State::IdleClosed:
        return "IDLE_CLOSED";
      case State::EntranceValidating:
        return "ENTRANCE_VALIDATING";
      case State::EntranceWaitClear:
        return "ENTRANCE_WAIT_CLEAR";
      case State::EntranceOpening:
        return "ENTRANCE_OPENING";
      case State::EntranceOpenWait:
        return "ENTRANCE_OPEN_WAIT";
      case State::EntranceClosing:
        return "ENTRANCE_CLOSING";
      case State::ExitValidatingPerson:
        return "EXIT_VALIDATING_PERSON";
      case State::ExitOptionalRFID:
        return "EXIT_OPTIONAL_RFID";
      case State::ExitWaitClear:
        return "EXIT_WAIT_CLEAR";
      case State::ExitOpening:
        return "EXIT_OPENING";
      case State::ExitOpenWait:
        return "EXIT_OPEN_WAIT";
      case State::ExitClosing:
        return "EXIT_CLOSING";
      case State::AccessDenied:
        return "ACCESS_DENIED";
      default:
        return "UNKNOWN";
    }
  }

  void transitionTo(State newState) {
    state_ = newState;
    stateStartedAt_ = millis();
    irClearStartedAt_ = 0;

    if (
        newState == State::EntranceValidating ||
        newState == State::ExitValidatingPerson
    ) {
      mlAttemptCount_ = 0;
      lastMLAttemptAt_ = 0;
      mlHadSuccessfulResponse_ = false;
    }

    Serial.print(F("[STATE] "));
    Serial.println(stateName(newState));
  }

  void handleState(
      bool entranceDetected,
      bool exitDetected
  ) {
    switch (state_) {
      case State::IdleClosed:
        handleIdle(entranceDetected, exitDetected);
        break;

      case State::EntranceValidating:
        handleEntranceValidation(entranceDetected);
        break;

      case State::EntranceWaitClear:
        handlePassiveWaitClear(entranceDetected);
        break;

      case State::EntranceOpening:
        if (entranceGate_.isOpen()) {
          display_.show("Silakan masuk", "Lewati gate");
          transitionTo(State::EntranceOpenWait);
        }
        break;

      case State::EntranceOpenWait:
        handleOpenWait(
            entranceDetected,
            entranceGate_,
            State::EntranceClosing
        );
        break;

      case State::EntranceClosing:
        if (entranceGate_.isClosed()) {
          returnToIdle();
        }
        break;

      case State::ExitValidatingPerson:
        handleExitPersonValidation(exitDetected);
        break;

      case State::ExitOptionalRFID:
        handleExitOptionalRFID(exitDetected);
        break;

      case State::ExitWaitClear:
        handlePassiveWaitClear(exitDetected);
        break;

      case State::ExitOpening:
        if (exitGate_.isOpen()) {
          display_.show("Silakan keluar", "Lewati gate");
          transitionTo(State::ExitOpenWait);
        }
        break;

      case State::ExitOpenWait:
        handleOpenWait(
            exitDetected,
            exitGate_,
            State::ExitClosing
        );
        break;

      case State::ExitClosing:
        if (exitGate_.isClosed()) {
          pendingRFID_ = "";
          returnToIdle();
        }
        break;

      case State::AccessDenied:
        if (
            millis() - stateStartedAt_ >=
                AppConfig::ACCESS_DENIED_DISPLAY_MS &&
            !entranceDetected &&
            !exitDetected
        ) {
          returnToIdle();
        }
        break;
    }
  }

  void handleIdle(
      bool entranceDetected,
      bool exitDetected
  ) {
    // Prioritaskan gate keluar jika kedua sensor aktif bersamaan.
    if (exitDetected) {
      pendingRFID_ = "";

      display_.show(
          "Validasi keluar",
          "Kamera AI..."
      );

      transitionTo(State::ExitValidatingPerson);
      return;
    }

    if (entranceDetected) {
      display_.show(
          "Validasi masuk",
          "Kamera AI..."
      );

      transitionTo(State::EntranceValidating);
    }
  }

  // ===========================================================
  // GATE MASUK
  // IR + person detected membuka gate. Tidak ada RFID dan tidak
  // ada alarm "orang tidak sah" pada gate masuk.
  // ===========================================================
  void handleEntranceValidation(bool entranceDetected) {
    if (!entranceDetected) {
      Serial.println(
          F("[ENTRANCE] IR tidak aktif lagi. Validasi dibatalkan.")
      );
      returnToIdle();
      return;
    }

    if (mlValidationFinished()) {
      if (mlHadSuccessfulResponse_) {
        showPassiveMessage(
            "Belum terdeteksi",
            "Gate tertutup",
            State::EntranceWaitClear
        );
      } else {
        showPassiveMessage(
            "Kamera/API gagal",
            "Gate tertutup",
            State::EntranceWaitClear
        );
      }
      return;
    }

    if (!mlAttemptDue()) {
      return;
    }

    registerMLAttempt("masuk");

    const MLResult result = api_.detectPerson();

    if (!result.requestOk) {
      return;
    }

    mlHadSuccessfulResponse_ = true;

    if (!personValid(result)) {
      return;
    }

    Serial.println(
        F("[ENTRANCE] IR + person detected. Gate masuk dibuka.")
    );

    display_.show(
        "Orang terdeteksi",
        "Gate membuka"
    );

    entranceGate_.open();
    transitionTo(State::EntranceOpening);
  }

  // ===========================================================
  // GATE KELUAR - TAHAP 1
  // IR + person detected harus valid terlebih dahulu.
  // ===========================================================
  void handleExitPersonValidation(bool exitDetected) {
    if (
        !exitDetected &&
        millis() - stateStartedAt_ >=
            AppConfig::IR_LOST_GRACE_MS
    ) {
      Serial.println(
          F("[EXIT] IR tidak aktif lagi. Validasi dibatalkan.")
      );
      returnToIdle();
      return;
    }

    if (mlValidationFinished()) {
      if (mlHadSuccessfulResponse_) {
        showPassiveMessage(
            "Orang tidak",
            "terdeteksi",
            State::ExitWaitClear
        );
      } else {
        showPassiveMessage(
            "Kamera/API gagal",
            "Gate tertutup",
            State::ExitWaitClear
        );
      }
      return;
    }

    if (!mlAttemptDue()) {
      return;
    }

    registerMLAttempt("keluar");

    const MLResult result = api_.detectPerson();

    if (!result.requestOk) {
      return;
    }

    mlHadSuccessfulResponse_ = true;

    if (!personValid(result)) {
      return;
    }

    Serial.println(
        F("[EXIT] IR + person detected. Memeriksa RFID opsional.")
    );

    pendingRFID_ = "";

    display_.show(
        "Cek barang",
        "Tempel RFID"
    );

    transitionTo(State::ExitOptionalRFID);
  }

  // ===========================================================
  // GATE KELUAR - TAHAP 2
  // - RFID terbaca: wajib valid/sudah dibayar.
  // - RFID tidak terbaca sampai timeout: dianggap tanpa barang.
  // ===========================================================
  void handleExitOptionalRFID(bool exitDetected) {
    if (rfid_.readUid(pendingRFID_)) {
      display_.show(
          "Cek pembayaran",
          "Mohon tunggu"
      );

      const RFIDValidationResult result =
          api_.validateRFID(pendingRFID_);

      if (!result.requestOk) {
        denyAccess(
            "Server RFID",
            "tidak tersedia"
        );
        return;
      }

      if (!result.allowed) {
        denyAccess(
            "Belum dibayar",
            "Gate tertutup"
        );
        return;
      }

      Serial.println(
          F("[EXIT] RFID valid. Gate keluar dibuka.")
      );

      display_.show(
          "Sudah dibayar",
          "Gate membuka"
      );

      exitGate_.open();
      transitionTo(State::ExitOpening);
      return;
    }

    if (
        millis() - stateStartedAt_ <
        AppConfig::EXIT_RFID_SCAN_WINDOW_MS
    ) {
      return;
    }

    if (
        AppConfig::ALLOW_EXIT_WITHOUT_RFID &&
        exitDetected
    ) {
      Serial.println(
          F("[EXIT] Tidak ada RFID. Dianggap tanpa barang.")
      );

      display_.show(
          "Tanpa barang",
          "Gate membuka"
      );

      exitGate_.open();
      transitionTo(State::ExitOpening);
      return;
    }

    // Orang sudah menjauh sebelum jendela RFID selesai.
    returnToIdle();
  }

  // ===========================================================
  // SAFETY
  // ===========================================================
  void handleAntiTrap(
      bool entranceDetected,
      bool exitDetected
  ) {
    if (
        state_ == State::EntranceClosing &&
        entranceDetected
    ) {
      Serial.println(
          F("[SAFETY] Gate masuk dibuka kembali.")
      );

      display_.show(
          "Objek terdeteksi",
          "Buka kembali"
      );

      entranceGate_.open();
      transitionTo(State::EntranceOpening);
    }

    if (
        state_ == State::ExitClosing &&
        exitDetected
    ) {
      Serial.println(
          F("[SAFETY] Gate keluar dibuka kembali.")
      );

      display_.show(
          "Objek terdeteksi",
          "Buka kembali"
      );

      exitGate_.open();
      transitionTo(State::ExitOpening);
    }
  }

  void handleOpenWait(
      bool irActive,
      GateActuator& gate,
      State closingState
  ) {
    if (
        millis() - stateStartedAt_ <
        AppConfig::MIN_GATE_OPEN_MS
    ) {
      return;
    }

    if (irActive) {
      irClearStartedAt_ = 0;
      return;
    }

    if (irClearStartedAt_ == 0) {
      irClearStartedAt_ = millis();
      return;
    }

    if (
        millis() - irClearStartedAt_ >=
        AppConfig::IR_CLEAR_HOLD_MS
    ) {
      display_.show(
          "Gate menutup",
          "Harap menjauh"
      );

      gate.close();
      transitionTo(closingState);
    }
  }

  void handlePassiveWaitClear(bool irActive) {
    if (
        millis() - stateStartedAt_ <
        AppConfig::PASSIVE_MESSAGE_DISPLAY_MS
    ) {
      return;
    }

    if (!irActive) {
      returnToIdle();
    }
  }

  bool personValid(const MLResult& result) const {
    if (
        !result.requestOk ||
        !result.personDetected
    ) {
      return false;
    }

    if (AppConfig::REQUIRE_SINGLE_PERSON) {
      return result.personCount == 1;
    }

    return result.personCount > 0;
  }

  bool mlAttemptDue() const {
    return
        lastMLAttemptAt_ == 0 ||
        millis() - lastMLAttemptAt_ >=
            AppConfig::ML_RETRY_INTERVAL_MS;
  }

  bool mlValidationFinished() const {
    return
        millis() - stateStartedAt_ >=
            AppConfig::ML_VALIDATION_TIMEOUT_MS ||
        mlAttemptCount_ >=
            AppConfig::ML_MAX_ATTEMPTS;
  }

  void registerMLAttempt(const char* gateName) {
    lastMLAttemptAt_ = millis();
    mlAttemptCount_++;

    Serial.print(F("[ML] Percobaan "));
    Serial.print(gateName);
    Serial.print(' ');
    Serial.print(mlAttemptCount_);
    Serial.print('/');
    Serial.println(AppConfig::ML_MAX_ATTEMPTS);
  }

  void showPassiveMessage(
      const String& line1,
      const String& line2,
      State waitState
  ) {
    Serial.print(F("[INFO] "));
    Serial.print(line1);
    Serial.print(F(" | "));
    Serial.println(line2);

    display_.show(line1, line2);
    transitionTo(waitState);
  }

  // Hanya digunakan untuk kegagalan RFID/pembayaran di gate keluar.
  void denyAccess(
      const String& line1,
      const String& line2
  ) {
    Serial.print(F("[DENIED] "));
    Serial.print(line1);
    Serial.print(F(" | "));
    Serial.println(line2);

    pendingRFID_ = "";

    display_.show(line1, line2);
    buzzer_.start();

    transitionTo(State::AccessDenied);
  }

  void returnToIdle() {
    pendingRFID_ = "";
    display_.showIdle(wifi_.connected());
    transitionTo(State::IdleClosed);
  }
};

// =============================================================
// OBJECT COMPOSITION
// =============================================================
DisplayService display(
    AppConfig::LCD_ADDRESS,
    AppConfig::LCD_COLUMNS,
    AppConfig::LCD_ROWS
);

WiFiService wifiService(
    AppConfig::WIFI_SSID,
    AppConfig::WIFI_PASSWORD,
    AppConfig::WIFI_RECONNECT_INTERVAL_MS
);

PayloadCrypto payloadCrypto(
    AppConfig::REQUEST_KEY,
    AppConfig::RESPONSE_KEY,
    AppConfig::DEVICE_ID
);

ApiClient apiClient(
    AppConfig::ML_API_URL,
    AppConfig::RFID_API_URL,
    AppConfig::HTTP_CONNECT_TIMEOUT_MS,
    AppConfig::HTTP_RESPONSE_TIMEOUT_MS,
    payloadCrypto
);

IRSensor entranceIR(
    AppConfig::IR_MASUK_PIN,
    AppConfig::IR_ACTIVE_LEVEL
);

IRSensor exitIR(
    AppConfig::IR_KELUAR_PIN,
    AppConfig::IR_ACTIVE_LEVEL
);

RFIDService rfidService(
    AppConfig::RFID_SS_PIN,
    AppConfig::RFID_RST_PIN,
    AppConfig::RFID_DEBOUNCE_MS
);

BuzzerService buzzer(
    AppConfig::BUZZER_PIN,
    AppConfig::BUZZER_DURATION_MS
);

GateActuator entranceGate(
    AppConfig::SERVO_MASUK_PIN,
    AppConfig::SERVO_CLOSED_ANGLE,
    AppConfig::SERVO_OPEN_ANGLE,
    AppConfig::SERVO_STEP_INTERVAL_MS
);

GateActuator exitGate(
    AppConfig::SERVO_KELUAR_PIN,
    AppConfig::SERVO_CLOSED_ANGLE,
    AppConfig::SERVO_OPEN_ANGLE,
    AppConfig::SERVO_STEP_INTERVAL_MS
);

SmartGateController controller(
    display,
    wifiService,
    apiClient,
    rfidService,
    entranceIR,
    exitIR,
    entranceGate,
    exitGate,
    buzzer
);

// =============================================================
// ARDUINO ENTRY POINT
// =============================================================
void setup() {
  Serial.begin(115200);
  delay(200);

  display.begin(
      AppConfig::I2C_SDA_PIN,
      AppConfig::I2C_SCL_PIN
  );

  display.show(
      "Smart Souvenir",
      "Inisialisasi..."
  );

  entranceIR.begin();
  exitIR.begin();
  buzzer.begin();
  rfidService.begin();

  entranceGate.begin(
      AppConfig::SERVO_MIN_PULSE_US,
      AppConfig::SERVO_MAX_PULSE_US
  );

  exitGate.begin(
      AppConfig::SERVO_MIN_PULSE_US,
      AppConfig::SERVO_MAX_PULSE_US
  );

  payloadCrypto.begin();
  wifiService.begin(display);
  controller.begin();
}

void loop() {
  controller.update();
  delay(2);
}
