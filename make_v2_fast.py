# -*- coding: utf-8 -*-
import os
import sys
import datetime
import socket
socket.setdefaulttimeout(10.0)

from historical_report_compiler import build_report_for_date

target_date = datetime.datetime(2026, 7, 20)
date_str = target_date.strftime('%Y%m%d')
v2_json = f"scan_results_yey_v2_{date_str}.json"

print(f"Building v2 report for {date_str} from {v2_json}...")
build_report_for_date(
    target_date,
    technique_name='양음양 v2 기법',
    json_filename=v2_json,
    pdf_filename_prefix='김일청의_양음양기법_v2전략',
    report_title='김일청의 양음양 v2 기법 분석 리포트'
)
print("SUCCESSFULLY COMPLETED V2 PDF REPORT!")
