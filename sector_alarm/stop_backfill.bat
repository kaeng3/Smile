@echo off
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*infostock.py backfill*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; 'killed ' + $_.ProcessId }" > logs\stop.txt 2>&1
