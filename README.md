# 🔥 ĐỒ ÁN TỐT NGHIỆP — HỆ THỐNG BÁO CHÁY THÔNG MINH (ESP32)

> ESP32 + cảm biến lửa + cảm biến khói MQ2 + DHT11 + quạt hút + còi báo + bơm nước + LCD 16x2 I2C
> **Server Python (Flask) riêng** — **mọi dữ liệu server trả về dạng JSON**
> Web dashboard · **Đăng nhập/xác thực** · **Multi-device** · **Báo cháy thủ công + Ngừng/Chặn (ACK)**
> **Telegram**: gửi cảnh báo qua `sendMessage` và **file báo cáo qua `sendDocument` (multipart `-F`)**

---

## 1. Tổng quan hệ thống

```
┌─────────────────── Thiết bị (có thể nhiều ESP32) ───────────────────┐
│ Cảm biến lửa  → GPIO34 ┐                                            │
│ Cảm biến MQ2  → GPIO35 ┤        HTTP POST JSON + X-Api-Key         │
│ DHT11         → GPIO4  ┤   ESP32 ────────────────────────────►      │
│ LCD 16x2 I2C  → 21/22  ┤   ◄── GET /api/command (lenh manual)      │
│ Còi/26, Quạt/27, Bơm/14┘                                            │
└──────────────────────────────────┬───────────────────────────────────┘
                                   ▼
┌──────────────── SERVER PYTHON (Flask, cổng 5000) ────────────────────┐
│  /api/data (X-Api-Key) ──► SQLite (readings/devices/users/events)   │
│  /api/command            ► trang thai bao chay thu cong cho ESP32    │
│  /api/latest,history,state,stats,devices,events,manual,report       │
│      (JSON) ──► chi tra ve khi DANG NHAP (Flask session cookie)      │
│  Telegram: sendMessage + sendDocument (multipart -F, curl style)     │
└──────────────┬──────────────────────────────┬────────────────────────┘
               ▼                              ▼
     ┌──────────────────┐          ┌────────────────────────┐
     │ Web Dashboard     │          │ Telegram Bot            │
     │ /login → Dang nhap│          │ - canh bao bao chay     │
     │ - xem JSON realtime│         │ - file JSON hien trang   │
     │ - NUT BAO CHAY     │         │ - bao cao CSV dinh ky    │
     │   THU CONG + ACK   │         │                         │
     │ - quan ly devices  │         └────────────────────────┘
     └──────────────────┘
```

**Bốn lớp hoạt động chính:**

| Trạng thái | Điều kiện | Hành động |
|---|---|---|
| `NORMAL` (AN TOAN) | Mọi thông số dưới ngưỡng | Tắt còi, bơm, quạt |
| `WARNING` (CẢNH BÁO) | Khói ≥ 1800 **hoặc** nhiệt ≥ 40 °C | Bật quạt hút, cảnh báo trên web |
| `ALARM` (BÁO CHÁY) | Lửa ≥ 1500 **hoặc** khói ≥ 2800 **hoặc** nhiệt ≥ 45 °C | Còi nhấp nháy, bơm bật, web đỏ + **Telegram cảnh báo** |
| **BÁO CHÁY THỦ CÔNG** | Người dùng bấm nút trên web | Server ép ESP32 vào ALARM qua `/api/command`; **NGỪNG/CHẶN (ACK)** để tắt |

## 2. Danh sách linh kiện

