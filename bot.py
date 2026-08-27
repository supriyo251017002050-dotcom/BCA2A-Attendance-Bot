"""
bot.py — BCA2A Attendance Bot (Main Entry Point)
Telegram bot for SOF BCA2A, 3rd Semester
Techno India University, West Bengal

Commands:
  /start               — Welcome + help
  /myid                — Show your Telegram Chat ID
  /present <ids...>    — Mark students Present for today
  /absent  <ids...>    — Mark students Absent for today
  /table [date]        — Show day schedule & initialize attendance sheet
  /summary [date]      — Attendance summary for a date
  /students            — List all registered students
  /report <id>         — Attendance report for one student
  /help                — Show all commands
"""

import logging
from datetime import date, datetime
from functools import wraps
import time
import json
import os
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

import config
from routine import format_schedule_table, get_day_name, get_schedule_for_date
from sheets_manager import SheetsManager

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Write credentials.json from env var (for cloud hosting like Fly.io) ──────
_creds_env = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if _creds_env and not os.path.exists(config.CREDENTIALS_FILE):
    try:
        with open(config.CREDENTIALS_FILE, "w") as _f:
            _f.write(_creds_env)
        logger.info("credentials.json written from GOOGLE_CREDENTIALS_JSON env var.")
    except Exception as _e:
        logger.error(f"Failed to write credentials.json: {_e}")

# ── Sheets client (initialized once) ─────────────────────────────────────────
sheets = SheetsManager(config.CREDENTIALS_FILE, config.SPREADSHEET_ID)

SHEET_URL = f"https://docs.google.com/spreadsheets/d/{config.SPREADSHEET_ID}"
active_sessions = {}  # Tracks user attendance sessions: {chat_id: {"date": date, "data": dict, "current_subject_index": int, "message_id": int}}


# ─────────────────────────────────────────────────────────────────────────────
#  Auth decorator & Login
# ─────────────────────────────────────────────────────────────────────────────

AUTH_FILE = "auth.json"
COOLDOWN_TIMERS = {}

def check_cooldown(uid: int, command: str, cooldown: int) -> int:
    """Returns the remaining cooldown time, or 0 if allowed."""
    key = f"{uid}_{command}"
    last_used = COOLDOWN_TIMERS.get(key, 0)
    now = time.time()
    if now - last_used < cooldown:
        return int(cooldown - (now - last_used))
    COOLDOWN_TIMERS[key] = now
    return 0

