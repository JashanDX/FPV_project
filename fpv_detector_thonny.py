# =============================================================
#  FPV (Feline Panleukopenia Virus) IoT Strip Detector
#  Device  : Raspberry Pi 4 + Pi Camera Module v2
#  Version : No-scipy build (works on Python 3.8 32-bit)
#  Tested  : Windows PC (Thonny) + Raspberry Pi
# =============================================================
#
#  REQUIREMENTS - install these in Thonny:
#  Tools > Manage Packages > search and install each one:
#    1. opencv-python  (already installed - done!)
#    2. numpy          (already installed - done!)
#    3. requests       (for Telegram alerts)
#    4. flask          (for web dashboard)
#
#  NO scipy needed anymore - removed completely!
# =============================================================

import cv2
import numpy as np
import sqlite3
import requests
import time
import os
from datetime import datetime

# --- Optional GPIO for LED (only works on Raspberry Pi) ------
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("[INFO] RPi.GPIO not found - OK, running on PC")

# --- Optional Pi Camera (only works on Raspberry Pi) ---------
try:
    from picamera2 import Picamera2
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False
    print("[INFO] Picamera2 not found - OK, using test image on PC")


# =============================================================
#                     CONFIGURATION
# =============================================================

CONFIG = {
    # Camera
    "IMAGE_PATH"         : "strip_capture.jpg",
    "SAVE_IMAGES"        : True,

    # ROI - Run calibrate_roi.py once to get your exact values
    # These are default values - update after calibration
    "ROI_X"              : 20,
    "ROI_Y"              : 250,
    "ROI_W"              : 160,
    "ROI_H"              : 300,

    # Line Detection Sensitivity
    # PEAK_HEIGHT : higher = less sensitive (fewer false positives)
    # PEAK_DISTANCE : min gap in pixels between two lines
    "PEAK_HEIGHT"        : 400,
    "PEAK_DISTANCE"      : 25,

    # GPIO Pin Numbers (BCM) - Raspberry Pi only
    "LED_GREEN_PIN"      : 17,
    "LED_RED_PIN"        : 27,
    "LED_YELLOW_PIN"     : 22,

    # Telegram - get token from @BotFather on Telegram app
    "TELEGRAM_ENABLED"   : True,
    "TELEGRAM_TOKEN"     : "8773281085:AAHYf36111w_dvx33nJ4sGq4bcGOlIp3O50",
    "TELEGRAM_CHAT_ID"   : "8773281085",

    # Device info
    "DEVICE_ID"          : "FPV-UNIT-01",
    "LOCATION"           : "City Animal Shelter - Block A",

    # Database file
    "DB_PATH"            : "fpv_results.db",
}


# =============================================================
#   PEAK FINDER - replaces scipy.signal.find_peaks
#   Pure numpy - works on ALL Python versions, no installs
# =============================================================

def find_peaks_numpy(arr, height=400, distance=25):
    """
    Finds peaks (spikes) in a 1D array.
    Replaces scipy.signal.find_peaks completely.

    arr      : 1D numpy array (our row pixel sums)
    height   : minimum value to count as a peak
    distance : minimum number of rows between two peaks

    Returns list of peak positions (row indices)
    """
    peaks = []
    n = len(arr)

    for i in range(1, n - 1):
        # Must be above minimum height
        if arr[i] < height:
            continue
        # Must be higher than both neighbours (local maximum)
        if arr[i] < arr[i - 1] or arr[i] < arr[i + 1]:
            continue
        # Must be far enough from the last found peak
        if peaks and (i - peaks[-1]) < distance:
            # Keep the higher one
            if arr[i] > arr[peaks[-1]]:
                peaks[-1] = i
            continue
        peaks.append(i)

    return np.array(peaks)


# =============================================================
#                      GPIO SETUP
# =============================================================

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


def set_led(color):
    """color: 'green', 'red', 'yellow', or 'off'"""
    if not GPIO_AVAILABLE:
        print("[LED SIM] " + color.upper() + " LED")
        return
    mapping = {
        "green"  : CONFIG["LED_GREEN_PIN"],
        "red"    : CONFIG["LED_RED_PIN"],
        "yellow" : CONFIG["LED_YELLOW_PIN"],
    }
    for pin in mapping.values():
        GPIO.output(pin, GPIO.LOW)
    if color in mapping:
        GPIO.output(mapping[color], GPIO.HIGH)


# =============================================================
#                    DATABASE
# =============================================================

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
    print("[DB] Database ready")


def log_result(result, peaks_found, image_path, alert_sent):
    conn = sqlite3.connect(CONFIG["DB_PATH"])
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO results
        (timestamp, device_id, location, result,
         peaks_found, image_path, alert_sent)
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
    print("[DB] Saved: " + result)


# =============================================================
#                    IMAGE CAPTURE
# =============================================================

def make_test_image(positive=False):
    """
    Generates a fake strip image for PC testing.
    On Raspberry Pi this is never called.

    positive=True  -> draws both T and C lines (FPV detected)
    positive=False -> draws only C line (clean)
    """
    # Light pink/beige background like a real strip
    img = np.ones((800, 200, 3), dtype=np.uint8) * 230
    # C line is always present
    cv2.rectangle(img, (320, 500), (400, 520), (70, 70, 150), -1)
    if positive:
        # T line only appears when FPV antigen found
        cv2.rectangle(img, (320, 300), (400, 320), (70, 70, 150), -1)
    return img