| # | Linh kiện | SL | Ghi chú |
|---|---|---|---|
| 1 | ESP32 DevKit (WROOM-32) | 1+ | Nhiều ESP32 = multi-device |
| 2 | Cảm biến lửa (flame sensor) | 1 | Module **3 chân: VCC / GND / D0** — cài `FLAME_D0_ACTIVE_HIGH` đúng chiều |
| 3 | Cảm biến khói MQ-2 | 1 | Module có `AO`+`DO`, cần preheat |
| 4 | Cảm biến DHT11 | 1 | 0–50 °C |
| 5 | LCD 16x2 I2C (PCF8574) | 1 | Địa chỉ `0x27` (hoặc `0x3F`) |
| 6 | Module relay 1 kênh | 2 | Quạt + bơm |
| 7 | Quạt hút DC 5V/12V | 1 | |
| 8 | Bơm nước mini DC | 1 | Demo chữa cháy |
| 9 | Còi báo (buzzer module) | 1 | |
| 10 | Nguồn 5V/3.3V, dây, breadboard | - | Quạt/bơm dùng nguồn RIÊNG |

## 3. Sơ đồ đấu nối

| Thiết bị | Chân ESP32 | Chi tiết |
|---|---|---|
| Cảm biến lửa (3 chân) → `D0` | **GPIO34** | Module VCC 5V thì **cấp 3.3V** hoặc chia áp cho D0 (GPIO không chịu 5V) |
| MQ-2 → `AO` | **GPIO35** | ADC1 |
| DHT11 → `DATA` | **GPIO4** | Pull-up 10k về 3.3V |
| LCD I2C → `SDA` | **GPIO21** | VCC LCD 5V, GND chung |
| LCD I2C → `SCL` | **GPIO22** | |
| Còi → `OUT` | **GPIO26** | |
| Relay 1 → `IN1` (quạt) | **GPIO27** | `COM/NO` nối tiếp nguồn quạt |
| Relay 2 → `IN2` (bơm) | **GPIO14** | `COM/NO` nối tiếp nguồn bơm |
| GND | **GND** | ⚠️ Chung GND: ESP32 – relay – nguồn |

⚠️ **An toàn:**
1. Demo chỉ dùng quạt/bơm **DC 5V–12V**, **không cắm 220VAC** vào relay (nếu bắt buộc phải có hộp cách điện + relay chính hãng + thầy duyệt).
2. Đầu `AO` của MQ2/cảm biến lửa (5V) **có thể làm hỏng ESP32** → chia áp 10kΩ+20kΩ hoặc cấp 3.3V cho module.
3. Relay TF-380 thường ACTIVE LOW → hằng `RELAY_ACTIVE_LOW` trong code.

## 4. Cấu trúc thư mục

```
do an/
├── code.md                        ← tài liệu + TOÀN BỘ code (file này)
├── .github/workflows/
│   └── build-ios.yml              ← GitHub Actions: build app iOS trên macOS runner
├── esp32_fire_alarm/
│   └── esp32_fire_alarm.ino       ← code nạp ESP32
├── mobile_app/                    ← APP ĐIỆN THOẠI (Capacitor → iOS)
│   ├── package.json               ← @capacitor/core + cli + ios
│   ├── capacitor.config.json      ← appId com.doan.baochay, webDir www
│   ├── ios/                       ← platform iOS (sinh bởi npx cap add ios)
│   └── www/index.html             ← TOÀN BỘ app (login, dashboard, ACK...)
└── server/
    ├── app.py                     ← server: JSON API, auth, multi-device, Telegram
    ├── simulate.py                ← mock ESP32 (cần ESP32_API_KEY)
    ├── requirements.txt           ← flask + requests
    ├── fire_alarm.db              ← SQLite (tự tạo lúc chạy đầu tiên)
    └── templates/
        ├── index.html             ← dashboard web (cần đăng nhập)
        └── login.html             ← trang đăng nhập
```

## 5. BẢO MẬT & MULTI-DEVICE

### 5.1 Đăng nhập web (Flask session)

- Truy cập `/` chưa đăng nhập → **tự chuyển hướng `/login`**; API web trả `401` nếu chưa đăng nhập.
- Tài khoản khởi tạo mặc định: **`admin` / `admin123`** (đổi bằng biến môi trường `ADMIN_USER`, `ADMIN_PASS`; mật khẩu lưu **băm** trong bảng `users`).
- Mọi hành động (đăng nhập, bật báo cháy, ACK, thêm/xoá thiết bị…) đều ghi vào bảng `events` (nhật ký hiển thị trên web).

