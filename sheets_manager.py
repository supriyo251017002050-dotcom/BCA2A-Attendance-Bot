import json
import logging
import re
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

import config
from routine import get_day_name, get_teaching_slots

logger = logging.getLogger(__name__)

# ── Styling colors ─────────────────────────────────────────────────────────────
COLOR_HEADER_BLUE   = {"red": 0.8, "green": 0.9, "blue": 1.0}
COLOR_DATE_YELLOW   = {"red": 1.0, "green": 0.95, "blue": 0.6}
COLOR_PRESENT_GREEN = {"red": 0.8, "green": 1.0, "blue": 0.8}
COLOR_ABSENT_RED    = {"red": 1.0, "green": 0.8, "blue": 0.8}


def _col_letter(n: int) -> str:
    """Convert 1-based column index to letter (1=A, 26=Z, 27=AA)."""
    string = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        string = chr(65 + remainder) + string
    return string


class SheetsManager:
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        self.gc = gspread.authorize(creds)
        self.ss = self.gc.open_by_key(spreadsheet_id)

    # ── Students ─────────────────────────────────────────────────────────────────

    def get_students(self) -> dict[str, str]:
        """Read students.json and return a dict of {id: name} sorted numerically by ID."""
        try:
            with open("students.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                raw = data.get("students", {})
                # Sort numerically by student ID
                return dict(sorted(raw.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]))
        except FileNotFoundError:
            logger.warning("students.json not found!")
            return {}
        except Exception as e:
            logger.error(f"Error reading students.json: {e}")
            return {}

    def get_student_name(self, student_id: str) -> str | None:
        """Return the student's name for a given ID, or None if not found."""
        return self.get_students().get(student_id)

    def is_valid_student(self, student_id: str) -> bool:
        """Check if a student ID exists in the roster."""
        return student_id in self.get_students()

    # ── Sheet helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _day_sheet_name(target_date: date) -> str:
        return target_date.strftime("%d-%m-%Y")  # e.g. "01-08-2026"

    def _get_or_create_sheet(self, target_date: date) -> tuple[gspread.Worksheet, bool]:
        """Get the daily sheet, creating or syncing it. Returns (worksheet, created)."""
        name = self._day_sheet_name(target_date)
        try:
            ws = self.ss.worksheet(name)
            self._sync_sheet_students(ws, target_date)
            return ws, False
        except gspread.WorksheetNotFound:
            logger.info(f"Creating new daily sheet: {name}")
            ws = self.ss.add_worksheet(title=name, rows=150, cols=20)
            self._init_sheet(ws, target_date)
            return ws, True

    def _init_sheet(self, ws: gspread.Worksheet, target_date: date):
        """Write headers, date, subjects, and student list into a daily sheet."""
        students = self.get_students()
        day_name = get_day_name(target_date)
        date_str = target_date.strftime("%d/%m/%Y")
        slots = get_teaching_slots(target_date)
        
        # Row 1 & 2
        ws.update("A1:B2", [
            ["DATE", ""],
            [date_str, day_name]
        ])
        
        # Row 3 headers
        headers = ["Sl NO", "Student_ID", "Student_NAME"]
        for slot in slots:
            subj = slot['subject']
            tchr = slot['teacher']
            if tchr and tchr != "TBA":
                headers.append(f"{subj} ({tchr})")
            else:
                headers.append(subj)
        
        num_cols = len(headers)
        col_end_ltr = _col_letter(num_cols)
        
        # Format and merge top headers (Row 1 & 2)
        if num_cols > 1:
            try:
                ws.merge_cells(f"B1:{col_end_ltr}1")
                ws.merge_cells(f"B2:{col_end_ltr}2")
                
                ws.format(f"A1:A2", {
                    "textFormat": {"bold": True, "fontSize": 11},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "backgroundColor": COLOR_DATE_YELLOW
                })
                ws.format(f"B1:{col_end_ltr}2", {
                    "textFormat": {"bold": True, "fontSize": 12},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "backgroundColor": COLOR_DATE_YELLOW
                })
            except Exception as e:
                logger.error(f"Error formatting top headers: {e}")
        
        ws.update(f"A3:{col_end_ltr}3", [headers])
        ws.format(f"A3:{col_end_ltr}3", {
            "textFormat": {"bold": True, "fontSize": 10},
            "backgroundColor": COLOR_HEADER_BLUE,
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
        })

        # Student rows (sorted by ID, default empty "")
        if students:
            rows = []
            for i, (sid, name) in enumerate(students.items(), start=1):
                row = [str(i), sid, name]
                # Default empty "" for all subjects (unmarked)
                row.extend([""] * len(slots))
                rows.append(row)
                
            num_rows = len(rows)
            row_start = 4
            row_end = 3 + num_rows
            
            ws.update(f"A{row_start}:{col_end_ltr}{row_end}", rows)
            
            # Apply borders to the entire table
            try:
                ws.format(f"A1:{col_end_ltr}{row_end}", {
                    "borders": {
                        "top": {"style": "SOLID"},
                        "bottom": {"style": "SOLID"},
                        "left": {"style": "SOLID"},
                        "right": {"style": "SOLID"}
                    }
                })
            except Exception as e:
                logger.error(f"Error applying borders in _init_sheet: {e}")

        logger.info(f"Daily sheet initialized with {len(students)} students and {len(slots)} subjects.")

    def _sync_sheet_students(self, ws: gspread.Worksheet, target_date: date):
        """Sync existing sheet student names & order with students.json while preserving marked attendance."""
        try:
            students = self.get_students()
            if not students:
                return

            slots = get_teaching_slots(target_date)
            num_subjects = len(slots)
            col_end_ltr = _col_letter(3 + num_subjects)

            # Read existing values
            all_values = ws.get_all_values()
            
            # If the sheet is empty or headers are missing (e.g., user cleared it manually)
            if len(all_values) < 3:
                ws.clear()
                self._init_sheet(ws, target_date)
                return
                
            existing_marks = {}
            if len(all_values) >= 4:
                for r in all_values[3:]:
                    if len(r) >= 2:
                        sid = r[1]
                        marks = r[3:3+num_subjects] if len(r) > 3 else []
                        existing_marks[sid] = marks

            # Build updated rows
            rows = []
            for i, (sid, name) in enumerate(students.items(), start=1):
                prev_marks = existing_marks.get(sid, [])
                # Fill previous marks or blank ""
                subject_cells = []
                for j in range(num_subjects):
                    val = prev_marks[j] if j < len(prev_marks) else ""
                    # Keep P or A if previously marked, otherwise blank
                    subject_cells.append(val if val in ("P", "A") else "")
                
                row = [str(i), sid, name] + subject_cells
                rows.append(row)

            # Clear old rows and write fresh sorted roster
            num_rows = len(rows)
            row_start = 4
            row_end = 3 + num_rows

            ws.update(f"A{row_start}:{col_end_ltr}{row_end}", rows)
            
            # Reapply borders in case new students were added
            try:
                ws.format(f"A1:{col_end_ltr}{row_end}", {
                    "borders": {
                        "top": {"style": "SOLID"},
                        "bottom": {"style": "SOLID"},
                        "left": {"style": "SOLID"},
                        "right": {"style": "SOLID"}
                    }
                })
            except Exception as e:
                logger.error(f"Error applying borders in _sync_sheet_students: {e}")
                
            logger.info(f"Synced {num_rows} students in sheet {ws.title}")
        except Exception as e:
            logger.error(f"Error syncing sheet students: {e}")

    def _student_row(self, ws: gspread.Worksheet, student_id: str) -> int | None:
        """Return the 1-based row index for a student ID in the daily sheet, or None."""
        col_b = ws.col_values(2)  # Column B is Student_ID
        try:
            return col_b.index(student_id) + 1
        except ValueError:
            return None

    # ── Public API ───────────────────────────────────────────────────────────────

    def initialize_date(self, target_date: date) -> None:
        """
        Ensure a daily sheet exists and is formatted.
        """
        self._get_or_create_sheet(target_date)

    def mark_attendance(
        self, student_id: str, target_date: date, mark: str = "P"
    ) -> tuple[bool, str]:
        """
        Mark a student P or A for all subjects on a given date.
        Returns (success: bool, message: str).
        """
        students = self.get_students()
        if student_id not in students:
            return False, f"Student ID `{student_id}` not found in the list."

        try:
            ws, created = self._get_or_create_sheet(target_date)
            row = self._student_row(ws, student_id)

            if row is None:
                return False, f"Student `{student_id}` missing from sheet."

            # Find how many subject columns there are
            headers = ws.row_values(3)
            num_subjects = len(headers) - 3
            
            if num_subjects == 0:
                return False, "No subjects scheduled for this day."
                
            col_start_ltr = _col_letter(4)
            col_end_ltr = _col_letter(3 + num_subjects)
            
            # Update all subjects to mark
            marks = [[mark] * num_subjects]
            ws.update(f"{col_start_ltr}{row}:{col_end_ltr}{row}", marks)
            
            ws.format(f"{col_start_ltr}{row}:{col_end_ltr}{row}", {
                "backgroundColor": COLOR_PRESENT_GREEN if mark == "P" else COLOR_ABSENT_RED,
                "horizontalAlignment": "CENTER",
            })

            logger.info(f"Marked {student_id} as {mark} for all subjects on {target_date}")
            return True, "OK"

        except Exception as e:
            logger.error(f"mark_attendance error: {e}")
            return False, str(e)

    def reset_attendance(self, target_date: date) -> tuple[bool, str]:
        """Clear all attendance marks for the given date's sheet."""
        try:
            ws, created = self._get_or_create_sheet(target_date)
            headers = ws.row_values(3)
            num_subjects = len(headers) - 3
            if num_subjects <= 0:
                return False, "No subjects scheduled for this day."
                
            students = self.get_students()
            if not students:
                return False, "No students found."
                
            num_students = len(students)
            col_start_ltr = _col_letter(4)
            col_end_ltr = _col_letter(3 + num_subjects)
            row_start = 4
            row_end = 3 + num_students
            
            # Create a 2D array of empty strings
            marks = [[""] * num_subjects for _ in range(num_students)]
            ws.update(f"{col_start_ltr}{row_start}:{col_end_ltr}{row_end}", marks)
            
            # Reset format to white background
            ws.format(f"{col_start_ltr}{row_start}:{col_end_ltr}{row_end}", {
                "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                "horizontalAlignment": "CENTER",
            })
            
            logger.info(f"Reset attendance table for {target_date}")
            return True, "Table reset successfully."
            
        except Exception as e:
            logger.error(f"reset_attendance error: {e}")
            return False, str(e)

    def get_daily_attendance_data(self, target_date: date) -> dict | None:
        """
        Returns a structured dict of the current day's sheet for interactive editing.
        Format:
        {
            "subjects": ["Math", "Physics", ...],
            "students": [
                {"id": "251017002050", "name": "Alice"},
                ...
            ],
            "attendance": {
                "251017002050": ["P", "", "A", ...],
                ...
            }
        }
        """
        try:
            ws, created = self._get_or_create_sheet(target_date)
            all_values = ws.get_all_values()
            
            if len(all_values) < 3:
                return None
                
            headers = all_values[2]
            subjects = headers[3:]
            
            students = []
            attendance = {}
            
            for row in all_values[3:]:
                if len(row) >= 2:
                    sid = row[1]
                    name = row[2] if len(row) > 2 else "Unknown"
                    marks = row[3:]
                    # Pad marks if missing
                    while len(marks) < len(subjects):
                        marks.append("")
                    # Truncate if too many
                    marks = marks[:len(subjects)]
                        
                    students.append({"id": sid, "name": name})
                    attendance[sid] = marks
                    
            return {
                "subjects": subjects,
                "students": students,
                "attendance": attendance
            }
        except Exception as e:
            logger.error(f"get_daily_attendance_data error: {e}")
            return None

    def save_daily_attendance_data(self, target_date: date, session_data: dict) -> tuple[bool, str]:
        """
        Takes the modified attendance dict from Telegram and writes it back to the sheet in one API call.
        """
        try:
            ws, created = self._get_or_create_sheet(target_date)
            
            num_subjects = len(session_data["subjects"])
            num_students = len(session_data["students"])
            if num_subjects == 0 or num_students == 0:
                return False, "No data to save."
                
            col_start_ltr = _col_letter(4)
            col_end_ltr = _col_letter(3 + num_subjects)
            row_start = 4
            row_end = 3 + num_students
            
            # Reconstruct the 2D array of marks matching the row order in session_data["students"]
            marks_2d = []
            for student in session_data["students"]:
                sid = student["id"]
                marks = session_data["attendance"].get(sid, [""] * num_subjects)
                marks_2d.append(marks)
                
            ws.update(f"{col_start_ltr}{row_start}:{col_end_ltr}{row_end}", marks_2d)
            
            # Formatting request batch
            requests = []
            
            # 1. Header wrap text (in case this sheet was created before we added it to _init_sheet)
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": 2,
                        "endRowIndex": 3,
                        "startColumnIndex": 3,
                        "endColumnIndex": 3 + num_subjects
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "WRAP",
                            "verticalAlignment": "MIDDLE",
                            "horizontalAlignment": "CENTER",
                            "textFormat": {"bold": True, "fontSize": 10},
                            "backgroundColor": COLOR_HEADER_BLUE
                        }
                    },
                    "fields": "userEnteredFormat(wrapStrategy,verticalAlignment,horizontalAlignment,textFormat,backgroundColor)"
                }
            })
            
            # 2. Update Column Widths for Subject columns to comfortably fit text
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "COLUMNS",
                        "startIndex": 3,
                        "endIndex": 3 + num_subjects
                    },
                    "properties": {"pixelSize": 140},
                    "fields": "pixelSize"
                }
            })
            
            # 3. Apply colors to individual P/A marks
            for r_idx, marks in enumerate(marks_2d):
                for c_idx, mark in enumerate(marks):
                    if mark == "P":
                        color = COLOR_PRESENT_GREEN
                    elif mark == "A":
                        color = COLOR_ABSENT_RED
                    else:
                        color = {"red": 1.0, "green": 1.0, "blue": 1.0} # White
                        
                    requests.append({
                        "repeatCell": {
                            "range": {
                                "sheetId": ws.id,
                                "startRowIndex": 3 + r_idx,
                                "endRowIndex": 4 + r_idx,
                                "startColumnIndex": 3 + c_idx,
                                "endColumnIndex": 4 + c_idx
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": color,
                                    "horizontalAlignment": "CENTER"
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment)"
                        }
                    })
            
            # Apply all formatting in one batch update
            self.ss.batch_update({"requests": requests})
            
            logger.info(f"Saved interactive attendance for {target_date}")
            return True, "Attendance saved successfully."
        except Exception as e:
            logger.error(f"save_daily_attendance_data error: {e}")
            return False, str(e)

    def get_day_summary(self, target_date: date) -> dict | None:
        """
        Return a dict with present/absent lists for a given date.
        Student is 'present' if they are present for at least one subject.
        """
        try:
            ws, created = self._get_or_create_sheet(target_date)
            if created:
                # If we just created it, it means no data was there before
                return None

            ids = ws.col_values(2)[3:]   # skip headers
            names = ws.col_values(3)[3:]
            
            # Get all subject columns
            headers = ws.row_values(3)
            num_subjects = len(headers) - 3
            if num_subjects == 0:
                return {"present": [], "absent": [], "total": 0, "date": self._day_sheet_name(target_date)}
                
            col_start_ltr = _col_letter(4)
            col_end_ltr = _col_letter(3 + num_subjects)
            row_end = 3 + len(ids)
            
            # Fetch all attendance cells
            attendance_data = ws.get(f"{col_start_ltr}4:{col_end_ltr}{row_end}")
            
            present, absent = [], []
            for i, sid in enumerate(ids):
                if not sid:
                    continue
                name = names[i] if i < len(names) else "Unknown"
                
                # Check if 'P' is in any of the student's cells
                row_marks = attendance_data[i] if i < len(attendance_data) else []
                if "P" in row_marks:
                    present.append((sid, name))
                else:
                    absent.append((sid, name))

            return {
                "present": present,
                "absent":  absent,
                "total":   len(present) + len(absent),
                "date":    target_date.strftime("%d %B %Y  (%A)"),
            }

        except gspread.WorksheetNotFound:
            return None
        except Exception as e:
            logger.error(f"get_day_summary error: {e}")
            return None

    def get_student_report(self, student_id: str) -> list[tuple[str, str]]:
        """
        Return a list of (date_str, 'P' or 'A') for a student across all daily sheets.
        Returns empty list if none found.
        """
        records = []
        try:
            for ws in self.ss.worksheets():
                title = ws.title
                # Only check daily sheets like DD-MM-YYYY
                if re.match(r"^\d{2}-\d{2}-\d{4}$", title):
                    row = self._student_row(ws, student_id)
                    if row:
                        # Get first subject mark for simplicity
                        mark = ws.acell(f"D{row}").value
                        records.append((title, mark or "A"))
        except Exception as e:
            logger.error(f"get_student_report error: {e}")

        # Sort by date
        records.sort(key=lambda x: x[0])
        return records


    def generate_sheet_image(self, target_date: date) -> str | None:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import pandas as pd
        import os

        try:
            ws, created = self._get_or_create_sheet(target_date)
            data = ws.get_all_values()
            if len(data) < 3:
                return None
                
            # Pad all rows to the same length so pandas DataFrame doesn't complain
            num_cols = max(len(r) for r in data)
            for r in data:
                while len(r) < num_cols:
                    r.append('')
                    
            df = pd.DataFrame(data)
            num_rows = len(df)
            
            fig_width = max(10, num_cols * 1.5)
            fig_height = max(2, num_rows * 0.3)
            fig, ax = plt.subplots(figsize=(fig_width, fig_height))
            ax.axis('tight')
            ax.axis('off')
            
            # Draw the table with no column headers (they are included in df.values)
            table = ax.table(cellText=df.values, loc='center', cellLoc='center')
            table.auto_set_font_size(False)
            table.set_fontsize(10)
            table.scale(1, 1.5)
            
            # Format rows and cells
            for (row, col), cell in table.get_celld().items():
                if row in [0, 1]:
                    # Date & Day header (Yellow)
                    cell.set_facecolor('#fff2cc')
                    cell.set_text_props(weight='bold')
                elif row == 2:
                    # Column headers (Blue)
                    cell.set_facecolor('#cfe2f3')
                    cell.set_text_props(weight='bold')
                elif cell.get_text().get_text() == 'P':
                    cell.set_facecolor('#d9ead3')
                elif cell.get_text().get_text() == 'A':
                    cell.set_facecolor('#f4cccc')
                    
            filename = f'sheet_{self._day_sheet_name(target_date)}.png'
            filepath = os.path.join(os.getcwd(), filename)
            plt.savefig(filepath, bbox_inches='tight', dpi=150)
            plt.close()
            return filepath
        except Exception as e:
            logger.error(f'generate_sheet_image error: {e}')
            return None

    def get_backup_excel(self) -> bytes:
        """Export the entire spreadsheet as an Excel file (bytes)."""
        from gspread.utils import ExportFormat
        return self.ss.export(ExportFormat.EXCEL)

