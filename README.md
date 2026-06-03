# FPV IoT Detector — Setup Guide

## Install Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Python packages
pip install opencv-python numpy scipy requests flask picamera2
```

## File Structure

```
fpv_project/
├── fpv_detector.py      ← Main detection script (run this)
├── calibrate_roi.py     ← Run ONCE to set ROI coordinates
├── dashboard.py         ← Web dashboard for viewing results
├── requirements.txt     ← All Python dependencies
├── captures/            ← Auto-created, stores all strip images
└── fpv_results.db       ← Auto-created SQLite database
```

## Step-by-Step First Run

1. Wire up Pi Camera and LEDs (see wiring below)
2. Run calibration:    python calibrate_roi.py
3. Copy ROI values into CONFIG inside fpv_detector.py
4. Set up Telegram bot (optional) and add token/chat_id
5. Run detector:       python fpv_detector.py
6. Run dashboard:      python dashboard.py  (separate terminal)

## Wiring (GPIO BCM)

| Component    | GPIO Pin | Physical Pin |
|--------------|----------|--------------|
| Green LED +  | GPIO 17  | Pin 11       |
| Red LED +    | GPIO 27  | Pin 13       |
| Yellow LED + | GPIO 22  | Pin 15       |
| All LED GND  | GND      | Pin 6        |

Add a 220Ω resistor in series with each LED.

## Telegram Bot Setup (Free)

1. Message @BotFather on Telegram → /newbot
2. Copy the bot token into CONFIG["TELEGRAM_TOKEN"]
3. Message @userinfobot to get your chat ID
4. Copy into CONFIG["TELEGRAM_CHAT_ID"]
5. Set CONFIG["TELEGRAM_ENABLED"] = True

## Auto-start on Boot

```bash
sudo nano /etc/systemd/system/fpv-detector.service
```

Paste:
```
[Unit]
Description=FPV Strip Detector
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/fpv_project/fpv_detector.py
WorkingDirectory=/home/pi/fpv_project
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable fpv-detector
sudo systemctl start fpv-detector
```
