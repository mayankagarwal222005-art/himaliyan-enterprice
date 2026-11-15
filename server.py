import os
import io
import cv2
import numpy as np
import base64
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.database import VehicleDatabase, get_current_ist_time, format_ist_datetime
from backend.detector import PlateDetector

app = FastAPI(title="PlateTrack AI - Smart Vehicle ANPR & Stay Duration System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "best.pt")
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Mount static folder
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Initialize database and detector
db = VehicleDatabase(
    data_file=os.path.join(BASE_DIR, "plate_database.json"),
    csv_file=os.path.join(BASE_DIR, "vehicle_log.csv")
)
detector = PlateDetector(model_path=MODEL_PATH)


class Base64ScanRequest(BaseModel):
    image: str # data:image/jpeg;base64,...
    mode: Optional[str] = "auto" # 'auto', 'entry', 'exit'
    source: Optional[str] = "Live Camera"


class ManualEntryRequest(BaseModel):
    plate_number: str
    status: Optional[str] = "INSIDE" # 'INSIDE' or 'EXITED'
    source: Optional[str] = "Manual Entry"


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the main dashboard page."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>PlateTrack AI Dashboard loading...</h1>")


@app.get("/api/stats")
async def get_dashboard_stats():
    """Returns real-time dashboard statistics."""
    return db.get_dashboard_stats()


@app.get("/api/records")
async def get_records(query: str = Query("", description="Search by plate number"),
                      status: str = Query("", description="Filter by status: ALL, INSIDE, EXITED")):
    """Returns filtered vehicle records."""
    return db.get_all_records(query=query, status_filter=status)


@app.get("/api/plate/{plate_number}")
async def get_plate_history(plate_number: str):
    """Returns visit history and stay duration metrics for a specific plate number."""
    history = db.get_vehicle_history(plate_number)
    return history


@app.post("/api/scan/image")
async def scan_image(
    file: Optional[UploadFile] = File(None),
    mode: str = Form("auto"),
    source: str = Form("Upload (Photo)")
):
    """Scans an uploaded image file (photo) for vehicle license plates."""
    if not file:
        raise HTTPException(status_code=400, detail="No image file provided")

    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image file format")

    detection_result = detector.detect_and_recognize(image)
    plates = detection_result.get("plates", [])

    events = []
    if plates:
        for p in plates:
            plate_no = p.get("plate_number")
            conf = p.get("confidence", 0.90)
            if plate_no:
                event = db.process_plate_event(
                    plate_number=plate_no,
                    confidence=conf,
                    source=source,
                    mode=mode
                )
                events.append(event)
    else:
        # Check if plate could not be resolved
        events.append({
            "action": "NO_PLATE_DETECTED",
            "message": "No vehicle registration plate detected in this frame."
        })

    return {
        "success": True,
        "plates": plates,
        "events": events,
        "annotated_image": detection_result.get("annotated_image"),
        "stats": db.get_dashboard_stats()
    }


@app.post("/api/scan/base64")
async def scan_base64_frame(payload: Base64ScanRequest):
    """Scans a webcam canvas frame sent as base64 string."""
    try:
        raw_b64 = payload.image
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
            
        img_bytes = base64.b64decode(raw_b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            raise HTTPException(status_code=400, detail="Could not decode base64 image")
            
        detection_result = detector.detect_and_recognize(image)
        plates = detection_result.get("plates", [])
        
        events = []
        if plates:
            for p in plates:
                plate_no = p.get("plate_number")
                conf = p.get("confidence", 0.90)
                if plate_no:
                    event = db.process_plate_event(
                        plate_number=plate_no,
                        confidence=conf,
                        source=payload.source or "Live Camera",
                        mode=payload.mode or "auto"
                    )
                    events.append(event)
                    
        return {
            "success": True,
            "plates": plates,
            "events": events,
            "annotated_image": detection_result.get("annotated_image"),
            "stats": db.get_dashboard_stats()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scan/video")
async def scan_video(
    file: UploadFile = File(...),
    mode: str = Form("auto")
):
    """Processes an uploaded video file, identifies plates, and logs events."""
    import tempfile
    
    suffix = os.path.splitext(file.filename)[1] or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        detected_plates = detector.process_video(tmp_path, max_frames=80, sample_interval=5)
        events = []
        for p in detected_plates:
            plate_no = p.get("plate_number")
            conf = p.get("confidence", 0.90)
            if plate_no:
                event = db.process_plate_event(
                    plate_number=plate_no,
                    confidence=conf,
                    source=f"Video: {file.filename}",
                    mode=mode
                )
                events.append(event)

        return {
            "success": True,
            "video_filename": file.filename,
            "detected_plates": detected_plates,
            "events": events,
            "stats": db.get_dashboard_stats()
        }
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@app.post("/api/records/checkout/{record_id}")
async def checkout_vehicle_endpoint(record_id: str):
    """Manually checks out an inside vehicle."""
    result = db.checkout_vehicle(record_id)
    if not result:
        raise HTTPException(status_code=404, detail="Active vehicle record not found or already exited")
    return {"success": True, "record": result, "stats": db.get_dashboard_stats()}


@app.post("/api/records/manual")
async def manual_entry(payload: ManualEntryRequest):
    """Manually adds a vehicle entry or exit record."""
    clean_plate = detector.clean_raw_text(payload.plate_number)
    if not clean_plate or len(clean_plate) < 4:
        raise HTTPException(status_code=400, detail="Invalid vehicle plate number")
        
    mode = "entry" if payload.status == "INSIDE" else "exit"
    event = db.process_plate_event(
        plate_number=clean_plate,
        confidence=1.0,
        source=payload.source or "Manual Security Gate",
        mode=mode
    )
    return {"success": True, "event": event, "stats": db.get_dashboard_stats()}


@app.get("/api/export/excel")
async def export_excel_report():
    """Generates and downloads an Excel spreadsheet report (.xlsx)."""
    excel_stream = db.export_excel()
    filename = f"PlateTrack_Report_{get_current_ist_time().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        excel_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.delete("/api/records/clear")
async def clear_all_records():
    """Clears all records from database."""
    db.clear_all()
    return {"success": True, "message": "All records cleared", "stats": db.get_dashboard_stats()}


@app.get("/api/test-samples")
async def get_test_sample():
    """Returns sample images from the repository for 1-click immediate testing."""
    sample_files = [
        os.path.join(BASE_DIR, "runs", "detect", "predict", "test_img.jpg"),
        os.path.join(BASE_DIR, "plate_samples", "plate_100.jpg")
    ]
    for s_path in sample_files:
        if os.path.exists(s_path):
            with open(s_path, "rb") as f:
                b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("utf-8")
                return {"success": True, "filename": os.path.basename(s_path), "image": b64}
    return {"success": False, "error": "No test samples found"}