### 5.2 Xác thực thiết bị — API key (`X-Api-Key`)

- Mỗi ESP32 có **1 API key riêng** (bảng `devices`) — đây là **multi-device**:
  - **Quy định cấp key:** chạy server lần đầu → console in ra key mặc định của `esp32-fire-01`; hoặc trên web bấm **＋ Thêm** để tạo thiết bị mới (web hiện `device_id` + `api_key` → chèn vào `.ino`).
  - ESP32 gửi header `X-Api-Key: <key>` trong mọi request → thiếu/sai key server trả **401**.
  - Web hỗ trợ: **Bật/tắt** device (tắt = không nhận data), **Sinh lại API key** (khi nghi lộ), **Xoá**. Cột *Seen gần nhất* cập nhật khi device gửi data.
- Bảng endpoint & vai trò:

| Endpoint | Cách xác thực | Mô tả |
|---|---|---|
| `POST /api/login` (JSON) | — (user/pass) | Trả `app_token` cho app mobile |
| `GET /`, `/login`, `/logout` | Session cookie | Trang web |
| `GET /api/latest, history, state, stats, events, devices` | Session **hoặc** `X-App-Token` | JSON cho dashboard + app mobile |
| `POST /api/devices`, `/devices/<id>/toggle, regen, delete` | Session **hoặc** `X-App-Token` | Quản lý multi-device |
| `POST /api/manual`, `/api/report` | Session **hoặc** `X-App-Token` | Báo cháy thủ công / gửi báo cáo TG |
| `POST /api/data` | **`X-Api-Key`** | ESP32 gửi dữ liệu |
| `GET /api/command` | **`X-Api-Key`** | ESP32 đọc lệnh thủ công |

- Trang HTML `/` **chỉ** chấp nhận session (không nhận token qua header/query).
- CORS đã mở cho `/api/*` (`Access-Control-Allow-Origin: *`) → JS từ domain khác fetch được.

### 5.3 Gọi API từ App trên điện thoại (GET API)

Web dashboard của server vẫn chạy nguyên — nhưng nếu bạn tự làm **app/web app riêng** trên điện thoại thì chỉ cần **token** thay cho cookie:

**Bước 1 — Lấy token** (một trong ba cách):

```text
# a) Xem console khi chay server:
Mobile app token (POST /api/login hoac header X-App-Token): <32-40 ky tu>

# b) App tu dang nhap lay token (khong can cookie):
POST /api/login   body: {"username":"admin","password":"admin123"}
→ {"status":"ok","user":"admin","app_token":"<token>"}

# c) Dat truoc (restart server):  setx APP_TOKEN my-secret-token
```

**Bước 2 — Gọi API bằng header `X-App-Token`:**

```bash
curl -H "X-App-Token: <token>" https://baochay.example.com/api/latest
```

```javascript
// JavaScript / web app rieng (CORS da mo cho /api/*)
const r = await fetch(`${BASE}/api/history?limit=50`, { 
  headers: { 'X-App-Token': TOKEN }
});
const { data } = await r.json();   // [{id, ts, temperature, ...}]
```

```dart
// Flutter (package http)
final r = await http.get(
  Uri.parse('$BASE/api/state'),
  headers: {'X-App-Token': token},
);
```

**Ma trận xác thực 3 tần:**

| Client | Cách xác thực |
|---|---|
| Web dashboard (trang của server) | Cookie session (`/login` HTML form) |
| App mobile / frontend từ domain khác | Header **`X-App-Token`** (hoặc `?token=`) + CORS |
| ESP32 | **`X-Api-Key`** (mỗi thiết bị 1 key riêng) |

Lưu ý:

