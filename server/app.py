"""
DO AN TOT NGHIEP - SERVER BAO CHAY (Python + Flask)
- Nhan du lieu JSON tu ESP32 (bao mat bang X-Api-Key), tra ve cho web dang JSON
- Xac thuc dang nhap (Flask session) + quan ly nhieu thiet bi (multi-device)
- Bao chay thu cong (manual) + Ngung/Chan (acknowledge) tai web
- Gui Telegram qua sendDocument (multipart -F) + sendMessage

Chay:
    pip install -r requirements.txt
    python app.py           ->  http://127.0.0.1:5000
Bien moi truong tuy chon:
    ADMIN_USER / ADMIN_PASS     tai khoan quan tri (mac dinh admin/admin123)
    APP_TOKEN                   token cho app mobile (mac dinh: server tu sinh)
    TELEGRAM_BOT_TOKEN          bot token
    TELEGRAM_CHAT_ID            chat id
    TELEGRAM_REPORT_SEC         chu ky bao cao CSV (mac dinh 3600s)
"""

import csv
import json
import os
import secrets
import sqlite3
import tempfile
import threading
import time
from datetime import datetime
from functools import wraps

import requests
from flask import (
    Flask, request, jsonify, render_template,
    redirect, session, url_for,
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "fire_alarm.db")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
REPORT_INTERVAL = int(os.environ.get("TELEGRAM_REPORT_SEC", "3600"))

# Nguong CHAN SERVER cho tin nhan Telegram - dong bo voi file .ino
FLAME_THRESHOLD = 1500                 # lua: ADC tren 1500 la co lua
SMOKE_WARN, SMOKE_ALARM = 1800, 2800   # khoi/gas: 1800 canh bao, 2800 nguy hiem
TEMP_WARN, TEMP_ALARM = 40.0, 45.0     # nhiet do: 40 canh bao, 45 nguy hiem

app = Flask(__name__)
# dat FLASK_SECRET khi san xuat; mac dinh co dinh de session con sau khi restart
app.secret_key = os.environ.get("FLASK_SECRET",
                                "doan-baochay-fixed-secret-change-in-prod")


