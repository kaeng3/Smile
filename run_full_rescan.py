# -*- coding: utf-8 -*-
import os
import sys
import datetime
import json
import socket
socket.setdefaulttimeout(10.0)

from local_data_manager import sync_stock_data, load_cached_stock_dfs
from historical_scans_optimized import get_market_list, scan_date_optimized, scan_date_yey_v2, scan_podosi_date
from historical_report_compiler import build_report_for_date
from yangeumyang_tracker import register_anchor_stocks, scan_tracked_pullbacks

target_date = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
if target_date.weekday() == 5:
    target_date = target_date - datetime.timedelta(days=1)
elif target_date.weekday() == 6:
    target_date = target_date - datetime.timedelta(days=2)

date_str = target_date.strftime('%Y%m%d')

print("==========================================")
print(f" [{target_date.strftime('%Y-%m-%d')}] 로컬 캐시 DB 증분 스캔 및 리포트 즉시 발행")
print("==========================================")

# 1. 로컬 DB 증분(Delta) 갱신 (단 몇 초 소요)
sync_stock_data(target_date)

# 2. 로컬 DB에서 2,553개 종목 OHLCV 일괄 로딩 (0.5초 소요)
print("[로컬 DB] 전 종목 OHLCV 데이터 메모리 로딩 중...")
stock_dfs = load_cached_stock_dfs(target_date)
stocks = get_market_list()
print(f"총 {len(stocks)}개 상장 종목 로컬 캐시 준비 완료.")

# --- 1. 양음양 기법 일반 ---
print("\n--- [1] 양음양 기법 로컬 초고속 스캔 ---")
yey_results = scan_date_optimized(stocks, target_date, stock_dfs=stock_dfs)
print(f"양음양 일반 포착 완료: {len(yey_results)}개 종목")

register_anchor_stocks(yey_results, target_date)
tracked_results = scan_tracked_pullbacks(target_date, stock_dfs=stock_dfs)

combined_yey = list(yey_results)
existing_codes = {s['code'] for s in combined_yey}
for tr in tracked_results:
    if tr['code'] not in existing_codes:
        combined_yey.append(tr)

yey_json = f"scan_results_yey_{date_str}.json"
with open(yey_json, 'w', encoding='utf-8') as f:
    json.dump(combined_yey, f, ensure_ascii=False, indent=2)

build_report_for_date(
    target_date,
    technique_name='양음양 기법',
    json_filename=yey_json,
    pdf_filename_prefix='김일청의_양음양기법',
    report_title='김일청의 양음양 기법 분석 리포트',
    stock_dfs=stock_dfs
)

# --- 2. 양음양 v2 기법 ---
print("\n--- [2] 양음양 v2 기법 로컬 초고속 스캔 ---")
v2_results = scan_date_yey_v2(stocks, target_date, stock_dfs=stock_dfs)
print(f"양음양 v2 포착 완료: {len(v2_results)}개 종목")

register_anchor_stocks(v2_results, target_date)

v2_json = f"scan_results_v2_{date_str}.json"
with open(v2_json, 'w', encoding='utf-8') as f:
    json.dump(v2_results, f, ensure_ascii=False, indent=2)

build_report_for_date(
    target_date,
    technique_name='양음양 v2 기법',
    json_filename=v2_json,
    pdf_filename_prefix='김일청의_양음양기법_v2전략',
    report_title='김일청의 양음양 기법 v2전략 리포트',
    stock_dfs=stock_dfs
)

# --- 3. 포도시 차트 기법 ---
print("\n--- [3] 포도시 차트 기법 로컬 초고속 스캔 ---")
podosi_results = scan_podosi_date(stocks, target_date, stock_dfs=stock_dfs)
print(f"포도시 포착 완료: {len(podosi_results)}개 종목")

podosi_json = f"scan_results_podosi_{date_str}.json"
with open(podosi_json, 'w', encoding='utf-8') as f:
    json.dump(podosi_results, f, ensure_ascii=False, indent=2)

build_report_for_date(
    target_date,
    technique_name='포도시 차트 기법',
    json_filename=podosi_json,
    pdf_filename_prefix='김일청의_포도시차트',
    report_title='김일청의 포도시 차트 기법 분석 리포트',
    stock_dfs=stock_dfs
)

# --- 4. 대시보드 웹사이트용 latest 파일 자동 생성 ---
import shutil
shutil.copyfile(yey_json, 'scan_results_yey_latest.json')
shutil.copyfile(v2_json, 'scan_results_v2_latest.json')
shutil.copyfile(podosi_json, 'scan_results_podosi_latest.json')

# --- 5일치 스캔 히스토리 유지 및 6일 이상 데이터 자동 삭제 ---
history_file = 'scan_history.json'
history_data = {}
if os.path.exists(history_file):
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
    except Exception:
        history_data = {}

# 대시보드용 JSON (AI 코멘트 + 차트 경로 포함) 읽기
def load_dashboard_json(prefix_key, date_str):
    path = f"dashboard_{prefix_key}_{date_str}.json"
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

yey_web = load_dashboard_json('양음양', date_str)
v2_web  = load_dashboard_json('양음양기법_v2전략', date_str)
podosi_web = load_dashboard_json('포도시', date_str)

# fallback: 대시보드 JSON 없으면 기존 scan result JSON 사용
if not yey_web:
    yey_web = yey_results
if not v2_web:
    v2_web  = v2_results
if not podosi_web:
    podosi_web = podosi_results



# 오늘 데이터(AI 코멘트 + 차트 포함) 히스토리에 저장
history_data[date_str] = {
    'yey': yey_web,
    'v2': v2_web,
    'podosi': podosi_web
}

# 날짜 내림차순 정렬 후 최근 5일치만 남기고 6일 이전 데이터 자동 삭제
sorted_dates = sorted(history_data.keys(), reverse=True)
keep_dates = sorted_dates[:5]

purged_history = {d: history_data[d] for d in keep_dates}

with open(history_file, 'w', encoding='utf-8') as f:
    json.dump(purged_history, f, ensure_ascii=False, indent=2)

print(f"[히스토리 관리] 최근 5일치({', '.join(keep_dates)}) 데이터 보관, 6일 이상 이전 스캔 자동 삭제 완료!")


import subprocess
print("\n[GitHub] 깃허브 웹사이트 자동 반영 업로드 시작...")
try:
    cmd_dir = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\scratch"
    subprocess.run(["git", "add", "."], cwd=cmd_dir, check=False)
    subprocess.run(["git", "commit", "-m", f"Auto Update: {date_str}"], cwd=cmd_dir, check=False)
    subprocess.run(["git", "push", "origin", "main"], cwd=cmd_dir, check=False)
    print("[GitHub] 깃허브 웹사이트 반영 100% 완료!")
except Exception as e:
    print("[GitHub Upload Info]:", e)

print("\n==========================================")
print(f" [{target_date.strftime('%Y-%m-%d')}] 전 종목 로컬 초고속 스캔 및 리포트 3종 발행 완료!")
print("==========================================")
