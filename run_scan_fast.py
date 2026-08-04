# -*- coding: utf-8 -*-
import os
import sys
import datetime
import socket
socket.setdefaulttimeout(8.0)

from historical_report_compiler import build_report_for_date

target_dt = datetime.datetime(2026, 7, 20)

print("Building PDF reports for 20260720 using original PDF textbook rules...")

# 1. 양음양
build_report_for_date(
    target_dt,
    technique_name='양음양 기법',
    json_filename='scan_results_20260720.json',
    pdf_filename_prefix='김일청의_양음양기법',
    report_title='김일청의 양음양 기법 분석 리포트'
)

# 2. 양음양 v2
build_report_for_date(
    target_dt,
    technique_name='양음양 v2 기법',
    json_filename='scan_results_yey_v2_20260720.json',
    pdf_filename_prefix='김일청의_양음양기법_v2전략',
    report_title='김일청의 양음양 v2 기법 분석 리포트'
)

# 3. 포도시
build_report_for_date(
    target_dt,
    technique_name='포도시 차트 기법',
    json_filename='scan_results_podosi_20260720.json',
    pdf_filename_prefix='김일청의_포도시차트',
    report_title='김일청의 포도시 차트 분석 리포트'
)

print("ALL 3 PDF REPORTS SUCCESSFULLY GENERATED!")
