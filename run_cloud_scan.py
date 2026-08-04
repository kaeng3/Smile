# -*- coding: utf-8 -*-
import os
import sys
import datetime
import json
import FinanceDataReader as fdr
import pandas as pd

from historical_scans_optimized import scan_yangeumyang_date, scan_yangeumyang_v2_date, scan_podosi_date
from historical_report_compiler import build_report_for_date, get_previous_trading_day

print("==========================================")
print(" [GitHub Actions 클라우드 초고속 자동 스캔 엔진]")
print("==========================================")

# 1. 대상 날짜 구하기 (오늘 또는 이전 영업일)
target_date = datetime.date.today()

# 한국시간(UTC+9) 기준 조정
now_utc = datetime.datetime.utcnow()
now_kst = now_utc + datetime.timedelta(hours=9)
target_date = now_kst.date()

# 주말 처리
if target_date.weekday() == 5: # 토요일
    target_date -= datetime.timedelta(days=1)
elif target_date.weekday() == 6: # 일요일
    target_date -= datetime.timedelta(days=2)

date_str = target_date.strftime('%Y%m%d')
print(f"[클라우드 스캔 Target Date] {target_date.strftime('%Y-%m-%d')}")

# 2. KRX 전체 종목 시세 획득 (FinanceDataReader)
print("[클라우드 데이터] KRX 상장 전 종목 획득 중...")
df_krx = fdr.StockListing('KRX')
df_filtered = df_krx[df_krx['Market'].isin(['KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL'])].copy()

# 거래량/거래대금 상위 600개 종목 우선 선별하여 클라우드 속도 최적화
df_filtered['Amount'] = df_filtered.get('Amount', 0)
df_filtered = df_filtered.sort_values(by='Amount', ascending=False).head(800)

print(f"[클라우드 데이터] 주요 상장 종목 {len(df_filtered)}개 선별 완료.")

stocks = []
for _, row in df_filtered.iterrows():
    code = str(row['Code']).zfill(6)
    name = str(row['Name'])
    close = float(row.get('Close', 0) or 0)
    open_p = float(row.get('Open', close) or close)
    high_p = float(row.get('High', close) or close)
    low_p = float(row.get('Low', close) or close)
    vol = float(row.get('Volume', 0) or 0)
    changes = float(row.get('ChgRate', 0) or 0)
    rate = changes * 100 if abs(changes) < 1.0 else changes

    if close > 0:
        stocks.append({
            'code': code,
            'name': name,
            'close': close,
            'open': open_p,
            'high': high_p,
            'low': low_p,
            'volume': vol,
            'rate': rate
        })

print(f"[클라우드] 총 {len(stocks)}개 종목 기초 데이터 준비 완료.")

# stock_dfs 메모리 로딩 (온라인 fallback 지원)
stock_dfs = {}

# --- [1] 양음양 기법 ---
print("\n--- [1] 양음양 기법 클라우드 스캔 ---")
yey_results = scan_yangeumyang_date(stocks, target_date, stock_dfs=stock_dfs)
print(f"양음양 포착 완료: {len(yey_results)}개 종목")

yey_json = f"scan_results_yey_{date_str}.json"
with open(yey_json, 'w', encoding='utf-8') as f:
    json.dump(yey_results, f, ensure_ascii=False, indent=2)

try:
    build_report_for_date(
        target_date,
        technique_name='양음양 기법',
        json_filename=yey_json,
        pdf_filename_prefix='김일청의_양음양기법',
        report_title='김일청의 양음양 기법 분석 리포트',
        stock_dfs=stock_dfs
    )
except Exception as e:
    print("양음양 PDF 컴파일 알림:", e)

# --- [2] 양음양 v2 기법 ---
print("\n--- [2] 양음양 v2 기법 클라우드 스캔 ---")
v2_results = scan_yangeumyang_v2_date(stocks, target_date, stock_dfs=stock_dfs)
print(f"양음양 v2 포착 완료: {len(v2_results)}개 종목")

v2_json = f"scan_results_v2_{date_str}.json"
with open(v2_json, 'w', encoding='utf-8') as f:
    json.dump(v2_results, f, ensure_ascii=False, indent=2)

try:
    build_report_for_date(
        target_date,
        technique_name='양음양 v2 기법',
        json_filename=v2_json,
        pdf_filename_prefix='김일청의_양음양기법_v2전략',
        report_title='김일청의 양음양기법 v2전략 분석 리포트',
        stock_dfs=stock_dfs
    )
except Exception as e:
    print("양음양 v2 PDF 컴파일 알림:", e)

# --- [3] 포도시 차트 기법 ---
print("\n--- [3] 포도시 차트 기법 클라우드 스캔 ---")
podosi_results = scan_podosi_date(stocks, target_date, stock_dfs=stock_dfs)
print(f"포도시 포착 완료: {len(podosi_results)}개 종목")

podosi_json = f"scan_results_podosi_{date_str}.json"
with open(podosi_json, 'w', encoding='utf-8') as f:
    json.dump(podosi_results, f, ensure_ascii=False, indent=2)

try:
    build_report_for_date(
        target_date,
        technique_name='포도시 차트 기법',
        json_filename=podosi_json,
        pdf_filename_prefix='김일청의_포도시차트',
        report_title='김일청의 포도시 차트 기법 분석 리포트',
        stock_dfs=stock_dfs
    )
except Exception as e:
    print("포도시 PDF 컴파일 알림:", e)

# --- 대시보드 웹사이트용 latest 파일 복사 ---
import shutil
shutil.copyfile(yey_json, 'scan_results_yey_latest.json')
shutil.copyfile(v2_json, 'scan_results_v2_latest.json')
shutil.copyfile(podosi_json, 'scan_results_podosi_latest.json')

pdf_sources = [r"C:\Users\pc\Desktop\양음양 리포트", "."]
for src in pdf_sources:
    if os.path.exists(src):
        try:
            f1 = os.path.join(src, f"김일청의_양음양기법_{date_str}.pdf")
            f2 = os.path.join(src, f"김일청의_양음양기법_v2전략_{date_str}.pdf")
            f3 = os.path.join(src, f"김일청의_포도시차트_{date_str}.pdf")
            if os.path.exists(f1): shutil.copyfile(f1, "김일청의_양음양기법_latest.pdf")
            if os.path.exists(f2): shutil.copyfile(f2, "김일청의_양음양기법_v2전략_latest.pdf")
            if os.path.exists(f3): shutil.copyfile(f3, "김일청의_포도시차트_latest.pdf")
        except Exception as e:
            pass

print("\n==========================================")
print(f" [{target_date.strftime('%Y-%m-%d')}] 클라우드 초고속 스캔 및 리포트 발행 완료!")
print("==========================================")