- Mọi API JSON (`latest`, `history`, `state`, `stats`, `events`, `devices`, `manual`, `report`) đều nhận token — app của bạn có cả nút **Báo cháy thủ công / ACK** được.
- Sai/thiếu token → `401 {"error":"chua dang nhap (can cookie hoac X-App-Token)"}`.
- Nhật ký audit ghi actor = `app-token` cho các thao tác từ app.
- Token là bí mật — đừng commit/chia sẻ công khai; nghi lộ thì `setx APP_TOKEN <moi>` + restart.

## 6. CẤU HÌNH TRƯỚC KHI CHẠY / NẠP

### 6.1 WiFi + API key trong `.ino`

```cpp
const char* WIFI_SSID  = "TenWiFiCuaBan";
const char* WIFI_PASS  = "MatKhauWiFi";
const char* API_KEY     = "chen-api-key-tu-console-hoac-web";  // ← BẮT BUỘC
const char* SERVER_URL  = "http://192.168.1.100:5000/api/data";
const char* COMMAND_URL = "http://192.168.1.100:5000/api/command";
```

IP máy chạy server: `ipconfig` → IPv4. ESP32 và máy phải cùng mạng WiFi.

### 6.2 Telegram (tùy chọn — có token thì server tự gửi)

Lấy 2 giá trị rồi khai báo **trước khi** `python app.py` (Windows PowerShell):

```text
# 1. Tao bot: chat voi @BotFather tren Telegram → nhan BOT_TOKEN
# 2. Lay chat id: gui 1 tin cho bot, roi mo:
#    https://api.telegram.org/bot<TOKEN>/getUpdates  → "chat":{"id": 987654321}
setx TELEGRAM_BOT_TOKEN  123456:ABC-DEF...
setx TELEGRAM_CHAT_ID    987654321
# (tuy chon) chu ky bao cao CSV: giây, mac dinh 3600
setx TELEGRAM_REPORT_SEC 3600
python app.py
```

Không đặt token → server vẫn chạy, chỉ in cảnh báo `Telegram: TAT` (không crash).

### 6.3 Hosting qua Cloudflare Tunnel (xem web từ mọi nơi)

**Web không cần sửa dòng nào** — toàn bộ `fetch('/api/...')`, `/login`... là URL tương đối, tự bám theo domain người dùng mở; server đã `host="0.0.0.0"` nên cloudflared nối thẳng `localhost:5000`.

```text
# Cai cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
cloudflared tunnel login                 # dang nhap Cloudflare
cloudflared tunnel create bao-chay       # tao tunnel
cloudflared tunnel route dns bao-chay baochay.example.com

# config.yml (dat trong C:\Users\boi-dung\.cloudflared`):
#   tunnel: <id-vua-tao>
#   credentials-file: <duong-dan>/<id>.json
#   ingress:
#     - hostname: baochay.example.com
#       service: http://localhost:5000
#     - service: http_status:404
cloudflared tunnel run bao-chay

# Cach nhanh (mien phi, domain tam thoi, khong can ten mien):
cloudflared tunnel --url http://localhost:5000
```

Khi đã chạy:

| Thành phần | Cấu hình |
|---|---|
| **Web / điện thoại** | Mở `https://baochay.example.com` → đăng nhập `admin/...` — **không sửa code** |
| **ESP32** | **Giữ nguyên** `http://192.168.x.x:5000` (cùng mạng LAN với máy) — KHÔNG cần HTTPS, không đổi gì |
| **Telegram** | Vẫn bình thường (server tự đi ra Internet) |
| **simulate.py** | Vẫn `127.0.0.1` (chạy trên cùng máy) |
| Port router | **Không cần mở/port-forward** (cloudflared đi ra bằng kết nối outbound) |

**Trường hợp ESP32 BẮT BUỘC qua tunnel** (server đặt trên VPS/máy khác mạng) → đổi URL sang `https://...` và thêm code HTTPS (áp dụng cho cả `postReading()` và `fetchCommand()`):

