#include <WiFi.h>
#include <WiFiClient.h>        // HTTP (versi IP)
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>

// ===================
// PIN RFID RC522
// ===================
// Rangkaian: RC522 VCC->3.3V, GND->GND, IRQ (kosong)
#define RST_PIN    2   // RST RC522
#define SS_PIN     5   // SDA/SS RC522
#define MISO_PIN   19  // MISO RC522
#define MOSI_PIN   23  // MOSI RC522
#define SCK_PIN    21  // SCK RC522
#define BUZZER_PIN 14  // Buzzer + -> GPIO13, Buzzer - -> GND

MFRC522 mfrc522(SS_PIN, RST_PIN);

// ===================
// WIFI
// ===================
const char* ssid     = "wudeheli";
const char* password = "kalau0000";

// API server (HTTP via IP lokal / XAMPP)
String serverName = "http://192.168.100.74:5000/stock/api/insert_rfid.php"

// client (nama dipertahankan agar perubahan minimal)
WiFiClient secureClient;

void beepOnce(unsigned int ms = 120) {
  digitalWrite(BUZZER_PIN, HIGH);
  delay(ms);
  digitalWrite(BUZZER_PIN, LOW);
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW); // pastikan diam saat start

  // ---- KONEKSI WIFI ----
  Serial.println();
  Serial.println("Menghubungkan ke WiFi...");
  Serial.print("SSID: ");
  Serial.println(ssid);

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  int maxTries = 40; // ~20 detik
  while (WiFi.status() != WL_CONNECTED && maxTries-- > 0) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.println("WiFi connected!");
    Serial.print("IP ESP32: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("Gagal konek WiFi. Cek SSID/password atau jarak ke router.");
  }

  // ---- RFID ----
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);
  mfrc522.PCD_Init();
  Serial.println("RFID siap. Tempelkan kartu...");
}

void loop() {
  // Tidak ada kartu -> buzzer diam
  if (!mfrc522.PICC_IsNewCardPresent() || !mfrc522.PICC_ReadCardSerial()) {
    digitalWrite(BUZZER_PIN, LOW);
    return;
  }

  // Ada kartu -> bunyikan sekali
  beepOnce(120);

  // Ambil UID jadi string HEX tanpa spasi
  String uidStr = "";
  Serial.print("UID (HEX): ");
  for (byte i = 0; i < mfrc522.uid.size; i++) {
    if (mfrc522.uid.uidByte[i] < 0x10) {
      Serial.print("0");
      uidStr += "0";
    }
    Serial.print(mfrc522.uid.uidByte[i], HEX);
    uidStr += String(mfrc522.uid.uidByte[i], HEX);
  }
  Serial.println();
  uidStr.toUpperCase();
  Serial.print("UID string: ");
  Serial.println(uidStr);

  // Kirim ke server
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    String url = serverName + "?uid=" + uidStr;
    Serial.print("Request URL: ");
    Serial.println(url);

    // HTTP via IP
    http.begin(secureClient, url);
    int httpResponseCode = http.GET();

    if (httpResponseCode > 0) {
      Serial.print("HTTP Response code: ");
      Serial.println(httpResponseCode);
      String payload = http.getString();
      Serial.print("Response: ");
      Serial.println(payload);
    } else {
      Serial.print("Error code: ");
      Serial.println(httpResponseCode);
    }
    http.end();
  } else {
    Serial.println("WiFi terputus!");
  }

  // Stop kartu
  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();

  delay(100); // jeda biar tidak double-detect & double-beep
}