# =============================================================
#  FPV IoT Strip Detector - PC SIMULATION ONLY
# =============================================================

import cv2
import numpy as np
import sqlite3
import requests
import time
import os
from datetime import datetime

# =============================================================
#                     CONFIGURATION
# =============================================================

CONFIG = {
    "IMAGE_PATH"         : "strip_capture_sim.jpg",
    "SAVE_IMAGES"        : True,

    # Tuned specifically for the 800x200 synthetic test image
    "ROI_X"              : 20,
    "ROI_Y"              : 250,
    "ROI_W"              : 160,
    "ROI_H"              : 300,

    "PEAK_HEIGHT"        : 400, # Lower this if lines aren't detected
    "PEAK_DISTANCE"      : 25,

    "TELEGRAM_ENABLED"   : True,
    "TELEGRAM_TOKEN"     : "8773281085:AAHYf36111w_dvx33nJ4sGq4bcGOlIp3O50",
    "TELEGRAM_CHAT_ID"   : "1448292438",

    "DEVICE_ID"          : "FPV-SIM-PC",
    "LOCATION"           : "Local Testing",
    "DB_PATH"            : "fpv_results_sim.db",
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

def set_led(color):
    print(f"[LED SIM] {color.upper()} LED ON")

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

def make_test_image(positive=True):
    img = np.ones((800, 200, 3), dtype=np.uint8) * 230
    cv2.rectangle(img, (20, 500), (180, 520), (70, 70, 150), -1)
    if positive:
        cv2.rectangle(img, (20, 300), (180, 320), (70, 70, 150), -1)
    return img

def capture_image(save_path):
    print("[SIM] Using synthetic strip image (PC mode)")
    frame_bgr = make_test_image(positive=True) 

    if CONFIG["SAVE_IMAGES"]:
        os.makedirs("captures", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        cv2.imwrite("captures/strip_sim_" + ts + ".jpg", frame_bgr)
    
    cv2.imwrite(save_path, frame_bgr)
    return frame_bgr

def detect_strip(image):
    x, y, w, h = CONFIG["ROI_X"], CONFIG["ROI_Y"], CONFIG["ROI_W"], CONFIG["ROI_H"]
    
    # Validation to prevent OpenCV crash
    if x + w > image.shape[1] or y + h > image.shape[0]:
        print("[ERROR] ROI is out of bounds! Check CONFIG values.")
        return {"result": "INVALID", "decision": "Crop error.", "peaks": [], "num_peaks": 0, "led": "yellow", "annotated_path": ""}

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

    annotated_path = "strip_annotated_sim.jpg"
    cv2.imwrite(annotated_path, annotated)

    print(f"\n{'='*45}\n  RESULT    : {result}\n  LINES     : {num_peaks} line(s) detected\n  PEAKS AT  : {peaks.tolist()}\n  INFO      : {decision}\n{'='*45}\n")
    return {"result": result, "decision": decision, "peaks": peaks.tolist(), "num_peaks": num_peaks, "led": led, "annotated_path": annotated_path}


# =============================================================
#                   TELEGRAM ALERT
# =============================================================

def send_telegram_alert(detection):
    if not CONFIG["TELEGRAM_ENABLED"]:
        print("[ALERT] Telegram not configured - skipping")
        return False

    token   = CONFIG["TELEGRAM_TOKEN"]
    chat_id = CONFIG["TELEGRAM_CHAT_ID"]
    ts      = datetime.now().strftime("%d %b %Y, %I:%M %p")

    msg = (
        "FPV DETECTION ALERT\n"
        "----------------------------\n"
        "Result   : " + detection["result"] + "\n"
        "Device   : " + CONFIG["DEVICE_ID"] + "\n"
        "Location : " + CONFIG["LOCATION"] + "\n"
        "Time     : " + ts + "\n"
        "Lines    : " + str(detection["num_peaks"]) + " detected\n"
        "----------------------------\n"
        + detection["decision"] + "\n\n"
        "Confirm with PCR test before action."
    )

    try:
        url  = "https://api.telegram.org/bot" + token + "/sendMessage"
        resp = requests.post(url, data={
            "chat_id": chat_id,
            "text"   : msg,
        }, timeout=10)

        if os.path.exists(detection["annotated_path"]):
            photo_url = "https://api.telegram.org/bot" + token + "/sendPhoto"
            with open(detection["annotated_path"], "rb") as f:
                requests.post(photo_url,
                    data={"chat_id": chat_id,
                          "caption": "Strip: " + detection["result"]},
                    files={"photo": f},
                    timeout=15)

        if resp.status_code == 200:
            print("[ALERT] Telegram alert sent!")
            return True
        else:
            print("[ALERT] Telegram error: " + str(resp.status_code))
            return False

    except Exception as e:
        print("[ALERT] Alert failed: " + str(e))
        return False
    
    
    
def run_detection():
    set_led("yellow")
    image = capture_image(CONFIG["IMAGE_PATH"])
    detection = detect_strip(image)
    set_led(detection["led"])
    alert_sent=False
    # Crucial where bots get triggered
    if detection["result"]== "POSITIVE":
        alert_sent=send_telegram_alert(detection)
    log_result(detection["result"], detection["num_peaks"], detection["annotated_path"], alert_sent)

def main():
    print(f"\n{'='*45}\n  FPV IoT STRIP DETECTOR (PC SIM)\n{'='*45}\n")
    init_database()
    while True:
        try:
            input("  >> Press ENTER to run simulation scan...\n")
            run_detection()
        except KeyboardInterrupt:
            print("\n[EXIT] Shutting down...")
            break

if __name__ == "__main__":
    main()