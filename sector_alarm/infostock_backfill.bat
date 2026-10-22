@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 인포스탁 과거자료 수집
python infostock.py backfill > logs\infostock_backfill.txt 2>&1
python infostock.py reparse >> logs\infostock_backfill.txt 2>&1
python infostock.py brief > logs\infostock_brief.txt 2>&1
