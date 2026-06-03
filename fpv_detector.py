"""
=============================================================
 FPV (Feline Panleukopenia Virus) IoT Strip Detector
 Author  : Your Name
 Device  : Raspberry Pi 4 + Pi Camera Module v2
 Purpose : Capture FPV rapid test strip, detect C/T lines,
           log results, and alert veterinary department.
=============================================================
"""

import cv2
import numpy as np
import sqlite3
import requests
import time
import os
import json
from datetime import datetime
from scipy.signal import find_peaks

# ── Optional: GPIO for LED indicators ──────────────────────
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("[INFO] RPi.GPIO not found — running in simulation mode")

# ── Optional: Pi Camera ────────────────────────────────────
try:
    from picamera2 import Picamera2
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False
    print("[INFO] Picamera2 not found — will use test image instead")


# ╔══════════════════════════════════════════════════════════╗
# ║                    CONFIGURATION                        ║
# ╚══════════════════════════════════════════════════════════╝

CONFIG = {
    # ── Camera ──────────────────────────────────────────────
    "CAPTURE_DELAY_SEC"  : 600,        # 10 min wait after sample applied
    "IMAGE_PATH"         : "strip_capture.jpg",
    "SAVE_IMAGES"        : True,        # Save every captured image

    # ── ROI (Region of Interest) ────────────────────────────
    # Run calibrate_roi.py first to find your exact values!
    "ROI_X"              : 300,
    "ROI_Y"              : 200,
    "ROI_W"              : 120,
    "ROI_H"              : 350,

    # ── Line Detection Sensitivity ──────────────────────────
    "PEAK_HEIGHT"        : 400,         # Min pixel sum to count as a line
    "PEAK_DISTANCE"      : 25,          # Min row gap between two lines

    # ── GPIO Pin Numbers (BCM mode) ─────────────────────────
    "LED_GREEN_PIN"      : 17,          # Negative result
    "LED_RED_PIN"        : 27,          # Positive result
    "LED_YELLOW_PIN"     : 22,          # Invalid / processing

    # ── Telegram Alert ──────────────────────────────────────
    # Get token from @BotFather, get chat_id from @userinfobot
    "TELEGRAM_ENABLED"   : False,       # Set True once configured
    "TELEGRAM_TOKEN"     : "YOUR_BOT_TOKEN_HERE",
    "TELEGRAM_CHAT_ID"   : "YOUR_CHAT_ID_HERE",

    # ── Device Identity ─────────────────────────────────────
    "DEVICE_ID"          : "FPV-UNIT-01",
    "LOCATION"           : "City Animal Shelter - Block A",

    # ── Database ─────────────────────────────────────────────
    "DB_PATH"            : "fpv_results.db",
}


# ╔══════════════════════════════════════════════════════════╗
# ║                   GPIO SETUP                            ║
# ╚══════════════════════════════════════════════════════════╝

def setup_gpio():
    if not GPIO_AVAILABLE:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in [CONFIG["LED_GREEN_PIN"],
                CONFIG["LED_RED_PIN"],
                CONFIG["LED_YELLOW_PIN"]]:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
    print("[GPIO] Pins initialized")


def set_led(color: str):
    """Turn on one LED and turn off the others.
       color: 'green' | 'red' | 'yellow' | 'off'
    """
    if not GPIO_AVAILABLE:
        print(f"[LED SIM] {color.upper()} LED ON")
        return
    mapping = {
        "green"  : CONFIG["LED_GREEN_PIN"],
        "red"    : CONFIG["LED_RED_PIN"],
        "yellow" : CONFIG["LED_YELLOW_PIN"],
    }
    # Turn all off first
    for pin in mapping.values():
        GPIO.output(pin, GPIO.LOW)
    if color in mapping:
        GPIO.output(mapping[color], GPIO.HIGH)


# ╔══════════════════════════════════════════════════════════╗
# ║                  DATABASE SETUP                         ║
# ╚══════════════════════════════════════════════════════════╝

def init_database():
    conn = sqlite3.connect(CONFIG["DB_PATH"])
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            device_id   TEXT NOT NULL,
            location    TEXT NOT NULL,
            result      TEXT NOT NULL,
            peaks_found INTEGER NOT NULL,
            image_path  TEXT,
            alert_sent  INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    print("[DB] Database initialized")


def log_result(result: str, peaks_found: int,
               image_path: str, alert_sent: bool):
    conn = sqlite3.connect(CONFIG["DB_PATH"])
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO results
        (timestamp, device_id, location, result, peaks_found, image_path, alert_sent)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        CONFIG["DEVICE_ID"],
        CONFIG["LOCATION"],
        result,
        peaks_found,
        image_path,
        1 if alert_sent else 0,
    ))
    conn.commit()
    conn.close()
    print(f"[DB] Result logged: {result}")


