@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 테마 점등 알람
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /F /PID %%p > nul 2>&1
python app.py
pause
