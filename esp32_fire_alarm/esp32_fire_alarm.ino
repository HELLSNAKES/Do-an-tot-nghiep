// =====================================================================
// DO AN TOT NGHIEP - HE THONG BAO CHAY THONG MINH
// ESP32 + cam bien lua (bao chua) + MQ2 (khoi) + DHT11 (nhiet do)
//       + quat hut khoi + coi bao + bom nuoc + LCD 16x2 I2C
//       + gui du lieu JSON len server Python (HTTP POST)
// ---------------------------------------------------------------------
// Thu vien can cai (Arduino IDE -> Tools -> Manage Libraries):
//   - LiquidCrystal_I2C  (Frank de Brabander)
//   - DHT sensor library (Adafruit)
//   - Adafruit Unified Sensor
// =====================================================================
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>

// ---------------- CAU HINH MANG & SERVER ----------------
const char* WIFI_SSID  = "";
const char* WIFI_PASS  = "";
// IP cua may chay server (chay `ipconfig` de xem IPv4)
// Chay server TRUOC de doc API key trong console, hoac tao tren web
// (web -> Them thiet bi). Sau do chen vao day truoc khi nap.
const char* API_KEY     = "2a6cc78ac6934718514d80d1e0539375";
const char* SERVER_URL  = "http://192.168.1.110:5000/api/data";
const char* COMMAND_URL = "http://192.168.1.110:5000/api/command";
const char* DEVICE_ID   = "esp32-fire-01";

// ---------------- CAM BIEN ----------------
// CAME BIEN LUA    : module 3 chan (VCC / GND / D0) -> D0 noi GPIO34
//   + Nen cap VCC = 3.3V (quan GT hoac chia dao VCC 5V)
//   + Neu Serial luon hien sao Leonardo chan sau -> doi FLAME_D0_ACTIVE_HIGH
const int   PIN_FLAME = 34;              // chi doc duoc (34-39), digitalRead OK
const bool  FLAME_D0_ACTIVE_HIGH = false; // true: D0 HIGH = co lua; false: nguoc lai
const int   PIN_MQ2   = 35;   // dao dong cua cam bien khoi MQ2
const int   PIN_DHT   = 4;    // chan du lieu DHT11
#define DHT_TYPE DHT11

// ---------------- THIET BI DAU RA ----------------
const int   PIN_BUZZER = 26;  // coi bao
const int   PIN_FAN    = 27;  // relay 1 -> quat hut khoi
const int   PIN_PUMP   = 14;  // relay 2 -> bom nuoc chua chay
const bool  RELAY_ACTIVE_LOW  = true;   // Đổi thành false vì module của bạn cần mức HIGH (hoặc chạm GND kêu thì tùy loại, nhưng chạm GND kêu nghĩa là cần đảo chiều)
const bool  BUZZER_ACTIVE_LOW = false;  // doi true neu coi dung chan HIGH = tat

// ---------------- NGUONG BAO CHAY ----------------
const int   FLAME_THRESHOLD = 1500;  // module 3 chan chi co D0 -> flameVal = 0 hoac 4095
                                     // (409 5 >= 1500 = co lua); giu neu dung ban AO
const int   SMOKE_WARN      = 500;   // canh bao khoi
const int   SMOKE_ALARM     = 700;   // bao chay do khoi
const float TEMP_WARN       = 40.0;  // DHT11 chi doc duoc toi da 50 do C
const float TEMP_ALARM      = 45.0;

// ---------------- CHU KY LAM VIEC ----------------
const unsigned long SENSOR_MS = 2000;   // doc cam bien 2s/lan (DHT11 toi thieu 1-2s)
const unsigned long POST_MS   = 5000;   // gui du lieu len server 5s/lan
const unsigned long LCD_MS    = 2500;   // doi trang man hinh LCD
const unsigned long WIFI_MS   = 10000;  // thu ket noi lai WiFi

enum State { ST_NORMAL, ST_WARN, ST_ALARM };