```cpp
#include <WiFiClientSecure.h>
...
WiFiClientSecure wcs;
wcs.setInsecure();          // bo qua kiem tra chung chi (du cho do an; dung CA toi dac thi bo mat khau)
HTTPClient http;
http.begin(wcs, SERVER_URL); // SERVER_URL = "https://baochay.example.com/api/data"
http.addHeader(X-Api-Key...);
```

> Chú ý: HTTPS nặng hơn HTTP ~ 1-2s/lần gửi với ESP32 — nếu server và ESP32 cùng mạng LAN thì **luôn ưu tiên IP LAN**.

## 7. Code ESP32 — `esp32_fire_alarm/esp32_fire_alarm.ino`

**Thư viện** (Arduino IDE → Manage Libraries): `LiquidCrystal_I2C` (Frank de Brabander), `DHT sensor library` (Adafruit) + `Adafruit Unified Sensor`. Board **ESP32 Dev Module**, Serial **115200**.

**Điểm mới của bản này:**

- Gửi data: `POST /api/data` kèm header **`X-Api-Key`** (sai key → 401).
- Mỗi chu kỳ gửi data (5s) ESP32 gọi tiếp **`GET /api/command`** → nếu `manual_alarm: true` thì **ép trạng thái ALARM** (còi nhấp nháy + bơm + quạt) cho tới khi web **NGỪNG/CHẶN**.
- Vẫn giữ test cục bộ: gõ `t` trong Serial Monitor.



## 8. Code server Python — `server/app.py`

```text
cd server
pip install -r requirements.txt        # flask + requests
python app.py                          # → http://127.0.0.1:5000 (login admin/admin123)
```

Cấu trúc bảng SQLite (`fire_alarm.db`, tự tạo):

| Bảng | Vai trò |
|---|---|
| `readings` | Dữ liệu cảm biến theo thời gian (nguồn JSON) |
| `devices` | Multi-device: `device_id`, `api_key`, `active`, `last_seen` |
| `users` | Tài khoản đăng nhập (mật khẩu băm) |
| `app_state` | Trạng thái toggle (vd. `manual_alarm`) |
| `events` | Nhật ký hoạt động (audit) |


## 9. Web dashboard — `server/templates/`

### 9.1 `index.html` (cần đăng nhập)

- **JSON realtime từ server** (không hard-code): `/api/latest` 3s, `/api/state` 3s, `/api/history` 10s, `/api/stats` + `/api/events` 15s (fetch tự redirect `/login` khi 401).
- **Thanh điều khiển báo cháy thủ công** (ngay dưới banner):

| Nút | Chức năng |
|---|---|
| 🚨 **BẬT BÁO CHÁY THỦ CÔNG** | Hỏi xác nhận → `POST /api/manual {"action":"on"}` → banner đỏ nhấp nháy; ESP32 nhận lệnh qua `/api/command` và kích còi/bơm |
| ⏹ **NGỪNG / CHẶN (ACK)** | Hỏi xác nhận → `POST /api/manual {"action":"ack"}` → tắt kích hoạt; 2 nút state-driven (nút đang bật bị disable) |
| 📤 **Báo cáo Telegram** | `POST /api/report` → gửi ngay file **CSV hôm nay** qua `sendDocument` |
| 🔔 Bật chuông / Đăng xuất | Âm báo web (WebAudio), đăng xuất session |

- **Panel 📡 Thiết bị (multi-device):** thêm (hiện `device_id`+`api_key` để chèn `.ino`), bật/tắt, sinh lại key, xoá — cột *Seen gần nhất*.
- **Panel 📜 Nhật ký hoạt động:** mọi thao tác quan trọng kèm người thực hiện.
- Biểu đồ canvas nhiệt/độ ẩm + khói/lửa, thẻ 4 cảm biến, thống kê hôm nay, bảng 10 JSON mới nhất.



## 10. Tích hợp TELEGRAM (sendMessage + `sendDocument -F`)

**Đúng cơ chế bạn nêu** — mỗi lần gửi file, server POST tới URL:

