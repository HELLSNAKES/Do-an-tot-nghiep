"""
MO PHONG ESP32 - gui du lieu gia lap len server de thu web
khong can n code cho phan cung.

Chay (server phai dang chay truoc):
    set ESP32_API_KEY=<key doc tren console server>
    python simulate.py
Nhan Ctrl+C de dung.
"""

import json
import math
import os
import time
import urllib.request
from datetime import datetime

SERVER = "http://127.0.0.1:5000/api/data"
DEVICE_ID = "simulator-01"
INTERVAL = 2  # giay
# lay API key tu server (doan [SETUP]... hoac web -> Them thiet bi)
API_KEY = os.environ.get("ESP32_API_KEY", "DAN_API_KEY_VAO_DAY")


def post(payload):
    req = urllib.request.Request(
        SERVER,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "X-Api-Key": API_KEY},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as res:
        return res.status


def main():
    print(f"Mo phong dang gui du lieu moi {INTERVAL}s len {SERVER}")
    i = 0
    while True:
        i += 1
        # vong lap 25 mau: binh thuong -> canh bao -> bao chay
        phase = i % 25
        if phase <= 10:
            state, temp, smoke, flame, alarm = "NORMAL", 30 + i * 0.2, 700, 120, False
        elif phase <= 15:
            state, temp, smoke, flame, alarm = "WARNING", 42, 2100, 600, False
        else:
            state, temp, smoke, flame, alarm = "ALARM", 47, 3100, 3600, True

        payload = {
            "device_id": DEVICE_ID,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "temperature": round(temp + math.sin(i / 3), 1),
            "humidity": round(65 - math.sin(i / 4) * 8, 1),
            "flame": flame,
            "smoke": smoke,
            "flame_detected": flame >= 1500,
            "alarm": alarm,
            "state": state,
        }
        try:
            status = post(payload)
            print(f"[{payload['timestamp']}] {state:7s} "
                  f"T={payload['temperature']:5.1f}C khoi={smoke} "
                  f"lua={flame} -> HTTP {status}")
        except Exception as e:
            print(f"Loi ket noi server: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDa dung mo phong.")