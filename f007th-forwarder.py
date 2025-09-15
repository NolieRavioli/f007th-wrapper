#!/usr/bin/env python3
import os               # Filesystem paths and file ops
import sys              # Access stdin for streaming input lines
import time             # Timestamps, sleeping, epoch math
import json             # Read/write JSON records
import requests         # HTTP client for sending data to server
import re               # Regex for parsing timestamp lines
import RPi.GPIO as GPIO # Raspberry Pi GPIO control
from datetime import datetime, timezone  # Time parsing and formatting

# ---------------- Config ----------------
BASE_DIR = "/home/nolan/tempData"  # Root folder for data and state files

RELAY_CHANNELS = [1,2,3,4,5,6,7,8]  # Expected temperature channels (must all be present &amp; safe)
CONTROL_TEMP = 355       # Tenths of °F: 355 = 35.5°F threshold for "safe"
RELAY_GPIO = 22          # BCM pin controlling the relay coil
PIR_GPIO = 27            # BCM pin reading the PIR motion sensor
PIR_TIMEOUT_HOURS = 24   # After PIR triggers, force relay OFF for this many hours
STALE_TEMP_HOURS = 48    # If any channel's latest reading is older than this, force OFF

# Files
DATA_FILE = os.path.join(BASE_DIR, "data", "data.jsonl")              # Append-only raw readings stream (JSONL)
CURRENT_TEMPS = os.path.join(BASE_DIR, "data", "currTemps.jsonl")     # Latest reading per channel (JSONL)
STATE_FILE = os.path.join(BASE_DIR, "data", "last_sent")              # Byte offset into DATA_FILE last sent upstream
OCCUPIED_FILE = os.path.join(BASE_DIR, "data", "occupied")            # Contains epoch expiry for PIR-occupied window
LOG_FILE = os.path.join(BASE_DIR, "data", "forwarder.log")            # Text log for diagnostics
AUTH_FILE = os.path.join(BASE_DIR, "auth")                            # Bearer token file for server auth

# Remote server
SERVER_URL = "https://cpu1.nolp.net/data"  # Endpoint to PUT each record

# -------------- Helpers ----------------
def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())  # Human-readable local timestamp
    try:
        with open(LOG_FILE, "a") as lf:                        # Append to log file
            lf.write(f"{ts} {msg}\n")
    except Exception:
        pass  # Logging must never crash the program

def parse_time(record_time_str):
    """Convert 'time' string (YYYY-mm-dd HH:MM:SS±ZZZZ) to epoch float; None on failure."""
    try:
        dt = datetime.strptime(record_time_str, "%Y-%m-%d %H:%M:%S%z")
        return dt.timestamp()
    except Exception:
        return None

def get_last_sent():
    try:
        with open(STATE_FILE, "r") as f:   # Read previously stored file offset
            return int(f.read().strip())
    except Exception:
        return 0  # Default to 0 (send from beginning) if missing/corrupt

def set_last_sent(offset):
    try:
        with open(STATE_FILE, "w") as f:   # Persist new byte offset after successful send
            f.write(str(offset))
    except Exception:
        pass  # Ignore persistence failures; next loop will retry

# ---------------- Auth ----------------
if not os.path.exists(AUTH_FILE):
    # If no auth file exists, create placeholder and run without auth
    with open(AUTH_FILE,'w') as f:
        f.write('insert auth token here')
    token_data = None
else:
    # Read bearer token (single line) from disk
    with open(AUTH_FILE, "r") as f:
        token_data = f.read().strip()

if not token_data or token_data == 'insert auth token here':
    log('No valid auth token found!')  # Warn once via log
    AUTH_HEADER = None                 # Proceed without Authorization header
else:
    AUTH_HEADER = {
        "Authorization": f"Bearer {token_data}"  # Standard bearer token header
    }

# ---------------- Setup ----------------
for fn in (DATA_FILE, CURRENT_TEMPS):
    if not os.path.exists(fn):
        open(fn, "a").close()  # Ensure the data files exist so later opens succeed

GPIO.setmode(GPIO.BCM)                                   # Use Broadcom (BCM) numbering
GPIO.setup(RELAY_GPIO, GPIO.OUT, initial=GPIO.LOW)       # Relay output pin; start OFF
GPIO.setup(PIR_GPIO, GPIO.IN, pull_up_down=GPIO.PUD_DOWN) # PIR input with pull-down resistor

_relay_state = False  # Software-remembered relay state (False=OFF, True=ON) to avoid redundant writes

