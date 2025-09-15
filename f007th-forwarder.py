#!/usr/bin/env python3
import os
import sys
import time
import json
import requests
import re
import RPi.GPIO as GPIO
from datetime import datetime, timezone

# ---------------- Config ----------------
BASE_DIR = "/home/nolan/tempData"

RELAY_CHANNELS = [1,2,3,4,5,6,7,8]
CONTROL_TEMP = 355       # tenths of °F
RELAY_GPIO = 22
PIR_GPIO = 27
PIR_TIMEOUT_HOURS = 24   # PIR forces OFF for 24 hours
STALE_TEMP_HOURS = 48    # if ANY channel's latest reading is older than this -> OFF

# Files
DATA_FILE = os.path.join(BASE_DIR, "data", "data.jsonl")
CURRENT_TEMPS = os.path.join(BASE_DIR, "data", "currTemps.jsonl")   # JSONL: one line per channel (latest)
STATE_FILE = os.path.join(BASE_DIR, "data", "last_sent")
OCCUPIED_FILE = os.path.join(BASE_DIR, "data", "occupied")   # contains expiry epoch float
LOG_FILE = os.path.join(BASE_DIR, "data", "forwarder.log")
AUTH_FILE = os.path.join(BASE_DIR, "auth")

# Remote server
SERVER_URL = "https://cpu1.nolp.net/data"


# -------------- Helpers ----------------
def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    try:
        with open(LOG_FILE, "a") as lf:
            lf.write(f"{ts} {msg}\n")
    except Exception:
        pass

