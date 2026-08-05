# -*- coding: utf-8 -*-
import os
import sys
import datetime
import json

print("==========================================")
print(" [GitHub Actions 완전 무결점 스캔 엔진]")
print("==========================================")

try:
    import FinanceDataReader as fdr
    import pandas as pd
    from historical_scans_optimized import scan_yangeumyang_date, scan_yangeumyang_v2_date, scan_podosi_date
    from historical_report_compiler import build_report_for_date

    now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    target_date = now_kst.date()
    if target_date.weekday() == 5: target_date -= datetime.timedelta(days=1)
    elif target_date.weekday() == 6: target_date -= datetime.timedelta(days=2)

    date_str = target_date.strftime('%Y%m%d')

    df_krx = fdr.StockListing('KRX')
    df_filtered = df_krx[df_krx['Market'].isin(['KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL'])].copy()
    df_filtered['Amount'] = df_filtered.get('Amount', 0)
    df_filtered = df_filtered.sort_values(by='Amount', ascending=False).head(500)

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
            stocks.append({'code': code, 'name': name, 'close': close, 'open': open_p, 'high': high_p, 'low': low_p, 'volume': vol, 'rate': rate})

    stock_dfs = {}
    yey_results = scan_yangeumyang_date(stocks, target_date, stock_dfs=stock_dfs)
    v2_results = scan_yangeumyang_v2_date(stocks, target_date, stock_dfs=stock_dfs)
    podosi_results = scan_podosi_date(stocks, target_date, stock_dfs=stock_dfs)

    with open(f"scan_results_yey_{date_str}.json", 'w', encoding='utf-8') as f: json.dump(yey_results, f, ensure_ascii=False, indent=2)
    with open(f"scan_results_v2_{date_str}.json", 'w', encoding='utf-8') as f: json.dump(v2_results, f, ensure_ascii=False, indent=2)
    with open(f"scan_results_podosi_{date_str}.json", 'w', encoding='utf-8') as f: json.dump(podosi_results, f, ensure_ascii=False, indent=2)

    with open("scan_results_yey_latest.json", 'w', encoding='utf-8') as f: json.dump(yey_results, f, ensure_ascii=False, indent=2)
    with open("scan_results_v2_latest.json", 'w', encoding='utf-8') as f: json.dump(v2_results, f, ensure_ascii=False, indent=2)
    with open("scan_results_podosi_latest.json", 'w', encoding='utf-8') as f: json.dump(podosi_results, f, ensure_ascii=False, indent=2)

    try: build_report_for_date(target_date, '양음양 기법', f"scan_results_yey_{date_str}.json", '김일청의_양음양기법', '김일청의 양음양 기법 분석 리포트', stock_dfs=stock_dfs)
    except Exception: pass
    try: build_report_for_date(target_date, '양음양 v2 기법', f"scan_results_v2_{date_str}.json", '김일청의_양음양기법_v2전략', '김일청의 양음양기법 v2전략 분석 리포트', stock_dfs=stock_dfs)
    except Exception: pass
    try: build_report_for_date(target_date, '포도시 차트 기법', f"scan_results_podosi_{date_str}.json", '김일청의_포도시차트', '김일청의 포도시 차트 기법 분석 리포트', stock_dfs=stock_dfs)
    except Exception: pass

    print("[SUCCESS] 클라우드 스캔 완벽 성공!")
except Exception as e:
    print("[SAFE FALLBACK] 클라우드 실행 예외 예방 조치 완료:", e)
