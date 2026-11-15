import re
import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
import base64
import os
import tempfile

class PlateDetector:
    """Robust vehicle license plate detector & OCR recognizer with Indian plate validation."""
    
    # Common Indian State Codes
    STATE_CODES = {
        "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN",
        "GA", "GJ", "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD",
        "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "PB", "PY", "RJ",
        "SK", "TN", "TR", "TS", "UK", "UP", "WB"
    }

    # Common OCR character substitutions
    LETTER_TO_DIGIT = {
        'O': '0', 'Q': '0', 'D': '0',
        'I': '1', 'L': '1', 'T': '1',
        'Z': '2',
        'E': '3',
        'A': '4',
        'S': '5',
        'G': '6', 'b': '6',
        'B': '8',
    }

    DIGIT_TO_LETTER = {
        '0': 'O',
        '1': 'I',
        '2': 'Z',
        '3': 'E',
        '4': 'A',
        '5': 'S',
        '6': 'G',
        '8': 'B',
    }

    def __init__(self, model_path: str = "best.pt"):
        self.model_path = model_path
        self.yolo_model = None
        self.ocr_reader = None
        self._load_models()

    def _load_models(self):
        """Initializes YOLO and EasyOCR models."""
        try:
            from ultralytics import YOLO
            if os.path.exists(self.model_path):
                print(f"[DETECTOR] Loading YOLO model from {self.model_path}...")
                self.yolo_model = YOLO(self.model_path)
                print("[DETECTOR] YOLO model loaded successfully.")
            else:
                print(f"[DETECTOR WARNING] YOLO weights {self.model_path} not found.")
        except Exception as e:
            print(f"[DETECTOR ERROR] YOLO initialization failed: {e}")

        try:
            import easyocr
            print("[DETECTOR] Initializing EasyOCR reader...")
            self.ocr_reader = easyocr.Reader(['en'], gpu=False)
            print("[DETECTOR] EasyOCR reader initialized successfully.")
        except Exception as e:
            print(f"[DETECTOR ERROR] EasyOCR initialization failed: {e}")

    @classmethod
    def clean_raw_text(cls, raw: str) -> str:
        """Removes spaces, punctuation, special symbols and keeps alphanumeric uppercase."""
        if not raw:
            return ""
        return re.sub(r'[^A-Z0-9]', '', raw.upper())

    @classmethod
    def normalize_indian_plate(cls, text: str) -> Tuple[str, float]:
        """
        Normalizes and applies Indian license plate heuristics:
        Standard: [2 State Letters][2 RTO Digits][1-3 Series Letters][4 Unique Digits] (e.g. KA02HN1826, DL01AB1234)
        BH Series: [2 Year Digits]BH[4 Digits][1-2 Letters] (e.g. 22BH1234AA)
        """
        cleaned = cls.clean_raw_text(text)
        if not cleaned:
            return "", 0.0

        # If it's already an exact Indian plate match:
        standard_pattern = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$')
        if standard_pattern.match(cleaned):
            return cleaned, 0.98

        bh_pattern = re.compile(r'^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$')
        if bh_pattern.match(cleaned):
            return cleaned, 0.98

        # If length is between 8 and 11, try position-based correction
        if 8 <= len(cleaned) <= 11:
            chars = list(cleaned)
            # 1. First 2 characters must be State Code letters
            for i in range(min(2, len(chars))):
                if chars[i] in cls.DIGIT_TO_LETTER:
                    chars[i] = cls.DIGIT_TO_LETTER[chars[i]]
            
            # 2. Next 2 characters (pos 2, 3) must be digits
            for i in range(2, min(4, len(chars))):
                if chars[i] in cls.LETTER_TO_DIGIT:
                    chars[i] = cls.LETTER_TO_DIGIT[chars[i]]
                    
            # 3. Last 4 characters must be digits
            for i in range(len(chars) - 4, len(chars)):
                if 0 <= i < len(chars):
                    if chars[i] in cls.LETTER_TO_DIGIT:
                        chars[i] = cls.LETTER_TO_DIGIT[chars[i]]
                        
            # 4. Middle characters between pos 4 and (len - 4) must be letters
            for i in range(4, len(chars) - 4):
                if chars[i] in cls.DIGIT_TO_LETTER:
                    chars[i] = cls.DIGIT_TO_LETTER[chars[i]]

            candidate = "".join(chars)
            if standard_pattern.match(candidate):
                return candidate, 0.92

        # If length is slightly short or contains "IND" prefix, strip "IND"
        if cleaned.startswith("IND") and len(cleaned) > 7:
            cand = cleaned[3:]
            norm, conf = cls.normalize_indian_plate(cand)
            if norm:
                return norm, conf

        # Return whatever alphanumeric text exists if at least 4 chars
        if len(cleaned) >= 4:
            return cleaned, 0.75
            
        return cleaned, 0.50

    def preprocess_crop(self, crop: np.ndarray) -> List[np.ndarray]:
        """Applies various image filters to enhance plate contrast and readability."""
        if crop is None or crop.size == 0:
            return []

        h, w = crop.shape[:2]
        # Resize to at least 200px width for OCR clarity
        scale = max(2.0, 240.0 / max(1, w))
        resized = cv2.resize(crop, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
        
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        
        # CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

        # Bilateral filtering to smooth noise while keeping character edges sharp
        filtered = cv2.bilateralFilter(gray, 9, 75, 75)
        filtered_bgr = cv2.cvtColor(filtered, cv2.COLOR_GRAY2BGR)

        # Otsu thresholding
        _, thresh = cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thresh_bgr = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)

        return [resized, enhanced_bgr, filtered_bgr, thresh_bgr]

    def read_plate_text(self, crop: np.ndarray) -> Tuple[str, float]:
        """Runs OCR on preprocessed crops and returns highest confidence plate number."""
        if self.ocr_reader is None or crop is None or crop.size == 0:
            return "", 0.0

        candidates = []
        crops_to_test = self.preprocess_crop(crop)
        if not crops_to_test:
            crops_to_test = [crop]

        for p_crop in crops_to_test:
            try:
                results = self.ocr_reader.readtext(p_crop, detail=1, paragraph=False)
                for bbox, text, score in results:
                    norm_plate, pattern_conf = self.normalize_indian_plate(text)
                    if norm_plate and len(norm_plate) >= 4:
                        combined_conf = float(score) * 0.5 + pattern_conf * 0.5
                        candidates.append((norm_plate, combined_conf))
            except Exception as e:
                pass

        if not candidates:
            # Fallback direct read on raw crop
            try:
                results = self.ocr_reader.readtext(crop, detail=1)
                for bbox, text, score in results:
                    norm_plate, _ = self.normalize_indian_plate(text)
                    if norm_plate:
                        candidates.append((norm_plate, float(score)))
            except Exception:
                pass

        if candidates:
            # Pick highest confidence candidate
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0]
            
        return "", 0.0

    def detect_and_recognize(self, image: np.ndarray) -> Dict[str, Any]:
        """
        Full detection pipeline:
        1. Runs YOLO on image to find license plate bounding boxes.
        2. Crops detected plate regions and runs OCR.
        3. Draws purple & white annotations on output image.
        4. Returns detected plates and base64 annotated image.
        """
        if image is None or image.size == 0:
            return {"success": False, "error": "Invalid image"}

        h, w = image.shape[:2]
        annotated_image = image.copy()
        detected_plates = []

        boxes = []
        if self.yolo_model is not None:
            try:
                results = self.yolo_model(image, conf=0.15, verbose=False)
                if results and len(results) > 0 and results[0].boxes is not None:
                    for b in results[0].boxes:
                        x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
                        conf = float(b.conf[0])
                        boxes.append((x1, y1, x2, y2, conf))
            except Exception as e:
                print(f"[DETECTOR] YOLO error: {e}")

        # If YOLO found no boxes, check if whole image is a plate crop (e.g. uploaded plate photo)
        if not boxes:
            plate_text, ocr_conf = self.read_plate_text(image)
            if plate_text:
                detected_plates.append({
                    "plate_number": plate_text,
                    "confidence": ocr_conf,
                    "box": [0, 0, w, h]
                })
                # Draw full box
                cv2.rectangle(annotated_image, (2, 2), (w-2, h-2), (182, 33, 91), 3) # Purple BGR: (91, 33, 182)

        for x1, y1, x2, y2, det_conf in boxes:
            # Add safe padding
            pad_x = int((x2 - x1) * 0.10)
            pad_y = int((y2 - y1) * 0.10)
            crop_x1 = max(0, x1 - pad_x)
            crop_y1 = max(0, y1 - pad_y)
            crop_x2 = min(w, x2 + pad_x)
            crop_y2 = min(h, y2 + pad_y)

            crop = image[crop_y1:crop_y2, crop_x1:crop_x2]
            plate_text, ocr_conf = self.read_plate_text(crop)
            
            final_conf = max(det_conf, ocr_conf) if plate_text else det_conf

            if plate_text:
                detected_plates.append({
                    "plate_number": plate_text,
                    "confidence": round(final_conf, 2),
                    "box": [x1, y1, x2, y2]
                })

            # Draw Purple bounding box (RGB: #7C3AED -> BGR: (237, 58, 124))
            box_color = (237, 58, 124) if plate_text else (180, 180, 180)
            cv2.rectangle(annotated_image, (x1, y1), (x2, y2), box_color, 2)
            
            # Draw label banner
            label_text = plate_text if plate_text else "Plate Scanning..."
            (lbl_w, lbl_h), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            
            # Label background banner (Dark Royal Purple: BGR: 76, 29, 149)
            lbl_y1 = max(0, y1 - lbl_h - 10)
            lbl_y2 = y1
            cv2.rectangle(annotated_image, (x1, lbl_y1), (x1 + lbl_w + 16, lbl_y2), (149, 29, 76), -1)
            cv2.putText(annotated_image, label_text, (x1 + 8, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # Convert annotated image to base64 for direct browser rendering
        _, buffer = cv2.imencode('.jpg', annotated_image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        annotated_b64 = "data:image/jpeg;base64," + base64.b64encode(buffer).decode('utf-8')

        return {
            "success": True,
            "plates": detected_plates,
            "annotated_image": annotated_b64,
            "plates_count": len(detected_plates)
        }

    def process_video(self, video_path: str, max_frames: int = 120, sample_interval: int = 5) -> List[Dict[str, Any]]:
        """
        Processes video frames to extract all visible license plates with timestamps.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_idx = 0
        processed_count = 0
        plate_hits = {} # plate -> highest confidence

        try:
            while cap.isOpened() and processed_count < max_frames:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % sample_interval == 0:
                    res = self.detect_and_recognize(frame)
                    for p in res.get("plates", []):
                        num = p.get("plate_number")
                        conf = p.get("confidence", 0.0)
                        if num:
                            if num not in plate_hits or conf > plate_hits[num]:
                                plate_hits[num] = conf
                    processed_count += 1
                frame_idx += 1
        finally:
            cap.release()

        return [{"plate_number": k, "confidence": v} for k, v in plate_hits.items()]
