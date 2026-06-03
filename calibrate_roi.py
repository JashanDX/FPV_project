"""
=============================================================
  ROI CALIBRATION TOOL — Run this ONCE during device setup
  Drag a rectangle over the strip zone on the captured image.
  Copy the printed coordinates into CONFIG in fpv_detector.py
=============================================================
"""

import cv2
import sys
import os

# ── Try to capture from Pi Camera, else load a saved image ──
try:
    from picamera2 import Picamera2
    import time

    print("[CAM] Capturing calibration image from Pi Camera...")
    cam = Picamera2()
    cam.start()
    time.sleep(2)
    frame = cam.capture_array()
    cam.stop()
    image = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    cv2.imwrite("calibration_capture.jpg", image)
    print("[CAM] Saved calibration_capture.jpg")

except ImportError:
    # Load a previously saved image if no Pi Camera
    path = "calibration_capture.jpg"
    if not os.path.exists(path):
        print(f"[ERROR] No camera found and '{path}' does not exist.")
        print("  → Take a photo of your test strip setup and save it as:")
        print(f"    {os.path.abspath(path)}")
        sys.exit(1)
    image = cv2.imread(path)
    print(f"[INFO] Loaded existing image: {path}")


print("\n[INSTRUCTIONS]")
print("  1. A window will open showing your captured image")
print("  2. Click and drag to select the STRIP DETECTION ZONE")
print("     (the area containing only the C and T line region)")
print("  3. Press ENTER or SPACE to confirm selection")
print("  4. Press C to cancel and retry\n")

# ── Interactive ROI selection ────────────────────────────────
roi = cv2.selectROI(
    "Calibration — Select Strip Zone (ENTER to confirm)",
    image,
    showCrosshair=True,
    fromCenter=False
)
cv2.destroyAllWindows()

x, y, w, h = roi

if w == 0 or h == 0:
    print("[ERROR] No region selected. Please run again.")
    sys.exit(1)

# ── Print result ─────────────────────────────────────────────
print("\n" + "="*50)
print("  ✅  ROI CALIBRATION COMPLETE")
print("="*50)
print(f"\n  ROI_X = {x}")
print(f"  ROI_Y = {y}")
print(f"  ROI_W = {w}")
print(f"  ROI_H = {h}")
print("\n  Copy these values into CONFIG in fpv_detector.py")
print("="*50 + "\n")

# ── Save a preview image showing the selected ROI ────────────
preview = image.copy()
cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 255, 0), 3)
cv2.putText(preview, "Selected ROI",
            (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX,
            0.8, (0, 255, 0), 2)
cv2.imwrite("calibration_roi_preview.jpg", preview)
print("[INFO] Preview saved → calibration_roi_preview.jpg")

# ── Save coords to a JSON file for reference ─────────────────
import json
with open("roi_config.json", "w") as f:
    json.dump({"ROI_X": x, "ROI_Y": y, "ROI_W": w, "ROI_H": h}, f, indent=2)
print("[INFO] Coordinates saved → roi_config.json")

# THANK YOU!