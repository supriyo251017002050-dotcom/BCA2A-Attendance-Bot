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
        """Read students.json and return a dict of {id: name}."""
        try:
            with open("students.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("students", {})
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
        """Get the daily sheet, creating it if needed. Returns (worksheet, created)."""
        name = self._day_sheet_name(target_date)
        try:
            ws = self.ss.worksheet(name)
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
        
        ws.update(f"A3:{col_end_ltr}3", [headers])
        ws.format(f"A3:{col_end_ltr}3", {
            "textFormat": {"bold": True, "fontSize": 10},
            "backgroundColor": COLOR_HEADER_BLUE,
            "horizontalAlignment": "CENTER",
        })

        # Student rows
        if students:
            rows = []
            for i, (sid, name) in enumerate(students.items(), start=1):
                row = [str(i), sid, name]
                # Default "A" for all subjects
                row.extend(["A"] * len(slots))
                rows.append(row)
                
            num_rows = len(rows)
            row_start = 4
            row_end = 3 + num_rows
            
            ws.update(f"A{row_start}:{col_end_ltr}{row_end}", rows)
            
            # Format subject cells as red
            if len(slots) > 0:
                subj_start_ltr = _col_letter(4)
                ws.format(f"{subj_start_ltr}{row_start}:{col_end_ltr}{row_end}", {
                    "backgroundColor": COLOR_ABSENT_RED,
                    "horizontalAlignment": "CENTER",
                })

        logger.info(f"Daily sheet initialized with {len(students)} students and {len(slots)} subjects.")

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
        import matplotlib.pyplot as plt
        import pandas as pd
        import os

        try:
            ws, created = self._get_or_create_sheet(target_date)
            data = ws.get_all_values()
            if len(data) < 3:
                return None
            headers = data[2]
            rows = data[3:]
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=headers)
            num_rows = len(df)
            num_cols = len(df.columns)
            fig_width = max(10, num_cols * 1.5)
            fig_height = max(2, num_rows * 0.3)
            fig, ax = plt.subplots(figsize=(fig_width, fig_height))
            ax.axis('tight')
            ax.axis('off')
            table = ax.table(cellText=df.values, colLabels=df.columns, loc='center', cellLoc='center')
            table.auto_set_font_size(False)
            table.set_fontsize(10)
            table.scale(1, 1.5)
            for (row, col), cell in table.get_celld().items():
                if row == 0:
                    cell.set_facecolor('#d9ead3')
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

