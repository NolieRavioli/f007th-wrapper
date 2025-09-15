# ---------------- Network ----------------
def send_record(record):
    """PUT a single reading to the server; True on 2xx, False otherwise."""
    headers = AUTH_HEADER if AUTH_HEADER else {}
    try:
        r = requests.put(SERVER_URL, headers=headers, json=record, timeout=10)
        return r.status_code in (200, 201, 202)
    except Exception:
        return False


def flush_backlog():
    """Send any unsent lines from DATA_FILE starting at stored byte offset; update offset on success."""
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
TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[-+]\d{4}"
)  # e.g., 2025-09-14 12:34:56-0600


def parse_reading(lines):
    """
    Convert a block of sensor text lines into a normalized reading dict.
    Expects keys like 'channel', 'temperature', 'humidity', 'battery' and a timestamp.
    """
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
            try:
                reading["channel"] = int(val)
            except Exception:
                reading["channel"] = val
        elif key == "rolling code":
            if "(" in val and ")" in val:
                try:
                    reading["rolling_code"] = int(val.split("(")[-1].rstrip(")"))
                except Exception:
                    pass
        elif key == "temperature":
            try:
                reading["temperature"] = int(float(val.rstrip("F")))
            except Exception:
                pass
        elif key == "humidity":
            try:
                reading["humidity"] = int(val.rstrip("%"))
            except Exception:
                pass
        elif key == "battery":
            reading["battery_ok"] = val.upper() == "OK"
    return reading


# -------------- PIR interrupt --------------
def pir_callback(channel):
    """GPIO interrupt handler: extend occupied window, log, and recompute relay state."""
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

                    record["relay"] = relay_is_on()
                    record["occupied"] = occupied_is_active()

                    try:
                        f.write(json.dumps(record) + "\n")
                        f.flush()
                    except Exception:
                        log("Failed writing DATA_FILE")

                    update_current_temps(record)

                    if send_record(record):
                        try:
                            set_last_sent(f.tell())
                        except Exception:
                            pass

                    update_relay()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            GPIO.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()