def load_auth_users() -> set[int]:
    if not os.path.exists(AUTH_FILE):
        return set()
    try:
        with open(AUTH_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_auth_user(uid: int):
    users = load_auth_users()
    users.add(uid)
    with open(AUTH_FILE, "w") as f:
        json.dump(list(users), f)

def remove_auth_user(uid: int):
    users = load_auth_users()
    if uid in users:
        users.remove(uid)
        with open(AUTH_FILE, "w") as f:
            json.dump(list(users), f)

def authorized_only(func):
    """Allow only admin + authenticated CRs to run a command."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id

        # If ADMIN_CHAT_ID is still 0, the bot is in "setup mode" — allow all
        if config.ADMIN_CHAT_ID == 0:
            return await func(update, context)

        auth_users = load_auth_users()
        if uid != config.ADMIN_CHAT_ID and uid not in auth_users:
            await update.message.reply_text(
                "⛔ *Access Denied*\n\n"
                "You are not authorized to use this bot.\n"
                "Use `/login <ID> <Password>` if you are a CR.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        return await func(update, context)
    return wrapper

async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/login <id> <password>"""
    if len(context.args) != 2:
        await update.message.reply_text(
            "❌ Invalid format. Use: `/login ID Password`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
        
    cr_id = context.args[0]
    password = context.args[1]
    
    if cr_id in config.CR_CREDENTIALS and config.CR_CREDENTIALS[cr_id] == password:
        save_auth_user(update.effective_user.id)
        await update.message.reply_text(
            f"✅ *Login Successful!*\nWelcome {cr_id}. You can now mark attendance.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "❌ *Login Failed*\nIncorrect ID or Password.",
            parse_mode=ParseMode.MARKDOWN
        )

async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/logout — Logout current user."""
    uid = update.effective_user.id
    users = load_auth_users()
    if uid in users:
        remove_auth_user(uid)
        await update.message.reply_text(
            "🚪 *Logged Out Successfully*\nYou have been logged out.",
            parse_mode=ParseMode.MARKDOWN
        )
    elif uid == config.ADMIN_CHAT_ID:
        await update.message.reply_text(
            "ℹ️ You are the System Admin (configured via `.env`). Admin access cannot be logged out.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "ℹ️ You are not currently logged in.",
            parse_mode=ParseMode.MARKDOWN
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Date parsing helper
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> date | None:
    """Parse 'today', 'DD-MM-YYYY', 'DD/MM/YYYY', or 'YYYY-MM-DD'."""
    if s.lower() in ("today", "aaj"):
        return date.today()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user    = update.effective_user

    setup_note = ""
    if config.ADMIN_CHAT_ID == 0:
        setup_note = (
            "\n\n⚙️ *Setup Mode Active*\n"
            f"Your Chat ID is: `{chat_id}`\n"
            "Please add this to `.env` as `ADMIN_CHAT_ID` to lock the bot."
        )

    text = (
        f"👋 Hello *{user.first_name}*!\n\n"
        f"🤖 *BCA2A Attendance Bot*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛 {config.CLASS_NAME}\n"
        f"🏢 {config.COLLEGE_NAME}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Quick Commands:*\n"
        f"📍 `/login ID Password` — Login for CRs\n"
        f"📅 `/table` — Today's schedule\n"
        f"✅ `/present 251017002050` — Mark present\n"
        f"❌ `/absent 251017002050` — Mark absent\n"
        f"📊 `/summary` — Today's full report\n"
        f"📈 `/status` — Quick count of today's attendance\n"
        f"📸 `/sheet` — Get image of today's sheet\n"
        f"💾 `/backup` — Download full Excel backup\n"
        f"🔄 `/reset` — Reset today's attendance table\n"
        f"🧹 `/clear` — Clear chat screen\n"
        f"❓ `/help` — All commands"
        f"{setup_note}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────────────────────────────────────
#  /myid
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u  = update.effective_user
    cid = update.effective_chat.id
    await update.message.reply_text(
        f"👤 *Your Telegram Info*\n\n"
        f"Name     : {u.first_name} {u.last_name or ''}\n"
        f"Username : @{u.username or 'N/A'}\n"
        f"Chat ID  : `{cid}`\n\n"
        f"Share this Chat ID with the bot admin to get access.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  /present and /absent
# ─────────────────────────────────────────────────────────────────────────────

def _expand_id(sid: str) -> str:
    sid = sid.strip()
    if len(sid) == 2 and sid.isdigit():
        return config.STUDENT_ID_PREFIX + sid
    return sid

def _validate_id(sid: str) -> bool:
    return sid.isdigit() and len(sid) == config.STUDENT_ID_LENGTH


def build_attendance_keyboard(chat_id: int) -> tuple[InlineKeyboardMarkup, str]:
    session = active_sessions.get(chat_id)
    if not session:
        return None, "Session expired."
    
    idx = session["current_subject_index"]
    subjects = session["data"]["subjects"]
    subject_name = subjects[idx]
    
    keyboard = []
    row = []
    
    # Students grid
    for student in session["data"]["students"]:
        sid = student["id"]
        # Last two digits of roll number for the button text
        short_id = sid[-2:] if len(sid) >= 2 else sid
        
        mark = session["data"]["attendance"].get(sid, [""] * len(subjects))[idx]
        
        if mark == "P":
            text = f"✅ {short_id}"
        elif mark == "A":
            text = f"❌ {short_id}"
        else:
            text = f" {short_id} "
            
        row.append(InlineKeyboardButton(text, callback_data=f"att_toggle_{sid}"))
        
        if len(row) == 5: # 5 columns per row
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    # Navigation row
    nav_row = []
    if idx > 0:
        nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data="att_nav_prev"))
    
    nav_row.append(InlineKeyboardButton(f"📘 {subject_name}", callback_data="att_ignore"))
    
    if idx < len(subjects) - 1:
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data="att_nav_next"))
        
    keyboard.append(nav_row)
    
    # Save button
    keyboard.append([InlineKeyboardButton("💾 Save to Sheet", callback_data="att_save")])
    
    # Add day
    date_str = session["date"].strftime("%d %B %Y")
    msg_text = f"📋 *Attendance for {date_str}*\n\n👉 *{subject_name}*\n_Tap a student to toggle status (✅ P, ❌ A, or empty)._"
    
    return InlineKeyboardMarkup(keyboard), msg_text

@authorized_only
async def cmd_present(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/present [DD-MM-YYYY]"""
    # Parse date if provided, else today
    target_date = date.today()
    if context.args:
        parsed = _parse_date(context.args[0])
        if parsed:
            target_date = parsed
        else:
            await update.message.reply_text("❌ Invalid date format. Use DD-MM-YYYY.")
            return

    wait_msg = await update.message.reply_text("⏳ Fetching today's attendance sheet...")
    
    data = sheets.get_daily_attendance_data(target_date)
    if not data or not data["subjects"] or not data["students"]:
        await wait_msg.edit_text("❌ No subjects or students found for this date. Check `/table` first.", parse_mode=ParseMode.MARKDOWN)
        return
        
    chat_id = update.effective_chat.id
    active_sessions[chat_id] = {
        "date": target_date,
        "data": data,
        "current_subject_index": 0
    }
    
    markup, text = build_attendance_keyboard(chat_id)
    await wait_msg.edit_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

@authorized_only
async def cmd_absent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/absent is deprecated, use /present"""
    await update.message.reply_text("❌ `/absent` is deprecated. Use `/present` to open the interactive attendance menu.", parse_mode=ParseMode.MARKDOWN)

async def handle_attendance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    if chat_id not in active_sessions:
        await query.edit_message_text("❌ Session expired. Type /present again.")
        return
        
    session = active_sessions[chat_id]
    data = query.data
    
    if data == "att_ignore":
        return
        
    if data == "att_nav_prev":
        if session["current_subject_index"] > 0:
            session["current_subject_index"] -= 1
    elif data == "att_nav_next":
        if session["current_subject_index"] < len(session["data"]["subjects"]) - 1:
            session["current_subject_index"] += 1
    elif data == "att_save":
        await query.edit_message_text("⏳ Saving attendance to Google Sheets...")
        ok, msg = sheets.save_daily_attendance_data(session["date"], session["data"])
        if ok:
            await query.edit_message_text(
                f"✅ *Attendance saved successfully!*\n"
                f"All changes synced to Google Sheets.\n\n"
                f"🔗 [Open Google Sheet to verify/fix]({SHEET_URL})",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.edit_message_text(f"❌ *Failed to save*\n{msg}", parse_mode=ParseMode.MARKDOWN)
        del active_sessions[chat_id]
        return
    elif data.startswith("att_toggle_"):
        sid = data.split("_")[2]
        idx = session["current_subject_index"]
        
        # Current mark
        marks = session["data"]["attendance"].get(sid, [""] * len(session["data"]["subjects"]))
        current = marks[idx]
        
        # Toggle: "" -> "P" -> "A" -> ""
        if current == "":
            marks[idx] = "P"
        elif current == "P":
            marks[idx] = "A"
        else:
            marks[idx] = ""
            
        session["data"]["attendance"][sid] = marks

    # Rebuild and update keyboard
    markup, text = build_attendance_keyboard(chat_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────────────────────────────────────
#  /reset
# ─────────────────────────────────────────────────────────────────────────────

@authorized_only
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reset [DD-MM-YYYY | today]"""
    if not context.args:
        target_date = date.today()
    else:
        target_date = _parse_date(context.args[0])
        if target_date is None:
            await update.message.reply_text(
                "❌ Invalid date format.\n"
                "Use: `/reset 01-08-2026` or `/reset today`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    wait = await update.message.reply_text(f"⏳ Resetting table for {target_date.strftime('%d %B %Y')}...")
    ok, msg = sheets.reset_attendance(target_date)
    
    if ok:
        await wait.edit_text(
            f"🔄 *Table Reset Successful!*\n"
            f"All attendance marks for {target_date.strftime('%d %B %Y')} have been cleared.\n"
            f"You can now use `/present` or `/absent` to start over.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await wait.edit_text(f"❌ *Reset Failed*\n{msg}", parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────────────────────────────────────
#  /table [date]
# ─────────────────────────────────────────────────────────────────────────────

@authorized_only
async def cmd_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/table [DD-MM-YYYY | today]"""
    if not context.args:
        target_date = date.today()
    else:
        target_date = _parse_date(context.args[0])
        if target_date is None:
            await update.message.reply_text(
                "❌ Invalid date format.\n"
                "Use: `/table 01-08-2026` or `/table today`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    day = get_day_name(target_date)

    if day == "Sunday":
        await update.message.reply_text(
            f"🌅 *{target_date.strftime('%d %B %Y')}* is a *Sunday* — Holiday! No classes.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if day == "Monday":
        await update.message.reply_text(
            f"🏖 *{target_date.strftime('%d %B %Y')}* is *Monday* — Day Off! No classes.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Send timetable immediately
    table_text = format_schedule_table(target_date)
    msg = await update.message.reply_text(
        table_text + "\n\n⏳ _Initializing attendance sheet..._",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Initialize the date column in Google Sheets (in background)
    try:
        sheets.initialize_date(target_date)
        date_str = target_date.strftime("%d %B %Y")
        await msg.edit_text(
            table_text
            + f"\n\n✅ *Attendance sheet ready for {date_str}*"
            + f"\n📊 [Open Google Sheet]({SHEET_URL})"
            + f"\n\n*To mark present:*\n`/present 251017002050`",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"initialize_date error: {e}")
        await msg.edit_text(
            table_text + f"\n\n⚠️ Sheet init failed: {e}",
            parse_mode=ParseMode.MARKDOWN,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  /summary [date]
# ─────────────────────────────────────────────────────────────────────────────

@authorized_only
async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/summary [DD-MM-YYYY | today]"""
    if not context.args:
        target_date = date.today()
    else:
        target_date = _parse_date(context.args[0])
        if target_date is None:
            await update.message.reply_text(
                "❌ Invalid date. Use: `/summary 01-08-2026` or `/summary today`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    wait = await update.message.reply_text("⏳ Fetching attendance data from Google Sheets...")

    data = sheets.get_day_summary(target_date)
    date_str = target_date.strftime("%d %B %Y  (%A)")

    if data is None:
        await wait.edit_text(
            f"📭 No attendance data found for *{date_str}*.\n\n"
            f"Use `/table {target_date.strftime('%d-%m-%Y')}` first to initialize the sheet.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    total   = data["total"]
    p_count = len(data["present"])
    a_count = len(data["absent"])
    pct_p   = int(p_count / total * 100) if total else 0
    pct_a   = int(a_count / total * 100) if total else 0

    present_str = "\n".join(
        [f"  ✅ `{sid}` — {name}" for sid, name in data["present"]]
    ) or "  _(none)_"

    absent_str = "\n".join(
        [f"  ❌ `{sid}` — {name}" for sid, name in data["absent"]]
    ) or "  _(none)_"

    msg = (
        f"📊 *Attendance Summary*\n"
        f"📅 {date_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total : {total}\n"
        f"✅ Present: {p_count} ({pct_p}%)\n"
        f"❌ Absent : {a_count} ({pct_a}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Present ({p_count}):*\n{present_str}\n\n"
        f"*Absent ({a_count}):*\n{absent_str}\n\n"
        f"📊 [View Full Sheet]({SHEET_URL})"
    )
    await wait.edit_text(msg, parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────────────────────────────────────
#  /status
# ─────────────────────────────────────────────────────────────────────────────

@authorized_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — Quick count of today's attendance."""
    target_date = date.today()
    wait = await update.message.reply_text("⏳ Quick checking today's attendance...")

    data = sheets.get_day_summary(target_date)
    
    if data is None:
        await wait.edit_text("📭 No attendance sheet found for today yet.")
        return

    total   = data["total"]
    p_count = len(data["present"])
    a_count = len(data["absent"])
    pct_p   = int(p_count / total * 100) if total else 0

    msg = (
        f"📈 *Today's Quick Status*\n"
        f"✅ *Present:* {p_count} students ({pct_p}%)\n"
        f"❌ *Absent:* {a_count} students\n"
        f"👥 *Total:* {total} students"
    )
    await wait.edit_text(msg, parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────────────────────────────────────────────────────────
#  /sheet (Image snapshot)
# ─────────────────────────────────────────────────────────────────────────────

@authorized_only
async def cmd_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sheet — Returns a generated image of today's spreadsheet table."""
    logger.info("CMD_SHEET HAS BEEN CALLED!")
    
    uid = update.effective_user.id
    remaining = check_cooldown(uid, "sheet", 15)
    if remaining > 0:
        await update.message.reply_text(f"⏳ Please wait {remaining} seconds before requesting another sheet snapshot.")
        return
        
    target_date = date.today()
    wait = await update.message.reply_text("📸 Capturing table screenshot... Please wait.")

    filepath = sheets.generate_sheet_image(target_date)
    if not filepath or not os.path.exists(filepath):
        await wait.edit_text("❌ Could not generate the table image. Make sure the sheet is initialized.")
        return

    try:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=open(filepath, "rb"),
            caption=(
                f"📸 *Table Snapshot — {target_date.strftime('%d %B %Y')}*\n\n"
                f"🔗 [Open Google Sheet to manually adjust]({SHEET_URL})"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        await wait.delete()
        os.remove(filepath)
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        await wait.edit_text(f"❌ Error sending image: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  /backup (Excel export)
# ─────────────────────────────────────────────────────────────────────────────

@authorized_only
async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/backup — Export and download the entire attendance sheet as an Excel file."""
    uid = update.effective_user.id
    remaining = check_cooldown(uid, "backup", 30)
    if remaining > 0:
        await update.message.reply_text(f"⏳ Please wait {remaining} seconds before requesting another backup.")
        return
        
    wait = await update.message.reply_text("⏳ Generating offline Excel backup... Please wait.")
    
    try:
        excel_bytes = sheets.get_backup_excel()
        filename = f"BCA2A_Attendance_Backup_{date.today().strftime('%Y-%m-%d')}.xlsx"
        
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=excel_bytes,
            filename=filename,
            caption="💾 *Full Spreadsheet Backup*\n\nHere is your offline Excel backup containing all the data from Google Sheets.",
            parse_mode=ParseMode.MARKDOWN
        )
        await wait.delete()
    except Exception as e:
        logger.error(f"Error generating backup: {e}")
        await wait.edit_text(f"❌ Failed to generate backup: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  /students
# ─────────────────────────────────────────────────────────────────────────────

@authorized_only
async def cmd_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/students — List all students."""
    students = sheets.get_students()

    if not students:
        await update.message.reply_text(
            "📭 No students found.\n"
            "Edit `students.json` to add students and restart the bot."
        )
        return

    lines = [f"👥 *Student List — {config.CLASS_NAME}*\n"]
    for i, (sid, name) in enumerate(students.items(), 1):
        lines.append(f"{i:02}. `{sid}` — {name}")
    lines.append(f"\n*Total: {len(students)} students*")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────────────────────────────────────
#  /report <student_id>
# ─────────────────────────────────────────────────────────────────────────────

@authorized_only
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/report <student_id> — Full attendance history for one student."""
    if not context.args:
        await update.message.reply_text(
            "❌ Provide a student ID.\nExample: `/report 251017002050`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    sid  = context.args[0].strip()
    name = sheets.get_student_name(sid)
    if name is None:
        clean_sid = sid.replace("`", "").replace("*", "").replace("_", "")
        await update.message.reply_text(
            f"❌ Student ID `{clean_sid}` not found.", parse_mode=ParseMode.MARKDOWN
        )
        return

    wait = await update.message.reply_text("⏳ Fetching student report...")
    records = sheets.get_student_report(sid)

    if not records:
        await wait.edit_text(
            f"📭 No attendance records found for `{sid}` — {name}.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    present_days = sum(1 for _, m in records if m == "P")
    total_days   = len(records)
    pct          = int(present_days / total_days * 100) if total_days else 0

    lines = [f"📋 *Report for {name}*\n`{sid}`\n"]
    for dt, mark in records:
        icon = "✅" if mark == "P" else "❌"
        lines.append(f"{icon} {dt} — {mark}")

    lines.append(f"\n📈 *Attendance: {present_days}/{total_days} days ({pct}%)*")
    await wait.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────────────────────────────────────
#  /ask <prompt> (AI Integration)
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ask <question> — Ask the AI a question."""
    if not context.args:
        await update.message.reply_text(
            "❌ Please provide a question.\nExample: `/ask Who is this chat bot?`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    prompt = " ".join(context.args)
    wait = await update.message.reply_text("⏳ Thinking...")

    url = config.AI_API_URL
    headers = {
        "Authorization": f"Bearer {config.AI_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": config.AI_MODEL,
        "messages": [
            {"role": "system", "content": "You are the BCA2A Attendance Bot, a helpful AI assistant for Techno India University students. Keep your answers concise and helpful."},
            {"role": "user", "content": prompt}
        ]
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data, timeout=30.0)
            if response.status_code != 200:
                logger.error(f"AI API Error Status {response.status_code}: {response.text}")
                try:
                    res_json = response.json()
                    err_msg = res_json.get("error", {}).get("message") if isinstance(res_json.get("error"), dict) else res_json.get("message") or f"HTTP {response.status_code}"
                except Exception:
                    err_msg = f"HTTP {response.status_code}"
                await wait.edit_text(f"❌ AI Error ({response.status_code}): {err_msg}")
                return
            
            res_data = response.json()
            ai_response = res_data["choices"][0]["message"]["content"]
            await wait.edit_text(ai_response, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"AI Exception: {e}")
        await wait.edit_text("❌ Sorry, I couldn't get a response from the AI at the moment.")


# ─────────────────────────────────────────────────────────────────────────────
#  /help
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 *BCA2A Attendance Bot — All Commands*\n\n"
        "*📌 Schedule:*\n"
        "`/table` — Today's class schedule + init sheet\n"
        "`/table 01-08-2026` — Schedule for a specific date\n\n"
        "*✅ Marking Attendance:*\n"
        "`/present 251017002050` — Mark one student present\n"
        "`/present 001 002 003` — Mark multiple students\n"
        "`/absent 251017002050` — Mark student absent\n\n"
        "*📊 Reports:*\n"
        "`/summary` — Today's attendance summary\n"
        "`/summary 01-08-2026` — Summary for a specific date\n"
        "`/status` — Quick count of today's present/absent students\n"
        "`/sheet` — Get an image screenshot of today's table\n"
        "`/backup` — Download full Excel backup of all data\n"
        "`/reset` — Clear today's table if you made a mistake\n"
        "`/report 251017002050` — Full history for one student\n"
        "`/students` — List all students\n\n"
        "*🤖 AI Assistant:*\n"
        "`/ask <question>` — Ask the AI anything (e.g. 'Who is this chat bot?')\n\n"
        "*⚙️ Other:*\n"
        "`/myid` — Get your Telegram Chat ID\n"
        "`/clear` — Visually clear the chat screen\n"
        "`/start` — Welcome message\n"
        "`/help` — Show this help\n\n"
        f"🌐 [Open Google Sheet]({SHEET_URL})\n"
        f"🏛 {config.CLASS_NAME}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────────────────────────────────────
#  /clear
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/clear — Visually clears the chat by pushing messages up."""
    # Use the invisible Braille blank character to push messages up cleanly
    blank_space = "‎\n" * 50
    await update.message.reply_text(
        f"{blank_space}🧹 *Chat visually cleared!*\n\n"
        f"*(Note: Telegram bots cannot delete your chat history. To permanently clear history, tap the 3 dots in the top right and select 'Clear History')*",
        parse_mode=ParseMode.MARKDOWN
    )

# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in .env!")
    if not config.SPREADSHEET_ID:
        raise RuntimeError("SPREADSHEET_ID is not set in .env!")

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("login",    cmd_login))
    app.add_handler(CommandHandler("logout",   cmd_logout))
    app.add_handler(CommandHandler("myid",     cmd_myid))
    app.add_handler(CommandHandler("present",  cmd_present))
    app.add_handler(CommandHandler("absent",   cmd_absent))
    app.add_handler(CommandHandler("table",    cmd_table))
    app.add_handler(CommandHandler("today",    cmd_table))
    app.add_handler(CommandHandler("summary",  cmd_summary))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("sheet",    cmd_sheet))
    app.add_handler(CommandHandler("backup",   cmd_backup))
    app.add_handler(CommandHandler("reset",    cmd_reset))
    app.add_handler(CommandHandler("students", cmd_students))
    app.add_handler(CommandHandler("report",   cmd_report))
    app.add_handler(CommandHandler("ask",      cmd_ask))
    app.add_handler(CommandHandler("clear",    cmd_clear))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CallbackQueryHandler(handle_attendance_callback, pattern='^att_'))

    logger.info("🤖 BCA2A Attendance Bot is running...")
    if config.ADMIN_CHAT_ID == 0:
        logger.warning("⚠️  ADMIN_CHAT_ID is 0 — bot is in open/setup mode!")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
