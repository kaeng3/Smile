@echo off
chcp 65001 > nul
cd /d "%~dp0"
python -c "import app, theme_kb, themes; print('import ok')" > logs\diag.txt 2>&1
netstat -ano | findstr ":8000 " >> logs\diag.txt
tasklist /FI "IMAGENAME eq python.exe" >> logs\diag.txt