def get_last_sent():
    try:
        with open(STATE_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0

def set_last_sent(offset):
    try:
        with open(STATE_FILE, "w") as f:
            f.write(str(offset))
    except Exception:
        pass

# ---------------- Auth ----------------
if not os.path.exists(AUTH_FILE):
    with open(AUTH_FILE,'w') as f:
        f.write('insert auth token here')
    token_data = None
else:
    with open(AUTH_FILE, "r") as f:
        token_data = f.read().strip()

if not token_data or token_data == 'insert auth token here':
    log('No valid auth token found!')
    AUTH_HEADER = None
else:
    AUTH_HEADER = {
        "Authorization": f"Bearer {token_data}"
    }

# ---------------- Setup ----------------
for fn in (DATA_FILE, CURRENT_TEMPS):
    if not os.path.exists(fn):
        open(fn, "a").close()

GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_GPIO, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIR_GPIO, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

_relay_state = False  # False = OFF, True = ON

# ---------------- Occupied (PIR) ----------------
def read_occupied():
    try:
        with open(OCCUPIED_FILE, "r") as f:
            expiry = float(f.read().strip())
    except FileNotFoundError:
        return None
    except Exception:
        try: os.remove(OCCUPIED_FILE)
        except Exception: pass
        return None

    if time.time() > expiry:
        try: os.remove(OCCUPIED_FILE)
        except Exception: pass
        return None
    return expiry

def set_occupied(hours=PIR_TIMEOUT_HOURS):
    expiry = time.time() + hours*3600
    try:
        with open(OCCUPIED_FILE, "w") as f:
            f.write(str(expiry))
    except Exception:
        pass
    log(f"PIR: set occupied until {datetime.fromtimestamp(expiry).isoformat()}")

# ---------------- CURRENT_TEMPS ----------------
def load_current_temps_dict():
    out = {}
    try:
        with open(CURRENT_TEMPS, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    ch = int(r.get("channel"))
                    out[ch] = r
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return out

def write_current_temps_dict(d):
    try:
        with open(CURRENT_TEMPS, "w") as f:
            for ch in sorted(d.keys()):
                f.write(json.dumps(d[ch]) + "\n")
    except Exception:
        pass

def update_current_temps(record):
    if "channel" not in record:
        return
    try:
        ch = int(record["channel"])
    except Exception:
        return

    stored = dict(record)
    stored["channel"] = ch

    temps = load_current_temps_dict()
    temps[ch] = stored
    write_current_temps_dict(temps)

# ---------------- Safety / Relay ----------------
def relay_write(on):
    global _relay_state
    desired = bool(on)
    if desired == _relay_state:
        # Still log the actual pin voltage in case something external changed it
        actual = GPIO.input(RELAY_GPIO)
        log(f"RELAY already {'ON' if desired else 'OFF'}, actual pin={actual}")
        return
    _relay_state = desired
    try:
        GPIO.output(RELAY_GPIO, GPIO.HIGH if desired else GPIO.LOW)
        actual = GPIO.input(RELAY_GPIO)
    except Exception:
        actual = None
    log(f"RELAY set to {'ON' if desired else 'OFF'}, actual pin={actual}")

def parse_time(record_time_str):
    """Convert 'time' string to epoch float"""
    try:
        dt = datetime.strptime(record_time_str, "%Y-%m-%d %H:%M:%S%z")
        return dt.timestamp()
    except Exception:
        return None

def temps_are_stale(hours=STALE_TEMP_HOURS):
    cutoff = time.time() - hours*3600
    temps = load_current_temps_dict()
    for ch in RELAY_CHANNELS:
        r = temps.get(ch)
        if r is None:
            return True
        ts = parse_time(r.get("time"))
        if ts is None or ts < cutoff:
            return True
    return False

def all_channels_safe(control_temp=CONTROL_TEMP):
    temps = load_current_temps_dict()
    for ch in RELAY_CHANNELS:
        r = temps.get(ch)
        if r is None:
            log(f"Channel {ch} missing → NOT safe")
            return False
        temp = r.get("temperature")
        try:
            log(f"Channel {ch} temp={temp} control_temp={control_temp}")
            if int(temp) < int(control_temp):
                log(f"Channel {ch} below control_temp → NOT safe")
                return False
        except Exception:
            return False
    return True

def update_relay():
    if read_occupied() is not None:
        relay_write(False)
        return
    if temps_are_stale():
        relay_write(False)
        return
    if not all_channels_safe():
        relay_write(False)
        return
    relay_write(True)

# ---------------- Network ----------------
def send_record(record):
    headers = AUTH_HEADER if AUTH_HEADER else {}
    try:
        r = requests.put(SERVER_URL, headers=headers, json=record, timeout=10)
        return r.status_code in (200, 201, 202)
    except Exception:
        return False

def flush_backlog():
    last_sent = get_last_sent()
    sent = last_sent
    try:
        with open(DATA_FILE, "r") as f:
            f.seek(last_sent)
            while True:
                pos = f.tell()
                line = f.readline()
                if not line:
                    break
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if send_record(record):
                    sent = f.tell()
                    set_last_sent(sent)
                else:
                    break
    except FileNotFoundError:
        return

# ---------------- Parsing ----------------
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[-+]\d{4}")

def parse_reading(lines):
    reading = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue

        m = TIMESTAMP_RE.search(line)
        if m:
            reading["time"] = m.group(0)
            continue

        if "=" not in line:
            continue

        key, _, val = line.partition("=")
        key = key.strip().lower()
        val = val.strip()

        if key == "type":
            reading["type"] = "F007TH"
        elif key == "channel":
            try: reading["channel"] = int(val)
            except: reading["channel"] = val
        elif key == "rolling code":
            if "(" in val and ")" in val:
                try: reading["rolling_code"] = int(val.split("(")[-1].rstrip(")"))
                except: pass
        elif key == "temperature":
            try: reading["temperature"] = int(float(val.rstrip("F")))
            except: pass
        elif key == "humidity":
            try: reading["humidity"] = int(val.rstrip("%"))
            except: pass
        elif key == "battery":
            reading["battery_ok"] = val.upper() == "OK"
    return reading

# ---------------- PIR ----------------
def pir_callback(channel):
    set_occupied()
    log("PIR triggered; occupied extended/created")
    update_relay()

# ---------------- Main loop ----------------
def main():
    GPIO.add_event_detect(PIR_GPIO, GPIO.RISING, callback=pir_callback, bouncetime=200)
    _ = read_occupied()
    update_relay()
    flush_backlog()
    buffer = []

    try:
        with open(DATA_FILE, "a") as f:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                buffer.append(line)

                if "battery" in line:
                    record = parse_reading(buffer)
                    buffer = []

                    try:
                        f.write(json.dumps(record) + "\n")
                        f.flush()
                    except Exception:
                        log("Failed writing DATA_FILE")

                    update_current_temps(record)

                    if send_record(record):
                        try: set_last_sent(f.tell())
                        except Exception: pass

                    update_relay()
    except KeyboardInterrupt:
        pass
    finally:
        try: GPIO.cleanup()
        except Exception: pass

if __name__ == "__main__":
    main()