# ╔══════════════════════════════════════════════════════════╗
# ║                  IMAGE CAPTURE                          ║
# ╚══════════════════════════════════════════════════════════╝

def capture_image(save_path: str) -> np.ndarray:
    if PICAMERA_AVAILABLE:
        cam = Picamera2()
        config = cam.create_still_configuration(
            main={"size": (1920, 1080)}
        )
        cam.configure(config)
        cam.start()
        time.sleep(2)                      # Warm-up time
        frame = cam.capture_array()
        cam.stop()
        # Picamera2 returns RGB — convert to BGR for OpenCV
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    else:
        # --- SIMULATION MODE ---
        # In real deployment this branch is never hit.
        # Creates a synthetic strip image for testing on PC.
        print("[SIM] Generating synthetic test strip image")
        frame_bgr = _generate_synthetic_strip(positive=True)

    if CONFIG["SAVE_IMAGES"]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = f"captures/strip_{ts}.jpg"
        os.makedirs("captures", exist_ok=True)
        cv2.imwrite(archive_path, frame_bgr)
    cv2.imwrite(save_path, frame_bgr)
    print(f"[CAM] Image saved → {save_path}")
    return frame_bgr


def _generate_synthetic_strip(positive: bool = True) -> np.ndarray:
    """Creates a fake strip image for PC testing only."""
    img = np.ones((800, 200, 3), dtype=np.uint8) * 230   # Light background
    # Draw C line (always present)
    cv2.rectangle(img, (20, 500), (180, 520), (80, 80, 160), -1)
    if positive:
        # Draw T line (only if positive)
        cv2.rectangle(img, (20, 300), (180, 320), (80, 80, 160), -1)
    return img


# ╔══════════════════════════════════════════════════════════╗
# ║               STRIP DETECTION CORE                      ║
# ╚══════════════════════════════════════════════════════════╝

