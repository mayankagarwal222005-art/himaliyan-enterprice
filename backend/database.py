import os
import json
import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))

def get_current_ist_time() -> datetime:
    """Returns current real time in Indian Standard Time (IST)."""
    return datetime.now(IST_TIMEZONE)

def format_ist_datetime(dt: datetime) -> str:
    """Formats datetime cleanly in Indian format: '15 Nov 2026, 11:20:45 PM IST'"""
    return dt.strftime("%d %b %Y, %I:%M:%S %p IST")

def parse_ist_datetime(dt_str: str) -> Optional[datetime]:
    """Parses formatted IST datetime string back into datetime object."""
    if not dt_str or dt_str == "-" or dt_str == "None":
        return None
    try:
        # Strip trailing ' IST' if present
        clean_str = dt_str.replace(" IST", "").strip()
        dt_naive = datetime.strptime(clean_str, "%d %b %Y, %I:%M:%S %p")
        return dt_naive.replace(tzinfo=IST_TIMEZONE)
    except Exception:
        try:
            # Fallback for standard ISO or CSV format: 'YYYY-MM-DD HH:MM:SS'
            dt_naive = datetime.strptime(dt_str.strip(), "%Y-%m-%d %H:%M:%S")
            return dt_naive.replace(tzinfo=IST_TIMEZONE)
        except Exception:
            return None

def calculate_duration_str(start_dt: datetime, end_dt: datetime) -> str:
    """Calculates human-readable duration between two datetimes (e.g. '2 hrs 15 mins 30 secs')."""
    total_seconds = int(abs((end_dt - start_dt).total_seconds()))
    if total_seconds < 60:
        return f"{total_seconds} secs"
    
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours} hr{'s' if hours > 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} min{'s' if minutes > 1 else ''}")
    if seconds > 0 and days == 0 and hours == 0:
        parts.append(f"{seconds} sec{'s' if seconds > 1 else ''}")
        
    return " ".join(parts) if parts else "0 secs"


