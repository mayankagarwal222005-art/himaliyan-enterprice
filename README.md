# 🚘 PlateTrack AI - Smart Vehicle ANPR & Stay Monitoring System

An AI-powered Automatic Number Plate Recognition (ANPR) and vehicle stay duration monitoring dashboard with a clean purple & white user interface, real-time Indian Standard Time (IST) tracking, live gate scanning, and automated Excel reporting.

---

## 🌟 Key Features

- **🎯 AI Plate Detection**: Custom-trained YOLO11 model (`best.pt`) optimized for vehicle license plates.
- **🔍 Indian Plate Recognition**: Robust OCR with Indian registration format normalization (`^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$`).
- **⏱️ Real Indian Standard Time (IST)**: Real-time clock and timestamps computed strictly in Indian Standard Time (`UTC+5:30`).
- **🔄 Automatic Entry & Exit Tracking**:
  - Automatically identifies whether a detected vehicle is entering or exiting.
  - Calculates exact stay duration upon exit (e.g., `2 hrs 15 mins 30 secs`).
- **📹 Multi-Source Scanning**:
  - **Live Gate Camera**: Real-time webcam/CCTV feed with interval scanning and sound/visual alerts.
  - **Photo Upload**: Instant detection on uploaded vehicle images.
  - **Video Processing**: Frame-by-frame analysis with license plate tracking.
  - **Sample Quick-Test**: One-click demo images for testing without extra setup.
- **🔎 Vehicle History Search**: Lookup any license plate number to see complete movement history, stay durations, and entry/exit status.
- **📊 Branded Excel Export**: Download beautifully formatted Excel workbooks (`.xlsx`) with purple headers, auto-adjusted column widths, and summary statistics.
- **🎨 Human-Crafted Purple & White Theme**: Modern, accessible, non-AI-looking responsive layout built with glassmorphism touches and semantic hierarchy.
- **📝 Manual Entry & Gate Checkout**: Manual override controls for gate operators.

---

## 🏗️ Project Architecture

```
PlateTrackAI/
├── backend/
│   ├── __init__.py           # Package marker
│   ├── database.py           # Thread-safe persistent JSON & CSV vehicle database + Excel exporter
│   └── detector.py           # YOLO11 + EasyOCR plate detection & Indian regex normalization
├── static/
│   └── index.html            # Single-page purple & white responsive dashboard UI
├── plate_samples/            # Sample vehicle plate images for testing
│   └── plate_100.jpg
├── best.pt                   # Trained YOLO11 model weights (~40 MB)
├── server.py                 # FastAPI web application with RESTful API endpoints
├── run_dashboard.bat         # One-click Windows launcher
├── requirements.txt          # Python project dependencies
├── vehicle_log.csv           # Live vehicle logging CSV
└── README.md                 # Project documentation
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10 or 3.11 recommended
- Webcam or camera device (for live gate scanning)

### 2. Installation
Clone the repository and install the dependencies:

```bash
git clone https://github.com/mayankagarwal222005-art/himaliyan-enterprice.git
cd himaliyan-enterprice
pip install -r requirements.txt
```

> **Note on PyTorch (Windows CPU)**: If you are running on CPU without CUDA:
> ```bash
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
> ```

### 3. Running the Dashboard

#### Option A: One-Click Windows Launcher
Double-click `run_dashboard.bat` or run:
```cmd
run_dashboard.bat
```

#### Option B: Terminal Command
```bash
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser and navigate to:
```
http://localhost:8000
```

---

## 📡 API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/` | `GET` | Dashboard frontend web interface |
| `/api/stats` | `GET` | Live overview statistics (vehicles inside, total logs, today's entries) |
| `/api/records` | `GET` | Retrieve vehicle records with optional status filter |
| `/api/scan/image` | `POST` | Detect and log license plate from an uploaded image file |
| `/api/scan/base64` | `POST` | Process camera snapshot for live gate detection |
| `/api/scan/video` | `POST` | Process uploaded video file with frame tracking |
| `/api/plate/{plate_number}` | `GET` | Search complete visit history for a specific license plate |
| `/api/records/checkout/{id}`| `POST` | Manually mark a vehicle as exited with duration calculation |
| `/api/records/manual` | `POST` | Manual gate entry creation |
| `/api/records/{id}` | `DELETE` | Delete a vehicle record |
| `/api/export/excel` | `GET` | Download styled Excel (.xlsx) report with IST timestamps |
| `/api/test-samples` | `GET` | List available test plate images |

---

## 🔒 Security & Best Practices

- Runtime databases and personal identifiable log files (`plate_database.json`, `*.log`) are ignored via `.gitignore`.
- All timestamps adhere strictly to real Indian Standard Time (`Asia/Kolkata` / `UTC+5:30`) and are formatted consistently.
- Thread-safe storage with graceful fallbacks ensures no corrupted files during concurrent scan operations.

---

## 📄 License
This project is developed for enterprise vehicle monitoring and gate management.
