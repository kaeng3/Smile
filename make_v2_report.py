# -*- coding: utf-8 -*-
import os
import sys
import datetime
import json
import socket
socket.setdefaulttimeout(10.0)

from historical_scans_optimized import get_market_list, scan_date_yey_v2
from historical_report_compiler import build_report_for_date
from yangeumyang_tracker import register_anchor_stocks

target_date = datetime.datetime(2026, 7, 16)
date_str = target_date.strftime('%Y%m%d')

print("Fetching stocks...")
stocks = get_market_list()

print(f"[{date_str}] Scanning YEY v2 stocks...")
v2_results = scan_date_yey_v2(stocks, target_date)
print(f"v2 results count: {len(v2_results)}")

if v2_results:
    register_anchor_stocks(v2_results, target_date)

v2_json = f"scan_results_yey_v2_{date_str}.json"
with open(v2_json, 'w', encoding='utf-8') as f:
    json.dump(v2_results, f, ensure_ascii=False, indent=2)

print("Building PDF report...")
build_report_for_date(
    target_date,
    technique_name='양음양 v2 기법',
    json_filename=v2_json,
    pdf_filename_prefix='김일청의_양음양기법_v2전략',
    report_title='김일청의 양음양 v2 기법 분석 리포트'
)
print("COMPLETED ALL!")