class VehicleDatabase:
    """Thread-safe persistent database for vehicle entry and exit tracking."""
    
    def __init__(self, data_file: str = "plate_database.json", csv_file: str = "vehicle_log.csv"):
        self.data_file = data_file
        self.csv_file = csv_file
        self.records: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        """Loads records from JSON file or initializes from existing CSV."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    self.records = json.load(f)
                    return
            except Exception as e:
                print(f"[DB] Error loading {self.data_file}: {e}")
        
        # If JSON doesn't exist, try importing from vehicle_log.csv
        self.records = []
        if os.path.exists(self.csv_file):
            try:
                with open(self.csv_file, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    counter = 1
                    for row in reader:
                        plate = (row.get("License Plate") or row.get("plate_number") or "").strip().upper()
                        if not plate or plate == "SCANNING":
                            continue
                        status_raw = (row.get("Status") or "IN").strip().upper()
                        ts_raw = (row.get("Timestamp") or "").strip()
                        
                        dt = parse_ist_datetime(ts_raw) or get_current_ist_time()
                        formatted_ts = format_ist_datetime(dt)
                        
                        status = "INSIDE" if status_raw in ("IN", "INSIDE") else "EXITED"
                        
                        rec = {
                            "id": f"REC-{counter:04d}",
                            "plate_number": plate,
                            "status": status,
                            "entry_time": formatted_ts if status == "INSIDE" else formatted_ts,
                            "exit_time": formatted_ts if status == "EXITED" else "-",
                            "duration": "Completed" if status == "EXITED" else "Currently Inside",
                            "confidence": 0.92,
                            "source": "Imported Log",
                            "notes": "Historical entry",
                            "created_at": formatted_ts
                        }
                        self.records.append(rec)
                        counter += 1
                self._save()
            except Exception as e:
                print(f"[DB] Error importing initial CSV: {e}")

    def _save(self):
        """Persists records to both JSON and updated vehicle_log.csv."""
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.records, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[DB] Error saving JSON: {e}")

        try:
            # Sync to CSV
            with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Record ID", "License Plate", "Status", "Entry Time (IST)", "Exit Time (IST)", "Stay Duration", "Confidence", "Source"])
                for r in self.records:
                    writer.writerow([
                        r.get("id", ""),
                        r.get("plate_number", ""),
                        r.get("status", ""),
                        r.get("entry_time", ""),
                        r.get("exit_time", ""),
                        r.get("duration", ""),
                        f"{r.get('confidence', 0.0):.2f}",
                        r.get("source", "")
                    ])
        except Exception as e:
            print(f"[DB] Error saving CSV: {e}")

    def process_plate_event(self, plate_number: str, confidence: float = 0.90, source: str = "Camera", mode: str = "auto") -> Dict[str, Any]:
        """
        Core logic for vehicle entry/exit tracking.
        - plate_number: Cleaned uppercase plate (e.g. KA02HN1826)
        - mode:
          - 'auto': If vehicle is currently INSIDE, mark as EXITED (calculate duration). Otherwise, record new ENTRY.
          - 'entry': Force record as new vehicle entry.
          - 'exit': Force mark existing vehicle as exited.
        """
        plate_number = plate_number.strip().upper()
        current_time = get_current_ist_time()
        current_time_str = format_ist_datetime(current_time)
        
        # Look for an active "INSIDE" session for this vehicle
        active_record = None
        for r in reversed(self.records):
            if r.get("plate_number") == plate_number and r.get("status") == "INSIDE":
                active_record = r
                break

        # Decision on whether to Check Out (Exit) or Check In (Enter)
        is_exit = False
        if mode == "exit":
            is_exit = True
        elif mode == "entry":
            is_exit = False
        else: # auto
            if active_record is not None:
                # If seen within 10 seconds of entering, consider it same entry pass
                entry_dt = parse_ist_datetime(active_record.get("entry_time"))
                if entry_dt:
                    diff_secs = (current_time - entry_dt).total_seconds()
                    if diff_secs < 8:
                        # Too quick, just update confidence if better
                        if confidence > active_record.get("confidence", 0.0):
                            active_record["confidence"] = confidence
                            self._save()
                        return {
                            "action": "ALREADY_INSIDE",
                            "record": active_record,
                            "message": f"Vehicle {plate_number} is already recorded inside."
                        }
                is_exit = True
            else:
                is_exit = False

        if is_exit:
            # Handle Exit
            if active_record:
                entry_dt = parse_ist_datetime(active_record.get("entry_time"))
                if entry_dt:
                    duration_str = calculate_duration_str(entry_dt, current_time)
                else:
                    duration_str = "Unknown"

                active_record["status"] = "EXITED"
                active_record["exit_time"] = current_time_str
                active_record["duration"] = duration_str
                if confidence > active_record.get("confidence", 0.0):
                    active_record["confidence"] = confidence
                
                self._save()
                return {
                    "action": "EXIT",
                    "record": active_record,
                    "message": f"Vehicle {plate_number} Exited. Total Stay Duration: {duration_str}"
                }
            else:
                # Exiting without prior active entry record
                new_id = f"REC-{len(self.records)+1:04d}"
                new_rec = {
                    "id": new_id,
                    "plate_number": plate_number,
                    "status": "EXITED",
                    "entry_time": "Prior Entry (Unrecorded)",
                    "exit_time": current_time_str,
                    "duration": "Direct Exit",
                    "confidence": confidence,
                    "source": source,
                    "notes": "Exit logged directly",
                    "created_at": current_time_str
                }
                self.records.append(new_rec)
                self._save()
                return {
                    "action": "EXIT",
                    "record": new_rec,
                    "message": f"Vehicle {plate_number} Exited (Direct log)."
                }
        else:
            # Handle Entry
            new_id = f"REC-{len(self.records)+1:04d}"
            new_rec = {
                "id": new_id,
                "plate_number": plate_number,
                "status": "INSIDE",
                "entry_time": current_time_str,
                "exit_time": "-",
                "duration": "Currently Inside",
                "confidence": confidence,
                "source": source,
                "notes": "Entry recorded",
                "created_at": current_time_str
            }
            self.records.append(new_rec)
            self._save()
            return {
                "action": "ENTRY",
                "record": new_rec,
                "message": f"Vehicle {plate_number} Entered premises at {current_time_str}"
            }

    def get_all_records(self, query: str = "", status_filter: str = "") -> List[Dict[str, Any]]:
        """Returns records matching search query or status filter."""
        results = []
        q = query.strip().upper()
        s_filter = status_filter.strip().upper()
        
        for r in reversed(self.records):
            if q and q not in r.get("plate_number", "") and q not in r.get("id", ""):
                continue
            if s_filter and s_filter != "ALL":
                if r.get("status") != s_filter:
                    continue
            results.append(r)
        return results

    def get_vehicle_history(self, plate_number: str) -> Dict[str, Any]:
        """Returns complete visit history and aggregated stay metrics for a vehicle."""
        clean_plate = plate_number.strip().upper()
        matching_visits = [r for r in self.records if r.get("plate_number") == clean_plate]
        
        is_currently_inside = any(r.get("status") == "INSIDE" for r in matching_visits)
        
        # Calculate total completed stay duration in minutes/seconds
        total_seconds = 0
        for r in matching_visits:
            if r.get("status") == "EXITED":
                e_dt = parse_ist_datetime(r.get("entry_time"))
                x_dt = parse_ist_datetime(r.get("exit_time"))
                if e_dt and x_dt:
                    total_seconds += int(abs((x_dt - e_dt).total_seconds()))

        total_hours, rem_secs = divmod(total_seconds, 3600)
        total_mins, _ = divmod(rem_secs, 60)
        
        if total_hours > 0:
            cumulative_stay = f"{total_hours} hr {total_mins} mins"
        elif total_mins > 0:
            cumulative_stay = f"{total_mins} mins"
        elif total_seconds > 0:
            cumulative_stay = f"{total_seconds} secs"
        else:
            cumulative_stay = "N/A"

        return {
            "plate_number": clean_plate,
            "total_visits": len(matching_visits),
            "is_inside": is_currently_inside,
            "cumulative_stay": cumulative_stay,
            "visits": list(reversed(matching_visits))
        }

    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Calculates key metrics for the dashboard."""
        today_date_str = get_current_ist_time().strftime("%d %b %Y")
        
        total_today = 0
        currently_inside = 0
        exited_today = 0
        durations = []
        
        for r in self.records:
            entry_time = r.get("entry_time", "")
            if today_date_str in entry_time or today_date_str in r.get("created_at", ""):
                total_today += 1
                if r.get("status") == "EXITED":
                    exited_today += 1
            
            if r.get("status") == "INSIDE":
                currently_inside += 1
            elif r.get("status") == "EXITED":
                e_dt = parse_ist_datetime(r.get("entry_time"))
                x_dt = parse_ist_datetime(r.get("exit_time"))
                if e_dt and x_dt:
                    durations.append(abs((x_dt - e_dt).total_seconds()))

        avg_stay = "0 mins"
        if durations:
            avg_secs = int(sum(durations) / len(durations))
            hrs, rem = divmod(avg_secs, 3600)
            mins, _ = divmod(rem, 60)
            if hrs > 0:
                avg_stay = f"{hrs}h {mins}m"
            else:
                avg_stay = f"{max(1, mins)} mins"

        return {
            "total_today": total_today if total_today > 0 else len(self.records),
            "currently_inside": currently_inside,
            "exited_today": exited_today,
            "avg_stay_duration": avg_stay,
            "current_ist_time": format_ist_datetime(get_current_ist_time())
        }

    def export_excel(self) -> io.BytesIO:
        """Generates a professional Excel (.xlsx) file with purple branding and formatted columns."""
        wb = Workbook()
        ws = wb.active
        ws.title = "Vehicle Entry-Exit Records"
        
        # Ensure gridlines visible
        ws.views.sheetView[0].showGridLines = True
        
        # Purple theme colors
        header_fill = PatternFill(start_color="5B21B6", end_color="5B21B6", fill_type="solid")
        sub_header_fill = PatternFill(start_color="7C3AED", end_color="7C3AED", fill_type="solid")
        inside_fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid") # soft green
        exited_fill = PatternFill(start_color="F5F3FF", end_color="F5F3FF", fill_type="solid") # soft lavender
        
        header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
        title_font = Font(name="Segoe UI", size=14, bold=True, color="FFFFFF")
        regular_font = Font(name="Segoe UI", size=10, color="1E1B4B")
        bold_font = Font(name="Segoe UI", size=10, bold=True, color="1E1B4B")
        green_font = Font(name="Segoe UI", size=10, bold=True, color="166534")
        purple_font = Font(name="Segoe UI", size=10, bold=True, color="5B21B6")
        
        thin_border = Border(
            left=Side(style='thin', color='E2E8F0'),
            right=Side(style='thin', color='E2E8F0'),
            top=Side(style='thin', color='E2E8F0'),
            bottom=Side(style='thin', color='E2E8F0')
        )
        
        # Title Banner
        ws.merge_cells("A1:H1")
        title_cell = ws["A1"]
        title_cell.value = "PLATETRACK AI — VEHICLE ENTRY & EXIT MONITORING SYSTEM (IST)"
        title_cell.font = title_font
        title_cell.fill = header_fill
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 40
        
        # Subtitle Banner
        ws.merge_cells("A2:H2")
        sub_cell = ws["A2"]
        sub_cell.value = f"Report Generated on: {format_ist_datetime(get_current_ist_time())} | Total Records: {len(self.records)}"
        sub_cell.font = Font(name="Segoe UI", size=9, italic=True, color="FFFFFF")
        sub_cell.fill = sub_header_fill
        sub_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[2].height = 22
        
        # Headers
        headers = [
            "Record ID",
            "License Plate",
            "Status",
            "Entry Time (IST)",
            "Exit Time (IST)",
            "Stay Duration",
            "Detection Conf.",
            "Gate / Source"
        ]
        
        ws.append([]) # Row 3 blank spacing
        ws.row_dimensions[3].height = 10
        
        ws.append(headers) # Row 4
        ws.row_dimensions[4].height = 28
        
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=4, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border
            
        # Data rows
        for row_idx, r in enumerate(self.records, start=5):
            ws.row_dimensions[row_idx].height = 22
            status = r.get("status", "")
            
            row_data = [
                r.get("id", f"REC-{row_idx-4:04d}"),
                r.get("plate_number", ""),
                "INSIDE" if status == "INSIDE" else "EXITED",
                r.get("entry_time", "-"),
                r.get("exit_time", "-"),
                r.get("duration", "-"),
                f"{float(r.get('confidence', 0.0))*100:.1f}%",
                r.get("source", "Camera")
            ]
            ws.append(row_data)
            
            # Formatting cells
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="center", vertical="center")
                
                if col_idx == 2: # License Plate
                    cell.font = bold_font
                elif col_idx == 3: # Status
                    if status == "INSIDE":
                        cell.fill = inside_fill
                        cell.font = green_font
                    else:
                        cell.fill = exited_fill
                        cell.font = purple_font
                else:
                    cell.font = regular_font

        # Auto-adjust column widths
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.row in (1, 2):
                    continue
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = max(max_len + 5, 14)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    def checkout_vehicle(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Manually check out an inside vehicle."""
        for r in self.records:
            if r.get("id") == record_id and r.get("status") == "INSIDE":
                current_time = get_current_ist_time()
                current_time_str = format_ist_datetime(current_time)
                entry_dt = parse_ist_datetime(r.get("entry_time"))
                duration_str = calculate_duration_str(entry_dt, current_time) if entry_dt else "Calculated on exit"
                
                r["status"] = "EXITED"
                r["exit_time"] = current_time_str
                r["duration"] = duration_str
                self._save()
                return r
        return None

    def clear_all(self):
        """Clears all records."""
        self.records = []
        self._save()