```text
https://api.telegram.org/bot$BOT_TOKEN/sendDocument?chat_id=$CHAT_ID
```

với body là **multipart/form-data** — tương đương hệt lệnh curl:

```bash
curl -F "document=@baocao-homnay.csv" \
     "https://api.telegram.org/bot$BOT_TOKEN/sendDocument?chat_id=$CHAT_ID"
```

Trong Python (xem `app.py` — hàm `tg_send_document`):

```python
r = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendDocument?chat_id={CHAT_ID}",
    files={"document": (ten_file, f)},   # ← tương đương -F "document=@file"
    data={"caption": chu_thich},
    timeout=30,
)
```

**Cơ chế edge-triggered (không spam):** server lưu mức hiện tại của từng tín hiệu cho *mỗi thiết bị* trong bảng `alert_flags`. Mỗi POST (5s) chỉ gửi tin khi mức **vừa thay đổi**; cùng mức thì không gửi lại. Khi tín hiệu về 0 → tin "đã trở về bình thường". Cờ lưu trong SQLite nên restart server **không gửi lại**.

**Ngưỡng phía server** (hằng trong `app.py`, **bắt buộc đồng bộ** với `FLAME_THRESHOLD/SMOKE_*/TEMP_*` trong `.ino`):

| Tín hiệu | Mức ⚠️ CẢNH BÁO | Mức 🚨 NGUY HIỂM |
|---|---|---|
| 🔥 Lửa (giá trị nhận) | — | ≥ **1500** (bản D0 gửi 4095) |
| 💨 Khói/gas MQ2 (ADC) | ≥ **1800** | ≥ **2800** |
| 🌡️ Nhiệt độ DHT11 (°C) | ≥ **40** | ≥ **45** |

**Các sự kiện kích hoạt (chỉ chạy khi đã set token + chat_id):**

| Sự kiện | Nội dung gửi |
|---|---|
| **🔥 Lửa** vừa vượt 1500 | `sendMessage` **"PHÁT HIỆN CÓ LỬA!"** (giá trị + ngưỡng) |
| **💨 Khói/gas** vừa vượt **1800** | `sendMessage` **"CẢNH BÁO: nồng độ khói/gas bất thường"** |
| **💨 Khói/gas** vừa vượt **2800** | `sendMessage` **"PHÁT HIỆN KHÍ GAS/KHÓI CAO BẤT THƯỜNG!"** |
| **🌡️ Nhiệt độ** vừa vượt **40°C** | `sendMessage` **"CẢNH BÁO: nhiệt độ đang tăng cao"** |
| **🌡️ Nhiệt độ** vừa vượt **45°C** | `sendMessage` **"NHIỆT ĐỘ VƯỢT NGƯỠNG NGUY HIỂM!"** |
| Tín hiệu **vừa về bình thường** | `sendMessage` **"✅ Lửa / Khói-gas / Nhiệt độ đã trở về bình thường"** |
| Tín hiệu **giảm mức** | `sendMessage` **"⬇ ... đã giảm xuống mức cảnh báo"** |
| **Chuyển sang ALARM** (lần đầu) | `sendDocument` file **JSON** hiện trạng |
| **Báo cáo định kỳ** (mặc định 3600s, sửa `TELEGRAM_REPORT_SEC`) | `sendDocument` file **CSV** toàn bộ mẫu trong ngày (9 cột) |
| Bấm **BÁO CHÁY THỦ CÔNG** | `sendMessage` ⚠️ kèm tên người dùng + thời gian |
| Bấm **NGỪNG/CHẶN (ACK)** | `sendMessage` ✅ kèm tên người dùng + thời gian |
| Bấm **📤 Báo cáo Telegram** | `sendDocument` CSV ngay lập tức (`POST /api/report`) |

Log server: `[TELEGRAM] sendDocument xxx.csv -> 200`.
**Đã kiểm chứng (mock):** URL sinh ra đúng mẫu curl, body đúng multipart, file CSV/JSON đúng tên.
## 11. BÁO CHÁY THỦ CÔNG + NGỪNG/CHẶN (ACK) — dòng chạy