DHT dht(PIN_DHT, DHT_TYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2);  // doi dia chi 0x3F neu I2C Scanner bao 0x3F

int   flameVal = 0, smokeVal = 0;
float temp = 0, humi = 0;
State st = ST_NORMAL, effState = ST_NORMAL;
bool  alarmTest = false;   // lenh serial 't' de thu coi/bom
bool  manualAlarm = false; // lenh "bao chay thu cong" tu web (server)
bool  stateChanged = false, lastPostOk = false;
unsigned long lastRead = 0, lastPost = 0, lastLcd = 0, lastWifiTry = 0;
int lcdPage = 0;

// ---------------- HAM HO TRO ----------------
void setRelay(int pin, bool on) {
  digitalWrite(pin, RELAY_ACTIVE_LOW ? !on : on);
}
void setBuzzer(bool on) {
  digitalWrite(PIN_BUZZER, BUZZER_ACTIVE_LOW ? !on : on);
}
const char* stateName(State s) {
  switch (s) {
    case ST_WARN:  return "WARNING";
    case ST_ALARM: return "ALARM";
    default:       return "NORMAL";
  }
}
const char* stateText(State s) {   // van ban hien tren LCD
  switch (s) {
    case ST_WARN:  return "CANH BAO !";
    case ST_ALARM: return "! BAO CHAY !";
    default:       return "AN TOAN";
  }
}

// ---------------- DOC CAM BIEN ----------------
void readSensors() {
  bool flameHit = (digitalRead(PIN_FLAME) == (FLAME_D0_ACTIVE_HIGH ? HIGH : LOW));
  flameVal = flameHit ? 4095 : 0;     // quy ve ADC 0/4095 giong ban AO chong JSON
  smokeVal = analogRead(PIN_MQ2);
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (isnan(t) || isnan(h)) {
    Serial.println("[DHT11] khong doc duoc, giu gia tri cu");
  } else {
    temp = t;
    humi = h;
  }
}

// ---------------- QUYET DINH TRANG THAI ----------------
void evaluateState() {
  State raw = ST_NORMAL;
  if (flameVal >= FLAME_THRESHOLD || smokeVal >= SMOKE_ALARM || temp >= TEMP_ALARM)
    raw = ST_ALARM;
  else if (smokeVal >= SMOKE_WARN || temp >= TEMP_WARN)
    raw = ST_WARN;

  State prev = effState;
  st = raw;
  effState = (alarmTest || manualAlarm) ? ST_ALARM : raw;  // test serial / web manual
  if (effState != prev) stateChanged = true;
}

// ---------------- DIEU KHIEN THIET BI ----------------
void applyOutputs() {
  bool alarm = (effState == ST_ALARM);
  bool warn  = (effState == ST_WARN);

  setRelay(PIN_FAN, alarm || warn);   // quat: hut khoi khi co canh bao
  setRelay(PIN_PUMP, alarm);          // bom: chi chay khi bao chay
  // coi: keu nhap nhay 200ms khi bao chay
  setBuzzer(alarm && ((millis() % 400) < 200));
}

// ---------------- HINH LCD 16x2 ----------------
void renderLCD() {
  if (millis() - lastLcd < LCD_MS) return;
  lastLcd = millis();
  lcdPage = (lcdPage + 1) % 2;
  lcd.clear();
  lcd.setCursor(0, 0);
  char l1[17];
  if (lcdPage == 0) {
    snprintf(l1, sizeof(l1), "T:%dC   H:%d%%", (int)temp, (int)humi);
  } else {
    snprintf(l1, sizeof(l1), "L:%d K:%d", flameVal, smokeVal);  // L = lua, K = khoi
  }
  lcd.print(l1);
  lcd.setCursor(0, 1);
  lcd.print(stateText(effState));
  lcd.print(WiFi.status() == WL_CONNECTED ? " W:OK" : " W:--");
}