# ---------------- CURRENT_TEMPS ----------------
def load_current_temps_dict():
    """Load latest-per-channel readings from CURRENT_TEMPS into dict keyed by channel int."""
    out = {}
    try:
        with open(CURRENT_TEMPS, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue  # Skip blanks
                try:
                    r = json.loads(line)          # Parse JSONL line
                    ch = int(r.get("channel"))    # Normalize channel to int key
                    out[ch] = r                   # Store raw record by channel
                except Exception:
                    continue  # Skip malformed rows quietly
    except FileNotFoundError:
        pass  # Treat as empty if not present
    return out

def write_current_temps_dict(d):
    """Rewrite CURRENT_TEMPS with one JSON object per line ordered by channel."""
    try:
        with open(CURRENT_TEMPS, "w") as f:
            for ch in sorted(d.keys()):
                f.write(json.dumps(d[ch]) + "\n")  # Deterministic order aids diff/debug
    except Exception:
        pass  # Do not crash on write issues

def update_current_temps(record):
    """Update the 'latest per channel' store with a new reading record."""
    if "channel" not in record:
        return  # Ignore records without channel
    try:
        ch = int(record["channel"])  # Defensive parse as int
    except Exception:
        return  # Ignore if channel not numeric

    stored = dict(record)   # Copy so we can normalize without mutating caller
    stored["channel"] = ch  # Ensure int type stored

    temps = load_current_temps_dict()  # Load current snapshot
    temps[ch] = stored                 # Replace this channel's latest
    write_current_temps_dict(temps)    # Persist updated snapshot

# ---------------- Occupied (PIR) ----------------
def read_occupied():
    """Return expiry epoch if occupied window active; else None. Cleans up stale file."""
    try:
        with open(OCCUPIED_FILE, "r") as f:
            expiry = float(f.read().strip())  # Parse stored epoch seconds
    except FileNotFoundError:
        return None  # No occupied window stored
    except Exception:
        # If unreadable, remove and treat as not occupied
        try: os.remove(OCCUPIED_FILE)
        except Exception: pass
        return None

    if time.time() &gt; expiry:
        # Expired: delete marker and return None
        try: os.remove(OCCUPIED_FILE)
        except Exception: pass
        return None
    return expiry  # Still within the forced-occupied timeout

def set_occupied(hours=PIR_TIMEOUT_HOURS):
    """Create/update occupied window that forces relay OFF for given hours from now."""
    expiry = time.time() + hours*3600  # Calculate future epoch
    try:
        with open(OCCUPIED_FILE, "w") as f:
            f.write(str(expiry))       # Persist expiry
    except Exception:
        pass
    log(f"PIR: set occupied until {datetime.fromtimestamp(expiry).isoformat()}")  # Informative log

def occupied_is_active():
    """Return True if PIR 'occupied' timeout is still active, else False."""
    return read_occupied() is not None


# ---------------- Safety / Relay ----------------
def relay_write(on):
    """Drive the relay GPIO to desired state with logging; avoid redundant writes."""
    global _relay_state
    desired = bool(on)                 # Normalize to True/False
    if desired == _relay_state:
        # If nothing changes, still log the physical pin state for troubleshooting
        actual = GPIO.input(RELAY_GPIO)
        log(f"RELAY already {'ON' if desired else 'OFF'}, actual pin={actual}")
        return
    _relay_state = desired             # Update software state
    try:
        GPIO.output(RELAY_GPIO, GPIO.HIGH if desired else GPIO.LOW)  # Energize/de-energize coil
        actual = GPIO.input(RELAY_GPIO)                               # Read back pin for verification
    except Exception:
        actual = None  # If GPIO fails, we still log "None"
    log(f"RELAY set to {'ON' if desired else 'OFF'}, actual pin={actual}")

def temps_are_stale(hours=STALE_TEMP_HOURS):
    """Return True if ANY channel is missing or older than cutoff; used to fail-safe OFF."""
    cutoff = time.time() - hours*3600          # Oldest acceptable timestamp
    temps = load_current_temps_dict()          # Latest readings per channel
    for ch in RELAY_CHANNELS:
        r = temps.get(ch)
        if r is None:
            return True                        # Missing data =&gt; stale
        ts = parse_time(r.get("time"))
        if ts is None or ts &lt; cutoff:
            return True                        # Unparseable or too old =&gt; stale
    return False                                # All present and fresh

def all_channels_safe(control_temp=CONTROL_TEMP):
    """Return True only if every channel temp &gt;= control_temp; else False (fail-safe)."""
    temps = load_current_temps_dict()
    for ch in RELAY_CHANNELS:
        r = temps.get(ch)
        if r is None:
            log(f"Channel {ch} missing → NOT safe")
            return False
        temp = r.get("temperature")
        try:
            log(f"Channel {ch} temp={temp} control_temp={control_temp}")  # Trace each comparison
            if int(temp) &lt; int(control_temp):
                log(f"Channel {ch} below control_temp → NOT safe")
                return False
        except Exception:
            return False  # Non-integer or missing temperature =&gt; unsafe
    return True  # All channels meet or exceed control temp

def update_relay():
    """Composite safety controller: enforce OFF if occupied, stale, or unsafe; else ON."""
    if read_occupied() is not None:
        relay_write(False)  # PIR-occupied window forces OFF
        return
    if temps_are_stale():
        relay_write(False)  # Missing/old data forces OFF
        return
    if not all_channels_safe():
        relay_write(False)  # Any channel below threshold forces OFF
        return
    relay_write(True)       # All conditions nominal → turn ON

def relay_is_on():
    """Return True if relay is ON (coil energized), False otherwise."""
    try:
        return GPIO.input(RELAY_GPIO) == GPIO.HIGH
    except Exception:
        return False

# ---------------- Network ----------------
def send_record(record):
    """PUT a single reading to the server; True on 2xx, False otherwise."""
    headers = AUTH_HEADER if AUTH_HEADER else {}  # Add Authorization if available
    try:
        r = requests.put(SERVER_URL, headers=headers, json=record, timeout=10)  # 10s network timeout
        return r.status_code in (200, 201, 202)  # Accept common success codes
    except Exception:
        return False  # Network errors treated as send failure

def flush_backlog():
    """Send any unsent lines from DATA_FILE starting at stored byte offset; update offset on success."""
    last_sent = get_last_sent()  # Byte position where we left off
    sent = last_sent             # Track progress this pass
    try:
        with open(DATA_FILE, "r") as f:
            f.seek(last_sent)    # Seek to last successfully sent position
            while True:
                pos = f.tell()   # Current position before reading
                line = f.readline()
                if not line:
                    break        # EOF: nothing more to send
                try:
                    record = json.loads(line)  # Parse JSONL
                except json.JSONDecodeError:
                    continue     # Skip corrupt line but keep scanning
                if send_record(record):
                    sent = f.tell()     # Advance offset to after this line
                    set_last_sent(sent) # Persist progress incrementally
                else:
                    break        # Stop on first failed send (retry later)
    except FileNotFoundError:
        return  # No backlog yet; nothing to do

# ---------------- Parsing ----------------
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[-+]\d{4}")  # e.g., 2025-09-14 12:34:56-0600

def parse_reading(lines):
    """
    Convert a block of sensor text lines into a normalized reading dict.
    Expects keys like 'channel', 'temperature', 'humidity', 'battery' and a timestamp.
    """
    reading = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue  # Ignore blanks

        m = TIMESTAMP_RE.search(line)
        if m:
            reading["time"] = m.group(0)  # Capture precise timestamp with timezone
            continue

        if "=" not in line:
            continue  # Non key=value lines are ignored

        key, _, val = line.partition("=")  # Split only on first '='
        key = key.strip().lower()
        val = val.strip()

        if key == "type":
            reading["type"] = "F007TH"  # Normalize type name
        elif key == "channel":
            try: reading["channel"] = int(val)   # Prefer numeric channel
            except: reading["channel"] = val     # Fall back to raw value
        elif key == "rolling code":
            # Accept forms like "ABC (123)" → store 123
            if "(" in val and ")" in val:
                try: reading["rolling_code"] = int(val.split("(")[-1].rstrip(")"))
                except: pass
        elif key == "temperature":
            # Expect like "355F" or "35.5F" → store integer tenths of °F
            try: reading["temperature"] = int(float(val.rstrip("F")))
            except: pass
        elif key == "humidity":
            # Expect like "47%" → store integer percent
            try: reading["humidity"] = int(val.rstrip("%"))
            except: pass
        elif key == "battery":
            # Map textual status to boolean battery_ok
            reading["battery_ok"] = val.upper() == "OK"
    return reading  # May be partial if some fields missing

# -------------- PIR interrupt --------------
def pir_callback(channel):
    """GPIO interrupt handler: extend occupied window, log, and recompute relay state."""
    set_occupied()  # Start/extend timeout from now
    log("PIR triggered; occupied extended/created")
    update_relay()  # Immediately enforce OFF

# ---------------- Main loop ----------------
def main():
    # Register edge detection on PIR pin; rising edge = motion; debounce 200ms
    GPIO.add_event_detect(PIR_GPIO, GPIO.RISING, callback=pir_callback, bouncetime=200)
    _ = read_occupied()  # Prime occupied state (cleans up expired file if needed)
    update_relay()       # Set initial relay based on current conditions
    flush_backlog()      # Try to send any unsent historical records first
    buffer = []          # Accumulate lines until a complete reading (contains "battery")

    try:
        with open(DATA_FILE, "a") as f:  # Keep raw stream as JSONL append-only
            for line in sys.stdin:       # Read incoming text lines from STDIN continuously
                line = line.strip()
                if not line:
                    continue             # Skip empty lines
                buffer.append(line)      # Save for block parsing

                if "battery" in line:    # Heuristic: end of a reading block
                    record = parse_reading(buffer)  # Build record dict
                    buffer = []                      # Reset buffer for next block

                    # Add relay + occupied state fields
                    record["relay"] = relay_is_on()
                    record["occupied"] = occupied_is_active()

                    try:
                        f.write(json.dumps(record) + "\n")  # Append to DATA_FILE
                        f.flush()                            # Ensure durability for crash safety
                    except Exception:
                        log("Failed writing DATA_FILE")

                    update_current_temps(record)    # Refresh per-channel latest snapshot

                    if send_record(record):         # Attempt immediate upstream send
                        try: set_last_sent(f.tell())  # Mark offset as sent if success
                        except Exception: pass

                    update_relay()                  # Re-evaluate safety after new data
    except KeyboardInterrupt:
        pass  # Allow clean Ctrl+C exit
    finally:
        try: GPIO.cleanup()   # Return pins to safe state on exit
        except Exception: pass

if __name__ == "__main__":
    main()  # Entry point
