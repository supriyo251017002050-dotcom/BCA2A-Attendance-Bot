"""
routine.py — Class timetable for SOF BCA2A, 3rd Semester
             Techno India University, West Bengal

Extracted from the official routine image provided by the user.

Time Slots:
  Slot 1 : 09:00 – 09:50
  Slot 2 : 09:50 – 10:40
  Slot 3 : 10:40 – 11:30
  RECESS : 11:30 – 12:00
  Slot 4 : 12:00 – 12:50
  Slot 5 : 12:50 – 13:40
  Slot 6 : 13:40 – 14:30
"""

from datetime import date

# ── Time slot label map ───────────────────────────────────────────────────────
SLOT_TIMES = {
    1:        "9:00 AM – 9:50 AM",
    2:        "9:50 AM – 10:40 AM",
    3:        "10:40 AM – 11:30 AM",
    "RECESS": "11:30 AM – 12:00 PM",
    4:        "12:00 PM – 12:50 PM",
    5:        "12:50 PM – 1:40 PM",
    6:        "1:40 PM – 2:30 PM",
}

# ── Weekly timetable ──────────────────────────────────────────────────────────
# Each entry: slot, subject, teacher code, room
ROUTINE = {
    "Monday": [],  # Day off

    "Tuesday": [
        {"slot": 1,        "subject": "Professional Elective I", "teacher": "TBA",  "room": "LT-207"},
        {"slot": 2,        "subject": "Discrete Structures",                           "teacher": "SB",   "room": "LT-207"},
        {"slot": 3,        "subject": "Discrete Structures",                           "teacher": "SB",   "room": "LT-207"},
        {"slot": "RECESS", "subject": "RECESS",                                        "teacher": "",     "room": ""},
        {"slot": 4,        "subject": "Database Management Systems",                   "teacher": "SGR",  "room": "LT-207"},
        {"slot": 5,        "subject": "Aptitude and Reasoning Ability",                "teacher": "RK",   "room": "LT-207"},
        {"slot": 6,        "subject": "Soft Skills",                                   "teacher": "TS",   "room": "LT-207"},
    ],

    "Wednesday": [
        {"slot": 1,        "subject": "—",                                              "teacher": "",     "room": ""},
        {"slot": 2,        "subject": "—",                                              "teacher": "",     "room": ""},
        {"slot": 3,        "subject": "—",                                              "teacher": "",     "room": ""},
        {"slot": "RECESS", "subject": "RECESS",                                         "teacher": "",     "room": ""},
        {"slot": 4,        "subject": "Professional Elective I",  "teacher": "TBA",  "room": "LT-207"},
        {"slot": 5,        "subject": "Professional Elective I",  "teacher": "TBA",  "room": "LT-207"},
        {"slot": 6,        "subject": "CASD (Disaster Management)",                     "teacher": "TBA",  "room": "LT-207"},
    ],

    "Thursday": [
        {"slot": 1,        "subject": "Professional Elective I LAB",   "teacher": "TBA", "room": "LAB 18"},
        {"slot": 2,        "subject": "Professional Elective I LAB",   "teacher": "TBA", "room": "LAB 18"},
        {"slot": 3,        "subject": "Professional Elective I LAB",   "teacher": "TBA", "room": "LAB 18"},
        {"slot": "RECESS", "subject": "RECESS",                                         "teacher": "",    "room": ""},
        {"slot": 4,        "subject": "Software Engineering",                           "teacher": "TB",  "room": "LT-207"},
        {"slot": 5,        "subject": "Software Engineering",                           "teacher": "TB",  "room": "LT-207"},
        {"slot": 6,        "subject": "Discrete Structures",                            "teacher": "TBA", "room": "LT-207"},
    ],

    "Friday": [
        {"slot": 1,        "subject": "Database Management Systems",            "teacher": "ABB", "room": "LT-207"},
        {"slot": 2,        "subject": "Database Management Systems",            "teacher": "ABB", "room": "LT-207"},
        {"slot": 3,        "subject": "Software Engineering",                   "teacher": "TB",  "room": "LT-207"},
        {"slot": "RECESS", "subject": "RECESS",                                 "teacher": "",    "room": ""},
        {"slot": 4,        "subject": "IBM Master Class (Big Data Analytics)",  "teacher": "SS",  "room": "LAB 18"},
        {"slot": 5,        "subject": "IBM Master Class (Big Data Analytics)",  "teacher": "SS",  "room": "LAB 18"},
        {"slot": 6,        "subject": "IBM Master Class (Big Data Analytics)",  "teacher": "SS",  "room": "LAB 18"},
    ],

    "Saturday": [
        {"slot": 1,        "subject": "DBMS Lab",  "teacher": "RS", "room": "LAB 21"},
        {"slot": 2,        "subject": "DBMS Lab",  "teacher": "RS", "room": "LAB 21"},
        {"slot": 3,        "subject": "DBMS Lab",  "teacher": "RS", "room": "LAB 21"},
        {"slot": "RECESS", "subject": "RECESS",    "teacher": "",   "room": ""},
        {"slot": 4,        "subject": "—",          "teacher": "",   "room": ""},
        {"slot": 5,        "subject": "—",          "teacher": "",   "room": ""},
        {"slot": 6,        "subject": "—",          "teacher": "",   "room": ""},
    ],
}

# ── Public helpers ────────────────────────────────────────────────────────────

def get_day_name(target_date: date) -> str:
    """Return the weekday name for a given date (e.g. 'Tuesday')."""
    return target_date.strftime("%A")


def get_schedule_for_date(target_date: date) -> list[dict]:
    """Return the full list of slots for a given date (including RECESS)."""
    day_name = get_day_name(target_date)
    return ROUTINE.get(day_name, [])


def get_teaching_slots(target_date: date) -> list[dict]:
    """Return only the actual class slots, avoiding duplicate subjects (for double slots)."""
    slots = []
    seen_subjects = set()
    for s in get_schedule_for_date(target_date):
        if s["slot"] != "RECESS" and s["subject"] not in ("-", "", "—"):
            if s["subject"] not in seen_subjects:
                seen_subjects.add(s["subject"])
                slots.append(s)
    return slots


def format_schedule_table(target_date: date) -> str:
    """
    Return a clean text table of the day's schedule,
    formatted for a Telegram message (uses monospace).
    """
    day_name = get_day_name(target_date)
    date_str = target_date.strftime("%d %B %Y")
    schedule = get_schedule_for_date(target_date)

    header = (
        f"📅 *{date_str}  —  {day_name}*\n"
        f"🏛 SOF BCA2A  —  Room: LT-207\n"
    )

    if not schedule:
        return header + "\n❌ No classes scheduled."

    rows = ["```", f"{'#':<3} {'Time':<22} {'Subject':<32} {'Tchr':<5} {'Room'}", "─" * 70]
    slot_num = 0
    for entry in schedule:
        slot = entry["slot"]
        time_label = SLOT_TIMES.get(slot, "")

        if slot == "RECESS":
            rows.append(f"{'':3} {'11:30 AM – 12:00 PM':<22} {'──── RECESS ────':<32}")
            continue

        slot_num += 1
        subj = entry["subject"]
        if len(subj) > 30:
            subj = subj[:29] + "…"

        rows.append(
            f"{slot_num:<3} {time_label:<22} {subj:<32} {entry['teacher']:<5} {entry['room']}"
        )

    rows.append("```")
    return header + "\n" + "\n".join(rows)