```
Web: [ 🚨 BẬT BÁO CHÁY THỦ CÔNG ]       Web: [ ⏹ NGỪNG / CHẶN (ACK) ]
  | confirm() -> POST /api/manual          | confirm() -> POST /api/manual
  | {action:"on"}  (cookie/token)          | {action:"ack"} (cookie/token)
  v                                         v
app_state.manual_alarm = 1            app_state.manual_alarm = 0
  | + ghi events + Telegram                   | + ghi events + Telegram
  v                                            |
ESP32 moi 5s: GET /api/command (X-Api-Key)    |
  -> {"manual_alarm": true} -> ep ALARM       |-> {"manual_alarm": false} -> ve binh thuong
    coi keu, bom+quat chay, banner do  <-------+
```
## 12. Dữ liệu JSON của server

**`POST /api/data`** (ESP32 → server, header `X-Api-Key`):

```json
{
  "device_id": "esp32-fire-01",
  "temperature": 35.5,
  "humidity": 62.0,
  "flame": 4095,
  "smoke": 2400,
  "flame_detected": true,
  "alarm": false,
  "state": "WARNING"
}
```
→ `201 {"id":1,"manual_alarm":false,"status":"ok"}` · thiếu trường → `400` · sai key → `401`

**`GET /api/latest`** (server → web, sau đăng nhập):

```json
{"data": {"id": 2, "device_id": "esp32-fire-01", "ts": "2026-10-17T16:16:06",
  "temperature": 47.2, "humidity": 55.1, "flame": 4095, "smoke": 3100,
  "flame_detected": 1, "alarm": 1, "state": "ALARM"}}
```

**`GET /api/command`** (server → ESP32):

```json
{"manual_alarm": true, "server_time": "2026-10-17T18:10:34"}
```

Các endpoint còn lại (`/api/history`, `/api/state`, `/api/stats`, `/api/devices`, `/api/events`, `POST /api/manual`) đều nhận/trả **JSON** — đây chính là "data của server dạng JSON".
## 13. ỨNG DỤNG ĐIỆN THOẠI — Capacitor (iOS) + GitHub Actions

App **riêng** (khác dashboard của server): đăng nhập lấy `app_token` rồi gọi API theo header `X-App-Token` (xem mục 5.3), UI tối ưu mobile, kèm nút **BÁO CHÁY THỦ CÔNG / NGỪNG (ACK)**.

### 13.1 Cấu trúc

```text
mobile_app/
+- package.json           : @capacitor/core + cli + ios (da npm install)
+- capacitor.config.json  : appId com.doan.baochay, webDir www
+- ios/                   : platform iOS (da sinh bang `npx cap add ios`)
+- www/index.html         : TOAN BO app: HTML+CSS+JS, khong can build
.github/workflows/
+- build-ios.yml          : GitHub Actions build tren runner macOS
```

**Tính năng:** màn đăng nhập (`POST /api/login` → token lưu `localStorage`), banner trạng thái, 4 thẻ cảm biến (nhiệt/độ ẩm/lửa/khói), **nút ON/ACK**, thống kê hôm nay, 10 mẫu mới nhất, màn cài đặt (đổi `BASE`, xem token + nút **Sao chép token**), poll 3 giây, **safe-area** cho tai thỏ iPhone, modal **Sao chép API key** (thay cho `alert()` copy không được trên điện thoại).

### 13.2 Chạy thử ngay trên máy (không cần Xcode)

```text
# 1. chay server
cd server && python app.py
# 2. serve app
cd mobile_app\www
python -m http.server 8080
# 3. mo trang + dang nhap
#    BASE: http://127.0.0.1:5000  |  admin / admin123
```

### 13.3 Build app iOS

**Windows không build được iOS** (cần macOS + Xcode) → 2 cách:

1. **GitHub Actions (đã cấu hình sẵn):** push repo lên GitHub → tab **Actions** → run workflow **Build iOS (Capacitor)** → tải artifact `BaoChay-iOS-unsigned.ipa`. Workflow tự `npm ci` → `npx cap sync ios` → `xcodebuild` (unsign) → đóng gói `.ipa`.
2. **Trên Mac:** `cd mobile_app && npm ci && npx cap open ios` → Run trong Xcode.



Chu kỳ NORMAL → WARNING → ALARM giả lập để test web + Telegram báo cháy.


## 15. Hướng dẫn chạy từ đầu (A → Z)

1. **Server:** `cd server` → `pip install -r requirements.txt` → (tuỳ chọn) `setx TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` → `python app.py`.
2. **Đăng nhập web:** `http://127.0.0.1:5000` → `admin/admin123` (đổi sau).
3. **Lấy API key** từ console (`[SETUP] ... API key`) hoặc web ＋ Thêm thiết bị → chèn vào `.ino`.
4. **Test không cần phần cứng:** `set ESP32_API_KEY=<key>` → `python simulate.py` → web hiện dữ liệu; vào pha ALARM sẽ thấy log `[TELEGRAM]` (nếu đã cấu hình).
5. **Nạp ESP32:** cài thư viện (mục 7) → sửa WiFi + `API_KEY` + IP server (mục 6.1) → nạp → Serial 115200:
   - `[WiFi] connected, IP: ...`
   - `lua=120 khoi=700 t=30.5C h=65.0% state=NORMAL`
   - `[HTTP] gui len server OK` — nếu `401` là API key sai/chưa chèn
   - `[CMD] Web rang buoc BAO CHAY THU CONG` khi bấm nút trên web
6. **Thử logic:** đèn lửa soi cảm biến hoặc nhấn `t` (test cục bộ) → web đỏ + Telegram; dùng **nút thủ công** trên web → ESP32 vẫn báo dù cảm biến bình thường → **ACK** để tắt.
7. **Hiệu chỉnh ngưỡng** theo giá trị ADC thực tế (`FLAME_THRESHOLD`, `SMOKE_WARN`, `SMOKE_ALARM`).

## 16. Sự cố thường gặp

| Vấn đề | Cách xử lý |
|---|---|
| Web đá về `/login` | Chưa đăng nhập / session hết hạn → đăng nhập lại |
| ESP32 bị `401 X-Api-Key khong hop le` | Sai/chưa chèn `API_KEY`, hoặc device đang bị **TẮT** (web → Thiết bị → Bật/tắt) |
| API web trả `401` khi test bằng curl | API web yêu cầu session — đăng nhập trước lấy cookie: `curl -c c.txt -d "username=admin&password=admin123" http://IP:5000/login` rồi `curl -b c.txt ...` |
| Telegram không gửi | Chưa `setx TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID` (setx phải mởTerminal mới); xem log `[TELEGRAM]` |
| LCD hiện chữ mờ | I2C Scanner → nếu `0x3F` sửa `LiquidCrystal_I2C lcd(0x3F,16,2)` |
| Relay không kích | Đổi `RELAY_ACTIVE_LOW`; chung GND; nguồn JD-VCC |
| DHT11 trả NaN | Dây/điện trở 10k; interval đọc ≥2s (code đã làm) |
| MQ2 trôi giá trị | Preheat 20–60s (lần đầu 24h); set ngưỡng theo chênh lệch nền |
| GPIO 34–39 | Chỉ đọc được — dùng `digitalRead` (flame D0) / `analogRead` (MQ2) đúng chỗ |
| Lửa luôn 0 hoặc luôn 4095 | Module 3 chân đọc D0 → đổi chiều `FLAME_D0_ACTIVE_HIGH` trong `.ino` |
| Port 5000 bị chiếm | Đóng tiến trình python server cũ |
| Manual báo cáo Telegram trả 503 | Chưa cấu hình token/chat_id (mục 6.2) |