def detect_strip(image: np.ndarray) -> dict:
    """
    Full image-processing pipeline.
    Returns a dict with result, peaks, annotated image.
    """
    # ── Step 1: Crop ROI ──────────────────────────────────
    x = CONFIG["ROI_X"]
    y = CONFIG["ROI_Y"]
    w = CONFIG["ROI_W"]
    h = CONFIG["ROI_H"]
    roi = image[y:y+h, x:x+w]

    # ── Step 2: Grayscale ─────────────────────────────────
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # ── Step 3: Gaussian Blur ─────────────────────────────
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # ── Step 4: Threshold ─────────────────────────────────
    _, thresh = cv2.threshold(
        blurred, 100, 255, cv2.THRESH_BINARY_INV
    )

    # ── Step 5: Row-wise pixel summation ──────────────────
    row_sums = np.sum(thresh, axis=1).astype(np.float32)

    # ── Step 6: Peak detection ────────────────────────────
    peaks, properties = find_peaks(
        row_sums,
        height=CONFIG["PEAK_HEIGHT"],
        distance=CONFIG["PEAK_DISTANCE"]
    )
    num_peaks = len(peaks)

    # ── Step 7: Decision ──────────────────────────────────
    if num_peaks == 2:
        result   = "POSITIVE"
        decision = "⚠️  FPV DETECTED — Alerting veterinary department!"
        led      = "red"
    elif num_peaks == 1:
        result   = "NEGATIVE"
        decision = "✅  No FPV detected — Sample is clean."
        led      = "green"
    else:
        result   = "INVALID"
        decision = "❌  Test invalid — Please retest with a new strip."
        led      = "yellow"

    # ── Step 8: Annotate original image for saving ────────
    annotated = image.copy()
    # Draw ROI rectangle
    cv2.rectangle(annotated,
                  (x, y), (x + w, y + h),
                  (0, 255, 255), 2)
    # Draw detected line positions
    colors = [(0, 0, 255), (0, 165, 255)]   # Red, Orange for peaks
    for i, peak_row in enumerate(peaks):
        abs_y = y + peak_row
        color = colors[i % len(colors)]
        cv2.line(annotated,
                 (x, abs_y), (x + w, abs_y),
                 color, 2)
        label = "T" if i == 0 else "C"
        cv2.putText(annotated, label,
                    (x + w + 5, abs_y + 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, color, 2)
    # Result text on image
    color_map = {
        "POSITIVE": (0, 0, 255),
        "NEGATIVE": (0, 200, 0),
        "INVALID" : (0, 165, 255),
    }
    cv2.putText(annotated, result,
                (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2, color_map[result], 3)

    annotated_path = "strip_annotated.jpg"
    cv2.imwrite(annotated_path, annotated)

    print(f"\n{'='*50}")
    print(f"  RESULT   : {result}")
    print(f"  PEAKS    : {num_peaks} line(s) detected at rows {peaks.tolist()}")
    print(f"  DECISION : {decision}")
    print(f"{'='*50}\n")

    return {
        "result"        : result,
        "decision"      : decision,
        "peaks"         : peaks.tolist(),
        "num_peaks"     : num_peaks,
        "led"           : led,
        "annotated_path": annotated_path,
        "row_sums"      : row_sums.tolist(),
    }


# ╔══════════════════════════════════════════════════════════╗
# ║               TELEGRAM ALERT SYSTEM                     ║
# ╚══════════════════════════════════════════════════════════╝

def send_telegram_alert(detection: dict) -> bool:
    if not CONFIG["TELEGRAM_ENABLED"]:
        print("[ALERT] Telegram disabled in config — skipping")
        return False

    token   = CONFIG["TELEGRAM_TOKEN"]
    chat_id = CONFIG["TELEGRAM_CHAT_ID"]
    ts      = datetime.now().strftime("%d %b %Y, %I:%M %p")

    message = (
        f"🐱 *FPV DETECTION ALERT*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*Result*   : `{detection['result']}`\n"
        f"*Device*   : `{CONFIG['DEVICE_ID']}`\n"
        f"*Location* : {CONFIG['LOCATION']}\n"
        f"*Time*     : {ts}\n"
        f"*Lines*    : {detection['num_peaks']} detected\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{detection['decision']}\n\n"
        f"_Please confirm with PCR test before action._"
    )

    try:
        # Send text message
        text_url = (
            f"https://api.telegram.org/bot{token}"
            f"/sendMessage"
        )
        resp = requests.post(text_url, data={
            "chat_id"    : chat_id,
            "text"       : message,
            "parse_mode" : "Markdown",
        }, timeout=10)

        # Send annotated strip image
        if os.path.exists(detection["annotated_path"]):
            photo_url = (
                f"https://api.telegram.org/bot{token}"
                f"/sendPhoto"
            )
            with open(detection["annotated_path"], "rb") as img_file:
                requests.post(photo_url, data={
                    "chat_id": chat_id,
                    "caption": f"Strip image — {detection['result']}"
                }, files={"photo": img_file}, timeout=15)

        if resp.status_code == 200:
            print("[ALERT] Telegram alert sent successfully ✓")
            return True
        else:
            print(f"[ALERT] Telegram error: {resp.status_code} — {resp.text}")
            return False

    except Exception as e:
        print(f"[ALERT] Failed to send Telegram alert: {e}")
        return False


# ╔══════════════════════════════════════════════════════════╗
# ║                    MAIN LOOP                            ║
# ╚══════════════════════════════════════════════════════════╝

def run_detection():
    """Single detection cycle — capture → detect → alert → log."""
    set_led("yellow")   # Yellow = processing

    # Capture
    image = capture_image(CONFIG["IMAGE_PATH"])

    # Detect
    detection = detect_strip(image)

    # LED feedback
    set_led(detection["led"])

    # Alert (only on positive results)
    alert_sent = False
    if detection["result"] == "POSITIVE":
        alert_sent = send_telegram_alert(detection)

    # Log to database
    log_result(
        result      = detection["result"],
        peaks_found = detection["num_peaks"],
        image_path  = detection["annotated_path"],
        alert_sent  = alert_sent,
    )

    return detection


def main():
    print("\n" + "="*50)
    print("  FPV IoT STRIP DETECTOR — STARTING UP")
    print(f"  Device  : {CONFIG['DEVICE_ID']}")
    print(f"  Location: {CONFIG['LOCATION']}")
    print("="*50 + "\n")

    # Initialization
    setup_gpio()
    init_database()

    print("[READY] Device is ready. Insert strip after applying sample.")
    print(f"[TIMER] Waiting {CONFIG['CAPTURE_DELAY_SEC']}s "
          f"for test to develop...\n")

    try:
        while True:
            input("  ▶  Press ENTER when strip is ready to scan...\n")

            detection = run_detection()

            print("\n[LOOP] Waiting for next test...")
            print("-" * 50 + "\n")

    except KeyboardInterrupt:
        print("\n[EXIT] Shutting down detector...")
        set_led("off")
        if GPIO_AVAILABLE:
            GPIO.cleanup()


if __name__ == "__main__":
    main()