// ---------------- GUI LEN SERVER ----------------
bool postReading() {
  if (WiFi.status() != WL_CONNECTED) return false;

  String body = "{";
  body += "\"device_id\":\"" + String(DEVICE_ID) + "\",";
  body += "\"temperature\":" + String(temp, 1) + ",";
  body += "\"humidity\":" + String(humi, 1) + ",";
  body += "\"flame\":" + String(flameVal) + ",";
  body += "\"smoke\":" + String(smokeVal) + ",";
  body += "\"flame_detected\":" + String((flameVal >= FLAME_THRESHOLD) ? "true" : "false") + ",";
  body += "\"alarm\":" + String((effState == ST_ALARM) ? "true" : "false") + ",";
  body += "\"state\":\"" + String(stateName(effState)) + "\"";
  body += "}";

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Api-Key", API_KEY);
    http.setTimeout(3000);
    int code = http.POST(body);
    http.end();
    return (code == 200 || code == 201);
  }

  // ---------------- DOC LENH TU SERVER (bao chay thu cong / ACK) ----------------
  void fetchCommand() {
    if (WiFi.status() != WL_CONNECTED) return;
    HTTPClient http;
    http.begin(COMMAND_URL);
    http.addHeader("X-Api-Key", API_KEY);
    http.setTimeout(3000);
    int code = http.GET();
    bool manual = false;
    if (code == 200) {
      String payload = http.getString();
      manual = payload.indexOf("\"manual_alarm\": true") >= 0
            || payload.indexOf("\"manual_alarm\":true") >= 0;
    }
    http.end();
    if (code == 200 && manual != manualAlarm) {
      manualAlarm = manual;
      evaluateState();
      Serial.println(manualAlarm ? "[CMD] Web rang buoc BAO CHAY THU CONG"
                                 : "[CMD] Huy bao chay thu cong (ACK)");
    }
  }

// ---------------- WIFI ----------------
void maintainWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - lastWifiTry < WIFI_MS) return;
  lastWifiTry = millis();
  Serial.println("[WiFi] mat ket noi, thu lai...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

// ---------------- LENH SERIAL ----------------
void handleSerial() {
  if (!Serial.available()) return;
  char c = Serial.read();
  if (c == 't' || c == 'T') {          // bat/tat che do thu bao chay
    alarmTest = !alarmTest;
    evaluateState();
    Serial.println(alarmTest ? "[TEST] bat Che do thu bao chay"
                             : "[TEST] tat Che do thu bao chay");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_FLAME, INPUT);   // cam bien lua (D0) - GPIO34 chi doc, module san day ra
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  pinMode(PIN_PUMP, OUTPUT);
  setBuzzer(false); setRelay(PIN_FAN, false); setRelay(PIN_PUMP, false);

  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0); lcd.print("HE THONG BAO CHAY");
  lcd.setCursor(0, 1); lcd.print("Dang ket noi...");
  dht.begin();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) delay(250);
  lcd.clear();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WiFi] connected, IP: %s\n", WiFi.localIP().toString().c_str());
    lcd.setCursor(0, 0); lcd.print("WiFi: OK");
    lcd.setCursor(0, 1); lcd.print(WiFi.localIP());
    delay(1500);
    lcd.clear();
  } else {
    Serial.println("[WiFi] khong ket noi duoc (se thu lai sau)");
  }
  lastLcd = millis();
}

void loop() {
  maintainWifi();
  unsigned long now = millis();

  if (now - lastRead >= SENSOR_MS) {
    lastRead = now;
    readSensors();
    evaluateState();
    renderLCD();
    Serial.printf("lua=%d khoi=%d t=%.1fC h=%.1f%% state=%s\n",
                  flameVal, smokeVal, temp, humi, stateName(effState));
  }
  applyOutputs();   // goi moi loop de coi nhap nhay lian tuc khi bao chay

  if (stateChanged || now - lastPost >= POST_MS) {
    stateChanged = false;
    lastPost = now;
    lastPostOk = postReading();
    Serial.println(lastPostOk ? "[HTTP] gui len server OK"
                              : "[HTTP] loi / server dang offline");
        fetchCommand();
      }

  handleSerial();
}