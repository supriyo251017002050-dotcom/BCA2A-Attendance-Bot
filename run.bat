@echo off
title BCA2A Attendance Bot
color 0A
echo.
echo  =========================================
echo   BCA2A Attendance Bot — Starting...
echo   Techno India University, West Bengal
echo  =========================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python is not installed or not in PATH.
    echo  Please install Python from https://python.org
    pause
    exit /b 1
)

:: Install dependencies if needed
echo  Checking dependencies...
pip install -r requirements.txt -q
echo  Dependencies OK.
echo.

:: Run the bot
echo  Starting bot... Press Ctrl+C to stop.
echo.
python bot.py

echo.
echo  Bot stopped.
pause
