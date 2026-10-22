@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 상승 테마 업로드 (Smile 대시보드)
rem 알람 프로그램(run.bat)이 켜져 있어야 합니다. 장중 5분마다 올리고 장 마감 뒤 마지막 1회 올린 뒤 끝납니다.
python publish_snapshot.py --loop 300
pause
