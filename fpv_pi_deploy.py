# =============================================================
#  FPV IoT Strip Detector - RASPBERRY PI DEPLOYMENT
# =============================================================

import cv2
import numpy as np
import sqlite3
import requests
import time
import os
from datetime import datetime

# Strict hardware imports
import RPi.GPIO as GPIO
from picamera2 import Picamera2

# =============================================================
#                     CONFIGURATION
# =============================================================

CONFIG = {
    "IMAGE_PATH"         : "strip_capture.jpg",
    "SAVE_IMAGES"        : True,

    # HARDWARE ROI - Run calibrate_roi.py once the camera is mounted!
    "ROI_X"              : 300,
    "ROI_Y"              : 200,
    "ROI_W"              : 120,
    "ROI_H"              : 350,

    "PEAK_HEIGHT"        : 400,
    "PEAK_DISTANCE"      : 25,

    "LED_GREEN_PIN"      : 17,
    "LED_RED_PIN"        : 27,
    "LED_YELLOW_PIN"     : 22,

    "TELEGRAM_ENABLED"   : False,
    "TELEGRAM_TOKEN"     : "YOUR_BOT_TOKEN_HERE",
    "TELEGRAM_CHAT_ID"   : "YOUR_CHAT_ID_HERE",

    "DEVICE_ID"          : "FPV-UNIT-01",
    "LOCATION"           : "City Animal Shelter - Block A",
    "DB_PATH"            : "fpv_results.db",
}

def find_peaks_numpy(arr, height=400, distance=25):
    peaks = []
    n = len(arr)
    for i in range(1, n - 1):
        if arr[i] < height:
            continue
        if arr[i] < arr[i - 1] or arr[i] < arr[i + 1]:
            continue
        if peaks and (i - peaks[-1]) < distance:
            if arr[i] > arr[peaks[-1]]:
                peaks[-1] = i
            continue
        peaks.append(i)
    return np.array(peaks)




def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in [CONFIG["LED_GREEN_PIN"], CONFIG["LED_RED_PIN"], CONFIG["LED_YELLOW_PIN"]]:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
    print("[GPIO] Pins initialized")

def set_led(color):
    mapping = {"green": CONFIG["LED_GREEN_PIN"], "red": CONFIG["LED_RED_PIN"], "yellow": CONFIG["LED_YELLOW_PIN"]}
    for pin in mapping.values():
        GPIO.output(pin, GPIO.LOW)
    if color in mapping:
        GPIO.output(mapping[color], GPIO.HIGH)

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

def log_result(result, peaks_found, image_path, alert_sent):
    conn = sqlite3.connect(CONFIG["DB_PATH"])
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO results
        (timestamp, device_id, location, result, peaks_found, image_path, alert_sent)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        CONFIG["DEVICE_ID"], CONFIG["LOCATION"], result,
        peaks_found, image_path, 1 if alert_sent else 0,
    ))
    conn.commit()
    conn.close()

def capture_image(save_path):
    print("[CAM] Initializing camera...")
    cam = Picamera2()
    cfg = cam.create_still_configuration(main={"size": (1920, 1080)})
    cam.configure(cfg)
    cam.start()
    time.sleep(2) # Allow sensor to adjust to light
    frame = cam.capture_array()
    cam.stop()
    
    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    if CONFIG["SAVE_IMAGES"]:
        os.makedirs("captures", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        cv2.imwrite("captures/strip_" + ts + ".jpg", frame_bgr)

    cv2.imwrite(save_path, frame_bgr)
    print("[CAM] Image captured successfully")
    return frame_bgr
def detect_strip(image):
    x, y, w, h = CONFIG["ROI_X"], CONFIG["ROI_Y"], CONFIG["ROI_W"], CONFIG["ROI_H"]
    roi = image[y:y+h, x:x+w]
    
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 100, 255, cv2.THRESH_BINARY_INV)
    row_sums = np.sum(thresh, axis=1).astype(np.float32)

    peaks = find_peaks_numpy(row_sums, height=CONFIG["PEAK_HEIGHT"], distance=CONFIG["PEAK_DISTANCE"])
    num_peaks = len(peaks)

    if num_peaks == 2:
        result, decision, led = "POSITIVE", "FPV DETECTED - Alerting veterinary department!", "red"
    elif num_peaks == 1:
        result, decision, led = "NEGATIVE", "No FPV detected. Sample is clean.", "green"
    else:
        result, decision, led = "INVALID", "Test failed. Please retest with a new strip.", "yellow"

    annotated = image.copy()
    cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 255, 255), 2)
    line_colors = [(0, 0, 255), (0, 165, 255)]
    line_labels = ["T", "C"]
    
    for i, peak_row in enumerate(peaks):
        abs_y = y + int(peak_row)
        color = line_colors[i % 2]
        cv2.line(annotated, (x, abs_y), (x+w, abs_y), color, 2)
        cv2.putText(annotated, line_labels[i % 2], (x + w + 5, abs_y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    color_map = {"POSITIVE": (0, 0, 255), "NEGATIVE": (0, 200, 0), "INVALID": (0, 165, 255)}
    cv2.putText(annotated, result, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color_map.get(result, (255,255,255)), 3)

    annotated_path = "strip_annotated.jpg"
    cv2.imwrite(annotated_path, annotated)

    print(f"\n{'='*45}\n  RESULT    : {result}\n  LINES     : {num_peaks} line(s) detected\n  PEAKS AT  : {peaks.tolist()}\n  INFO      : {decision}\n{'='*45}\n")
    return {"result": result, "decision": decision, "peaks": peaks.tolist(), "num_peaks": num_peaks, "led": led, "annotated_path": annotated_path}

def send_telegram_alert(detection):
    if not CONFIG["TELEGRAM_ENABLED"]:
        return False

    token, chat_id = CONFIG["TELEGRAM_TOKEN"], CONFIG["TELEGRAM_CHAT_ID"]
    ts = datetime.now().strftime("%d %b %Y, %I:%M %p")
    msg = (f"FPV DETECTION ALERT\n----------------------------\nResult   : {detection['result']}\n"
           f"Device   : {CONFIG['DEVICE_ID']}\nLocation : {CONFIG['LOCATION']}\nTime     : {ts}\n"
           f"Lines    : {detection['num_peaks']} detected\n----------------------------\n"
           f"{detection['decision']}\n\nConfirm with PCR test before action.")
    
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        
        if os.path.exists(detection["annotated_path"]):
            photo_url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(detection["annotated_path"], "rb") as f:
                requests.post(photo_url, data={"chat_id": chat_id, "caption": f"Strip: {detection['result']}"}, files={"photo": f}, timeout=15)
                
        return resp.status_code == 200
    except Exception as e:
        print(f"[ALERT] Alert failed: {e}")
        return False

def run_detection():
    set_led("yellow")
    image = capture_image(CONFIG["IMAGE_PATH"])
    detection = detect_strip(image)
    set_led(detection["led"])
    
    alert_sent = False
    if detection["result"] == "POSITIVE":
        alert_sent = send_telegram_alert(detection)
        
    log_result(detection["result"], detection["num_peaks"], detection["annotated_path"], alert_sent)

def main():
    print(f"\n{'='*45}\n  FPV IoT STRIP DETECTOR (PI HARDWARE)\n  Device   : {CONFIG['DEVICE_ID']}\n  Location : {CONFIG['LOCATION']}\n{'='*45}\n")
    setup_gpio()
    init_database()

    print("[READY] System ready.\n[TIP]   Apply sample to strip, wait 10 min,\n        then press ENTER to scan.\n")