# --------------------------------------------------------------- Database
def get_db():
    # timeout=10: cho thay vi bao loi neu co request khac dang ghi cung luc
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS readings (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id      TEXT    NOT NULL,
                ts             TEXT    NOT NULL,
                temperature    REAL,
                humidity       REAL,
                flame          INTEGER,
                smoke          INTEGER,
                flame_detected INTEGER,
                alarm          INTEGER,
                state          TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ts ON readings (ts);

            CREATE TABLE IF NOT EXISTS devices (
                device_id  TEXT PRIMARY KEY,
                name       TEXT,
                api_key    TEXT NOT NULL UNIQUE,
                active     INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                last_seen  TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_state (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                ts     TEXT,
                actor  TEXT,
                action TEXT,
                detail TEXT
            );

                        CREATE TABLE IF NOT EXISTS alert_flags (
                            device_id TEXT,
                            signal    TEXT,
                            level     INTEGER NOT NULL DEFAULT 0,
                            PRIMARY KEY (device_id, signal)
                        );
                        """
                    )
        if conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
            conn.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (ADMIN_USER, generate_password_hash(ADMIN_PASS)),
            )
        if conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"] == 0:
            key = secrets.token_hex(16)
            conn.execute(
                "INSERT INTO devices (device_id, name, api_key, active, created_at)"
                " VALUES (?, ?, ?, 1, ?)",
                ("esp32-fire-01", "ESP32 chinh", key, now_str()),
            )
            print("[SETUP] Device mac dinh 'esp32-fire-01' voi API key:")
            print(f"        {key}")
            print("        -> chen vao API_KEY trong file .ino truoc khi nap!")
        if conn.execute("SELECT COUNT(*) c FROM app_state").fetchone()["c"] == 0:
            conn.execute("INSERT INTO app_state (key, value) VALUES ('manual_alarm','0')")
        conn.commit()


def now_str():
    return datetime.now().isoformat(timespec="seconds")


def get_state(key, default="0"):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key, value):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        conn.commit()


def log_event(actor, action, detail=""):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO events (ts, actor, action, detail) VALUES (?, ?, ?, ?)",
            (now_str(), actor, action, detail),
        )
        conn.commit()


def get_app_token():
    """Token cho app mobile: lay tu bien APP_TOKEN, neu khong thi sinh
    mot lan va luu vao app_state (in ra console trong Main)."""
    tok = os.environ.get("APP_TOKEN", "")
    if tok:
        return tok
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM app_state WHERE key='mobile_token'"
        ).fetchone()
        if row:
            return row["value"]
    tok = secrets.token_hex(20)
    set_state("mobile_token", tok)
    return tok


# --------------------------------------------------------------- Bao mat
def current_actor():
    """Nguoi thuc hien: ten dang nhap (cookie) hoac 'app-token' (X-App-Token)."""
    return session.get("user") or "app-token"

def has_api_access():
    """API /api/* dung cookie session (web) HOAC header X-App-Token (app mobile)."""
    if session.get("user"):
        return True
    tok = request.headers.get("X-App-Token") or request.args.get("token", "")
    want = get_app_token()
    return bool(tok) and bool(want) and secrets.compare_digest(str(tok), want)


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.path.startswith("/api/"):
            if not has_api_access():
                return jsonify(error="chua dang nhap (can cookie hoac X-App-Token)"), 401
        elif not session.get("user"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def auth_device():
    """Kiem tra X-Api-Key -> tra row device, NULL neu khong hop le."""
    key = request.headers.get("X-Api-Key") or request.args.get("api_key") or ""
    if not key:
        return None
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM devices WHERE api_key=? AND active=1", (key,)
        ).fetchone()


# --------------------------------------------------------------- Telegram
def tg_url(method, **params):
    """URL kieu chinh Telegram, giong vi du curl:
       https://api.telegram.org/bot$BOT_TOKEN/sendDocument?chat_id=$CHAT_ID
    """
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://api.telegram.org/bot{TOKEN}/{method}?{qs}"


def tg_send_message(text):
    if not (TOKEN and CHAT_ID):
        print("[TELEGRAM] chua dat TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return False
    try:
        r = requests.post(
            tg_url("sendMessage", chat_id=CHAT_ID),
            json={"text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        print(f"[TELEGRAM] sendMessage -> {r.status_code}")
        return r.ok
    except Exception as e:
        print(f"[TELEGRAM] loi sendMessage: {e}")
        return False


def tg_send_document(filepath, caption=""):
    """Gui file dung chinh multipart -F giong curl:
       curl -F "document=@file" ".../sendDocument?chat_id=$CHAT_ID"
    """
    if not (TOKEN and CHAT_ID):
        return False
    try:
        with open(filepath, "rb") as f:
            r = requests.post(
                tg_url("sendDocument", chat_id=CHAT_ID),
                files={"document": (os.path.basename(filepath), f)},
                data={"caption": caption},
                timeout=30,
            )
        print(f"[TELEGRAM] sendDocument {os.path.basename(filepath)} "
              f"-> {r.status_code}")
        return r.ok
    except Exception as e:
        print(f"[TELEGRAM] loi sendDocument: {e}")
        return False


def export_json_file(rows, title="bao-cao"):
    fd, path = tempfile.mkstemp(suffix=".json", prefix=title + "-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump([dict(r) for r in rows], f, ensure_ascii=False, indent=2)
    return path


def export_csv_file(rows):
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="baocao-homnay-")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["thoi_gian", "thiet_bi", "nhiet_do", "do_am",
                    "lua_adc", "khoi_adc", "co_lua", "bao_chay", "trang_thai"])
        for r in rows:
            w.writerow([r["ts"], r["device_id"], r["temperature"], r["humidity"],
                        r["flame"], r["smoke"], r["flame_detected"],
                        r["alarm"], r["state"]])
    return path


def telegram_alarm_document(payload):
    """Khi MOI chuyen sang ALARM: gui file JSON hien tai (tin van de da
    do tong hop o check_signal_alerts)."""
    try:
        path = export_json_file([payload], title="baochay")
        tg_send_document(
            path,
            caption=f"Du lieu ngay luc bao chay - {payload.get('device_id')} "
                    f"({payload.get('state')})",
        )
        os.remove(path)
    except Exception as e:
            print(f"[TELEGRAM] loi bao cao bao chay: {e}")


    # ------------------- CANH BAO THEO tung tin hieu -------------------
def signal_levels(temp, flame, smoke):
    """Xep cap cho tung tin hieu: 0 = binh thuong, 1 = canh bao, 2 = nguy hiem."""
    return {
        "flame": 2 if flame >= FLAME_THRESHOLD else 0,
        "gas": 2 if smoke >= SMOKE_ALARM else (1 if smoke >= SMOKE_WARN else 0),
        "temp": 2 if temp >= TEMP_ALARM else (1 if temp >= TEMP_WARN else 0),
    }


def build_signal_message(device_id, sig, old_level, new_level, value):
    """Tin nhan rieng cho tung tin hieu; chi tao khi cap thay doi."""
    now = now_str()
    names = {"flame": "Lửa", "gas": "Khói/gas", "temp": "Nhiệt độ"}
    if new_level == 0 and old_level > 0:
        return (f"\u2705 <b>{names[sig]} đã trở về bình thường</b>\n"
                f"Thiết bị: {device_id}\nGiá trị hiện tại: {value}\n"
                f"Thời gian: {now}")

    if sig == "flame" and new_level == 2:
        return (f"\U0001f525 <b>PHÁT HIỆN CÓ LỬA!</b>\n"
                f"Thiết bị: {device_id}\n"
                f"Cảm biến lửa (ADC): {value} — ngưỡng {FLAME_THRESHOLD}\n"
                f"Thời gian: {now}")

    if sig == "gas":
        if new_level == 1:
            return (f"\U0001f4a8 <b>CẢNH BÁO: nồng độ khói/gas bất thường</b>\n"
                    f"Thiết bị: {device_id}\n"
                    f"MQ2 (ADC): {value} — mức báo {SMOKE_WARN}\n"
                    f"Thời gian: {now}")
        if new_level == 2:
            return (f"\U0001f6a8 <b>PHÁT HIỆN KHÍ GAS/KHÓI CAO BẤT THƯỜNG!</b>\n"
                    f"Thiết bị: {device_id}\n"
                    f"MQ2 (ADC): {value} — ngưỡng nguy hiểm {SMOKE_ALARM}\n"
                    f"Thời gian: {now}")

    if sig == "temp":
        if new_level == 1:
            return (f"\U0001f321️ <b>CẢNH BÁO: nhiệt độ đang tăng cao</b>\n"
                    f"Thiết bị: {device_id}\n"
                    f"Nhiệt độ: {value} °C — ngưỡng cảnh báo {TEMP_WARN} °C\n"
                    f"Thời gian: {now}")
        if new_level == 2:
            return (f"\U0001f6a8 <b>NHIỆT ĐỘ VƯỢT NGƯỠNG NGUY HIỂM!</b>\n"
                    f"Thiết bị: {device_id}\n"
                    f"Nhiệt độ: {value} °C — ngưỡng {TEMP_ALARM} °C\n"
                    f"Thời gian: {now}")

    if new_level < old_level and new_level > 0:
        return (f"\U0001f4e8 <b>{names[sig]} đã giảm xuống mức cảnh báo</b>\n"
                f"Thiết bị: {device_id} · Giá trị: {value}\n"
                f"Thời gian: {now}")
    return None


def check_signal_alerts(device_id, temp, flame, smoke):
    """So sanh tin hieu voi lan truoc; gui Telegram chi khi cap vua thay doi
    edge-triggered -> khong spam 5s/moi lan POST."""
    levels = signal_levels(temp, flame, smoke)
    values = {"flame": flame, "gas": smoke, "temp": temp}
    changed = []
    try:
        with get_db() as conn:
            for sig, lv in levels.items():
                row = conn.execute(
                    "SELECT level FROM alert_flags WHERE device_id=? AND signal=?",
                    (device_id, sig),
                ).fetchone()
                old = row["level"] if row else 0
                if lv == old:
                    continue
                conn.execute(
                    "INSERT INTO alert_flags (device_id, signal, level)"
                    " VALUES (?, ?, ?)"
                    " ON CONFLICT(device_id, signal) DO UPDATE SET level=excluded.level",
                    (device_id, sig, lv),
                )
                changed.append((sig, old, lv))
            conn.commit()
    except Exception as e:
        print(f"[TELEGRAM] loi ghi alert_flags: {e}")
        return

    for sig, old, lv in changed:
        msg = build_signal_message(device_id, sig, old, lv, values[sig])
        if msg:
            threading.Thread(target=tg_send_message, args=(msg,),
                             daemon=True).start()


def telegram_daily_report():
    """Gui bao cao CSV hom nay (tat ca mau cua cac thiet bi)."""
    try:
        today = datetime.now().date().isoformat()
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM readings WHERE ts >= ? ORDER BY id", (today,)
            ).fetchall()
        if not rows:
            print("[TELEGRAM] khong co du lieu de bao cao")
            return False
        path = export_csv_file(rows)
        ok = tg_send_document(path, caption=f"Bao cao bao chay {today} - {len(rows)} mau")
        os.remove(path)
        return ok
    except Exception as e:
        print(f"[TELEGRAM] loi bao cao: {e}")
        return False


def report_scheduler():
    """Chay nen: gui bao cao CSV dinh ky len Telegram."""
    while True:
        time.sleep(REPORT_INTERVAL)
        if TOKEN and CHAT_ID:
            telegram_daily_report()


# --------------------------------------------------------------- Auth web
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        with get_db() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        if row and check_password_hash(row["password"], p):
            session["user"] = u
            log_event(u, "dang_nhap", request.remote_addr or "")
            return redirect("/")
        error = "Sai ten dang nhap hoac mat khau"
    return render_template("login.html", error=error)


@app.get("/logout")
def logout():
    if session.get("user"):
        log_event(current_actor(), "dang_xuat", "")
    session.clear()
    return redirect(url_for("login"))


@app.post("/api/login")
def api_login():
    """Dang nhap JSON cho app mobile -> tra app_token (dung header X-App-Token)."""
    data = request.get_json(silent=True) or {}
    u = data.get("username", "")
    p = data.get("password", "")
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
    if row and check_password_hash(row["password"], p):
        log_event(u, "dang_nhap_tu_app", request.remote_addr or "")
        return jsonify(status="ok", user=u, app_token=get_app_token())
    return jsonify(error="ten dang nhap hoac mat khau sai"), 401


# --------------------------------------------------------------- Web page
@app.get("/")
@login_required
def index():
    return render_template("index.html", user=session["user"])


# -------------------------------------------- API web (can dang nhap)
@app.get("/api/latest")
@login_required
def latest():
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM readings ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return jsonify(error="chua co du lieu"), 404
    return jsonify(data=dict(row))


@app.get("/api/history")
@login_required
def history():
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 1000))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM (SELECT * FROM readings ORDER BY id DESC LIMIT ?)"
            " ORDER BY id ASC",
            (limit,),
        ).fetchall()
    return jsonify(data=[dict(r) for r in rows], count=len(rows))


@app.get("/api/state")
@login_required
def app_state_api():
    """Trang thai he thong cho web: bao chay thu cong, danh sach thiet bi..."""
    with get_db() as conn:
        devs = conn.execute(
                    "SELECT device_id, name, api_key, active, last_seen FROM devices"
                    " ORDER BY created_at"
                ).fetchall()
        last = conn.execute(
            "SELECT alarm, device_id, ts FROM readings ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return jsonify(
        manual_alarm=get_state("manual_alarm") == "1",
        device_alarm=bool(last["alarm"]) if last else False,
        last_device=dict(last) if last else None,
        devices=[dict(d) for d in devs],
    )


@app.get("/api/stats")
@login_required
def stats():
    today = datetime.now().date().isoformat()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)         AS samples,
                   MIN(temperature) AS min_temp,
                   MAX(temperature) AS max_temp,
                   AVG(temperature) AS avg_temp,
                   MAX(smoke)       AS max_smoke,
                   MAX(flame)       AS max_flame,
                   SUM(alarm)       AS alarm_count
            FROM readings WHERE ts >= ?
            """,
            (today,),
        ).fetchone()
    return jsonify(data=dict(row), date=today)


@app.get("/api/events")
@login_required
def events_list():
    try:
        limit = int(request.args.get("limit", 30))
    except ValueError:
        limit = 30
    limit = max(1, min(limit, 200))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return jsonify(data=[dict(r) for r in rows])


# ------------------------------------------------ Multi-device management
@app.get("/api/devices")
@login_required
def devices_list():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM readings r"
            " WHERE r.device_id = d.device_id) AS samples"
            " FROM devices d ORDER BY d.created_at"
        ).fetchall()
    return jsonify(data=[dict(r) for r in rows])


@app.post("/api/devices")
@login_required
def devices_add():
    """Them thiet bi -> sinh API key cho ESP32 moi."""
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    if not name:
        return jsonify(error="thieu ten thiet bi"), 400
    device_id = "esp32-" + secrets.token_hex(4)
    api_key = secrets.token_hex(16)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO devices (device_id, name, api_key, active, created_at)"
            " VALUES (?, ?, ?, 1, ?)",
            (device_id, name, api_key, now_str()),
        )
        conn.commit()
    log_event(current_actor(), "them_thiet_bi", f"{device_id} ({name})")
    return jsonify(data={"device_id": device_id, "api_key": api_key}), 201


@app.post("/api/devices/<device_id>/toggle")
@login_required
def devices_toggle(device_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE device_id=?", (device_id,)
        ).fetchone()
        if not row:
            return jsonify(error="khong tim thay"), 404
        new_val = 0 if row["active"] else 1
        conn.execute(
            "UPDATE devices SET active=? WHERE device_id=?", (new_val, device_id)
        )
        conn.commit()
    log_event(current_actor(), "bat_tat_thiet_bi",
              f"{device_id} -> {'bat' if new_val else 'tat'}")
    return jsonify(status="ok", active=new_val)


@app.post("/api/devices/<device_id>/regen")
@login_required
def devices_regen(device_id):
    """Sinh lai API key (khi nghi bi ro ri)."""
    api_key = secrets.token_hex(16)
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE devices SET api_key=? WHERE device_id=?", (api_key, device_id)
        )
        conn.commit()
    if cur.rowcount == 0:
        return jsonify(error="khong tim thay"), 404
    log_event(current_actor(), "sinh_lai_api_key", device_id)
    return jsonify(data={"api_key": api_key})


@app.post("/api/devices/<device_id>/delete")
@login_required
def devices_delete(device_id):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
        conn.commit()
    if cur.rowcount == 0:
        return jsonify(error="khong tim thay"), 404
    log_event(current_actor(), "xoa_thiet_bi", device_id)
    return jsonify(status="ok")


# --------------------------------- Bao chay thu cong / Ngung-Chan (ACK)
@app.post("/api/manual")
@login_required
def manual_alarm():
    """action = 'on' -> bat bao chay thu cong; 'ack' -> ngung/chan."""
    action = (request.get_json(silent=True) or {}).get("action", "")
    if action == "on":
        set_state("manual_alarm", "1")
        log_event(current_actor(), "bao_chay_thu_cong", request.remote_addr or "")
        tg_send_message(
                    f"⚠️ <b>BÁO CHÁY THỦ CÔNG</b> — do {current_actor()} kích hoạt "
                    f"lúc {now_str()}"
                )
        return jsonify(manual_alarm=True, status="on")
    if action == "ack":
        set_state("manual_alarm", "0")
        log_event(current_actor(), "ngung_kich_hoat_ack", request.remote_addr or "")
        tg_send_message(
                    f"✅ <b>Đã NGỪNG/CHẶN báo cháy</b> — do {current_actor()} "
                    f"lúc {now_str()}"
                )
        return jsonify(manual_alarm=False, status="ack")
    return jsonify(error="action phai la 'on' hoac 'ack'"), 400


@app.post("/api/report")
@login_required
def report_now():
    """Gui bao cao CSV hom nay len Telegram ngay (nut tay tai web)."""
    if not (TOKEN and CHAT_ID):
        return jsonify(error="chua cau hinh TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID",
                       hint="dat bien moi truong roi restart server"), 503
    ok = telegram_daily_report()
    log_event(current_actor(), "gui_bao_cao_telegram",
              "thanh cong" if ok else "that bai")
    return (jsonify(status="ok"), 200) if ok else (jsonify(status="that_bai"), 502)


# ------------------------------------------ API ESP32 (can X-Api-Key)
@app.post("/api/data")
def receive_data():
    dev = auth_device()
    if dev is None:
        return jsonify(error="X-Api-Key khong hop le"), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="khong nhan duoc JSON"), 400
    required = ("temperature", "humidity", "flame", "smoke")
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify(error="thieu truong: " + ", ".join(missing)), 400
    try:
        temperature = float(data["temperature"])
        humidity = float(data["humidity"])
        flame = int(data["flame"])
        smoke = int(data["smoke"])
    except (TypeError, ValueError):
        return jsonify(error="gia tri khong hop le"), 400

    ts = data.get("timestamp") or now_str()
    alarm = 1 if data.get("alarm") else 0
    payload = {
        "device_id": dev["device_id"], "timestamp": ts,
        "temperature": temperature, "humidity": humidity,
        "flame": flame, "smoke": smoke,
        "flame_detected": bool(data.get("flame_detected")),
        "alarm": alarm, "state": data.get("state", "NORMAL"),
    }

    with get_db() as conn:
        prev = conn.execute(
            "SELECT alarm FROM readings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        cur = conn.execute(
            """
            INSERT INTO readings
                (device_id, ts, temperature, humidity, flame, smoke,
                 flame_detected, alarm, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (dev["device_id"], ts, temperature, humidity, flame, smoke,
             1 if payload["flame_detected"] else 0, alarm, payload["state"]),
        )
        conn.execute(
            "UPDATE devices SET last_seen=? WHERE device_id=?",
            (now_str(), dev["device_id"]),
        )
        row_id = cur.lastrowid

    if alarm and (not prev or not prev["alarm"]):
        threading.Thread(target=telegram_alarm_document,
                         args=(payload,), daemon=True).start()

    check_signal_alerts(dev["device_id"], temperature, flame, smoke)

    return jsonify(status="ok", id=row_id,
                   manual_alarm=get_state("manual_alarm") == "1"), 201


@app.get("/api/command")
def command():
    """ESP32 doc lenh: co dang bat bao chay thu cong tren web khong."""
    dev = auth_device()
    if dev is None:
        return jsonify(error="X-Api-Key khong hop le"), 401
    return jsonify(
        manual_alarm=get_state("manual_alarm") == "1",
        server_time=now_str(),
    )


# ---------------------------------------------------- CORS (app mobile khac domain)
@app.after_request
def add_cors(response):
    """Mo CORS cho /api/* de web app/ung dung web tren dien thoai goi duoc."""
    if request.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, X-Api-Key, X-App-Token, X-Requested-With"
        )
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# --------------------------------------------------------------- MAIN
if __name__ == "__main__":
    init_db()
    print(f"Server bao chay tai http://127.0.0.1:5000 "
          f"(dang nhap: {ADMIN_USER}/{ADMIN_PASS})")
    print(f"Mobile app token (POST /api/login hoac header X-App-Token): "
          f"{get_app_token()}")
    if TOKEN and CHAT_ID:
        print("Telegram: DANG BAT (bao chay + bao cao dinh ky)")
    else:
        print("Telegram: TAT - dat TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID de bat")
    threading.Thread(target=report_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)