# 🤖 Class Attendance Telegram Bot

A Telegram bot designed to help Class Representatives (CRs) automate and track daily student attendance directly into Google Sheets. 

This bot takes attendance commands via Telegram, automatically generates daily spreadsheets, keeps track of present/absent students, and even generates offline Excel backups and image snapshots of the attendance tables!

## ✨ Features
- **Google Sheets Integration:** Automatically creates daily sheets and updates attendance instantly.
- **Fast Attendance Marking:** Mark multiple students present or absent at once using `/present 01 02 04` or `/absent 12 15`.
- **Smart Snapshots:** Use `/sheet` to get an instant image snapshot of today's attendance table directly in Telegram.
- **Offline Backups:** Use `/backup` to download the entire Google Spreadsheet as an Excel (`.xlsx`) file.
- **Daily Summaries:** Use `/summary` and `/status` to see who was present/absent today.
- **Student Reports:** Use `/report <Student_ID>` to get the full attendance history of a specific student.
- **Secure Admin Login:** Only authorized admins (using a password) can mark attendance.

## 🚀 How to Setup (For your own class)

If you want to use this bot for your own department or class, follow these simple steps:

### 1. Prerequisites
You will need:
- A Telegram Bot Token (Get this from [@BotFather](https://t.me/botfather) on Telegram)
- A Google Service Account JSON key (for Google Sheets API)
- Python 3.10+ installed

### 2. Installation
1. Clone this repository:
   ```bash
   git clone https://github.com/supriyo251017002050-dotcom/BCA2A-Attendance-Bot.git
   cd BCA2A-Attendance-Bot
   ```
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

### 3. Configuration
1. Create a `.env` file in the main folder and fill in your keys:
   ```env
   TELEGRAM_TOKEN=your_telegram_bot_token
   SPREADSHEET_ID=your_google_sheet_id
   ADMIN_PASSWORD=your_secret_password
   ```
2. Place your Google Service Account credentials file in the main folder and name it `credentials.json`.
3. Share your Google Sheet with the email address found inside your `credentials.json` (give it **Editor** access).

### 4. Customizing for your Class
1. **`students.json`**: Edit this file and paste the Roll Numbers and Names of the students in your class.
2. **`timetable.json`**: Edit this file with your class's daily schedule (Subjects and Teachers).

### 5. Run the Bot
```bash
python bot.py
```
Your bot is now alive! Go to Telegram, send `/start`, and type `/login <your_password>` to start marking attendance!
