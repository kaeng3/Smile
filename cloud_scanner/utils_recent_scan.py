# -*- coding: utf-8 -*-
"""
Utility functions for loading and pruning the recent 500억봉 log.
The log is stored in the project root:
    C:/Users/pc/.gemini/antigravity/scratch/stock_scanner_500m/recent_500b_candle_log.json
"""
import json
import os
from pathlib import Path
import datetime

LOG_PATH = Path("C:/Users/pc/.gemini/antigravity/scratch/stock_scanner_500m/recent_500b_candle_log.json")

def _parse_date(record):
    try:
        return datetime.datetime.strptime(record.get('date', ''), "%Y-%m-%d").date()
    except Exception:
        return None

def load_recent_500b_candle_log(days: int = 20):
    if not LOG_PATH.exists():
        return []
    cutoff = datetime.datetime.now().date() - datetime.timedelta(days=days)
    records = []
    with LOG_PATH.open(encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                rec_date = _parse_date(rec)
                if rec_date and rec_date >= cutoff:
                    records.append(rec)
            except json.JSONDecodeError:
                continue
    return records

def prune_recent_500b_candle_log(days: int = 20):
    if not LOG_PATH.exists():
        return
    cutoff = datetime.datetime.now().date() - datetime.timedelta(days=days)
    kept = []
    with LOG_PATH.open(encoding='utf-8') as f:
        for line in f:
            try:
                rec = json.loads(line)
                rec_date = _parse_date(rec)
                if rec_date and rec_date >= cutoff:
                    kept.append(rec)
            except Exception:
                continue
    with LOG_PATH.open('w', encoding='utf-8') as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