def capture_image(save_path):
    if PICAMERA_AVAILABLE:
        cam = Picamera2()
        cfg = cam.create_still_configuration(main={"size": (1920, 1080)})
        cam.configure(cfg)
        cam.start()
        time.sleep(2)
        frame = cam.capture_array()
        cam.stop()
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    else:
        print("[SIM] Using synthetic strip image (PC mode)")
        # Change positive=False to test a negative result
        frame_bgr = make_test_image(positive=True)

    if CONFIG["SAVE_IMAGES"]:
        os.makedirs("captures", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        cv2.imwrite("captures/strip_" + ts + ".jpg", frame_bgr)

    cv2.imwrite(save_path, frame_bgr)
    print("[CAM] Image captured")
    return frame_bgr


# =============================================================
#               STRIP DETECTION PIPELINE
# =============================================================

def detect_strip(image):
    """
    Complete image processing pipeline:

    1. Crop ROI (strip detection zone only)
    2. Grayscale
    3. Gaussian blur (remove noise)
    4. Threshold (make lines black/white)
    5. Row pixel sum (scan for horizontal lines)
    6. Peak detection (count C and T lines)
    7. Decision: 2 peaks = POSITIVE, 1 = NEGATIVE

    Returns dict with result, peak count, annotated image path.
    """

    # Step 1 - Crop to strip zone
    x = CONFIG["ROI_X"]
    y = CONFIG["ROI_Y"]
    w = CONFIG["ROI_W"]
    h = CONFIG["ROI_H"]
    
    print(f"Debug: Image shape is {image.shape}")
    print(f"Debug: ROI crop is y:{y}->{y+h}, x:{x}->{x+w}")
    roi = image[y:y+h, x:x+w]

    # Step 2 - Grayscale
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # Step 3 - Blur
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Step 4 - Threshold (dark lines become white on black)
    _, thresh = cv2.threshold(
        blurred, 100, 255, cv2.THRESH_BINARY_INV
    )

    # Step 5 - Count white pixels in each row
    row_sums = np.sum(thresh, axis=1).astype(np.float32)

    # Step 6 - Find peaks using our custom function (no scipy!)
    peaks = find_peaks_numpy(
        row_sums,
        height=CONFIG["PEAK_HEIGHT"],
        distance=CONFIG["PEAK_DISTANCE"]
    )
    num_peaks = len(peaks)

    # Step 7 - Decision
    if num_peaks == 2:
        result   = "POSITIVE"
        decision = "FPV DETECTED - Alerting veterinary department!"
        led      = "red"
    elif num_peaks == 1:
        result   = "NEGATIVE"
        decision = "No FPV detected. Sample is clean."
        led      = "green"
    else:
        result   = "INVALID"
        decision = "Test failed. Please retest with a new strip."
        led      = "yellow"

    # Annotate image for visual review
    annotated = image.copy()

    # Draw ROI box in cyan
    cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 255, 255), 2)

    # Draw detected lines
    line_colors = [(0, 0, 255), (0, 165, 255)]   # Red, Orange
    line_labels = ["T", "C"]
    for i, peak_row in enumerate(peaks):
        abs_y = y + int(peak_row)
        color = line_colors[i % 2]
        cv2.line(annotated, (x, abs_y), (x+w, abs_y), color, 2)
        cv2.putText(annotated, line_labels[i % 2],
                    (x + w + 5, abs_y + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # Draw result text on image
    color_map = {
        "POSITIVE": (0, 0, 255),
        "NEGATIVE": (0, 200, 0),
        "INVALID" : (0, 165, 255),
    }
    cv2.putText(annotated, result, (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2, color_map.get(result, (255,255,255)), 3)

    annotated_path = "strip_annotated.jpg"
    cv2.imwrite(annotated_path, annotated)

    # Print result to console
    print("")
    print("=" * 45)
    print("  RESULT    : " + result)
    print("  LINES     : " + str(num_peaks) + " line(s) detected")
    print("  PEAKS AT  : " + str(peaks.tolist()) + " (row positions)")
    print("  INFO      : " + decision)
    print("=" * 45)
    print("")

    return {
        "result"         : result,
        "decision"       : decision,
        "peaks"          : peaks.tolist(),
        "num_peaks"      : num_peaks,
        "led"            : led,
        "annotated_path" : annotated_path,
    }


# =============================================================
#                   TELEGRAM ALERT
# =============================================================

def send_telegram_alert(detection):
    if not CONFIG["TELEGRAM_ENABLED"]:
        print("[ALERT] Telegram not configured - skipping")
        return False

    token   = CONFIG["Enter your BOT token"]
    chat_id = CONFIG["Your chat ID"]
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


# =============================================================
#                       MAIN
# =============================================================

def run_detection():
    """One full scan cycle."""
    set_led("yellow")
    image     = capture_image(CONFIG["IMAGE_PATH"])
    detection = detect_strip(image)
    set_led(detection["led"])

    alert_sent = False
    if detection["result"] == "POSITIVE":
        alert_sent = send_telegram_alert(detection)

    log_result(
        result      = detection["result"],
        peaks_found = detection["num_peaks"],
        image_path  = detection["annotated_path"],
        alert_sent  = alert_sent,
    )
    return detection


def main():
    print("")
    print("=" * 45)
    print("  FPV IoT STRIP DETECTOR")
    print("  Device   : " + CONFIG["DEVICE_ID"])
    print("  Location : " + CONFIG["LOCATION"])
    print("=" * 45)
    print("")

    setup_gpio()
    init_database()

    print("[READY] System ready.")
    print("[TIP]   Apply sample to strip, wait 10 min,")
    print("        then press ENTER to scan.")
    print("")

    try:
        while True:
            input("  >> Press ENTER to scan strip...\n")
            run_detection()
            print("[DONE] Scan complete. Ready for next test.")
            print("-" * 45)
            print("")

    except KeyboardInterrupt:
        print("\n[EXIT] Shutting down...")
        set_led("off")
        if GPIO_AVAILABLE:
            GPIO.cleanup()


if __name__ == "__main__":
    main()
