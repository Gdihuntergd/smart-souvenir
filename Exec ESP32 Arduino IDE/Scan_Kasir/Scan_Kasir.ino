#include <SPI.h>
#include <MFRC522.h>
#include <WiFi.h>
#include <HTTPClient.h>

// =======================
// WIFI
// =======================
const char* ssid = "wudeheli";
const char* password = "kalau0000";

// =======================
// PIN RFID
// =======================
const int RST_PIN = 2;
const int SS_PIN  = 5;

// =======================
// PIN BUZZER
// =======================
const int BUZZER_PIN = 4;

MFRC522 mfrc522(SS_PIN, RST_PIN);

// =======================
// SERVER LOKAL (IP)
// GANTI SESUAI IP PC / SERVER
// =======================
//const char* serverName = "http://10.80.112.77/kasir_souvenir/kasir_souvenir/api/scan_rfid.php";
const char* serverName = "http://192.168.100.74:5000/kasir/api/scan_rfid.php"
// contoh XAMPP: htdocs/kasir_souvenir/api/scan_rfid.php

// =======================
void beepSuccess() {
  for (int i = 0; i < 2; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(120);
    digitalWrite(BUZZER_PIN, LOW);
    delay(120);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("Booting...");

  // BUZZER
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  // RFID
  SPI.begin();
  mfrc522.PCD_Init();
  Serial.println("RFID Ready");

  // WIFI
  WiFi.begin(ssid, password);
  Serial.print("Connecting");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nConnected to WiFi!");
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());
}

void loop() {

  // Cek kartu RFID
  if (!mfrc522.PICC_IsNewCardPresent()) return;
  if (!mfrc522.PICC_ReadCardSerial()) return;

  // Ambil UID
  String uidString = "";
  for (byte i = 0; i < mfrc522.uid.size; i++) {
    if (mfrc522.uid.uidByte[i] < 0x10) uidString += "0";
    uidString += String(mfrc522.uid.uidByte[i], HEX);
  }
  uidString.toUpperCase();

  Serial.print("Scan UID: ");
  Serial.println(uidString);

  // Kirim ke server lokal
  if (WiFi.status() == WL_CONNECTED) {

    WiFiClient client;     // HTTP client biasa
    HTTPClient http;

    String url = String(serverName) + "?uid=" + uidString;
    Serial.println("Requesting: " + url);

    if (http.begin(client, url)) {
      int httpCode = http.GET();

      Serial.print("HTTP Code: ");
      Serial.println(httpCode);

      if (httpCode > 0) {
        String payload = http.getString();
        Serial.println("Response:");
        Serial.println(payload);
        beepSuccess();
      } else {
        Serial.print("HTTP Error: ");
        Serial.println(http.errorToString(httpCode));
      }

      http.end();
    } else {
      Serial.println("HTTP begin gagal");
    }

  } else {
    Serial.println("WiFi not connected!");
  }

  mfrc522.PICC_HaltA();
  delay(1200);
}
