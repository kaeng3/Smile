# -*- coding: utf-8 -*-
import os
import sys
import datetime
import json

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def main():
    # 1. 대상 날짜 결정 (기본값: 20260715)
    if len(sys.argv) > 1:
        try:
            target_date = datetime.datetime.strptime(sys.argv[1], '%Y%m%d')
        except ValueError:
            print("올바른 날짜 형식이 아닙니다 (예: 20260715)")
            sys.exit(1)
    else:
        target_date = datetime.datetime(2026, 7, 15)
        
    date_str = target_date.strftime('%Y%m%d')
    print(f"==========================================")
    print(f" [{target_date.strftime('%Y-%m-%d')}] 2대 핵심 기법별 스캔 및 리포트 작성 시작")
    print(f"==========================================")
    
    # 2. 시장 종목 정보 수집
    print("시장 종목 정보 불러오는 중...")
    from historical_scans_optimized import get_market_list, scan_date_optimized, scan_podosi_date, scan_date_yey_v2
    from historical_report_compiler import build_report_for_date
    from yangeumyang_tracker import register_anchor_stocks, scan_tracked_pullbacks
    
    stocks = get_market_list()
    print(f"총 {len(stocks)}개 상장 종목 확보 완료.")
    
    # --- 1-1기법: 기존 양음양 기법 ---
    print("\n--- [기법 1-1] 기존 양음양 기법 스캔 및 리포트 작성 ---")
    yey_results = scan_date_optimized(stocks, target_date)
    
    # [자동 DB 등록] 스캔된 양음양 종목을 추적 DB에 자동 등록
    if yey_results:
        register_anchor_stocks(yey_results, target_date)
        
    # [과거 DB 추적] 과거 등록된 종목 중 오늘 우상향 5/10/15/20선 지지 종목 스캔 후 합산
    tracked_signals = scan_tracked_pullbacks(target_date)
    for ts in tracked_signals:
        if ts['code'] not in {s['code'] for s in yey_results}:
            yey_results.append(ts)
            
    yey_json = f"scan_results_yey_{date_str}.json"
    with open(yey_json, 'w', encoding='utf-8') as f:
        json.dump(yey_results, f, ensure_ascii=False, indent=2)
    build_report_for_date(
        target_date, 
        technique_name='양음양 기법', 
        json_filename=yey_json, 
        pdf_filename_prefix='김일청의_양음양기법', 
        report_title='김일청의 양음양 기법 분석 리포트'
    )
    
    # --- 1-2기법: 양음양 v2 기법 (명세서 v2 전략 기준) ---
    print("\n--- [기법 1-2] 양음양 v2 기법 스캔 및 리포트 작성 ---")
    yey_v2_results = scan_date_yey_v2(stocks, target_date)
    if yey_v2_results:
        register_anchor_stocks(yey_v2_results, target_date)
        
    yey_v2_json = f"scan_results_yey_v2_{date_str}.json"
    with open(yey_v2_json, 'w', encoding='utf-8') as f:
        json.dump(yey_v2_results, f, ensure_ascii=False, indent=2)
    build_report_for_date(
        target_date, 
        technique_name='양음양 v2 기법', 
        json_filename=yey_v2_json, 
        pdf_filename_prefix='김일청의_양음양기법_v2전략', 
        report_title='김일청의 양음양 v2 기법 분석 리포트'
    )
    
    # --- 2기법: 포도시 차트 기법 (양음양 중복 시 ★ 표기) ---
    print("\n--- [기법 2] 포도시 차트 기법 스캔 및 리포트 작성 ---")
    podosi_results = scan_podosi_date(stocks, target_date)
    
    # 양음양 중복 종목에 종목명 앞 ★ 추가
    yey_codes = {s['code'] for s in yey_results}.union({s['code'] for s in yey_v2_results})
    for s in podosi_results:
        if s['code'] in yey_codes:
            s['name'] = '★' + s['name']
            print(f"[★ 표시 적용] {s['name']} ({s['code']}) - 포도시 & 양음양 중복 포착!")
            
    podosi_json = f"scan_results_podosi_{date_str}.json"
    with open(podosi_json, 'w', encoding='utf-8') as f:
        json.dump(podosi_results, f, ensure_ascii=False, indent=2)
    build_report_for_date(
        target_date, 
        technique_name='포도시 차트 기법', 
        json_filename=podosi_json, 
        pdf_filename_prefix='김일청의_포도시차트', 
        report_title='김일청의 포도시 차트 기법 분석 리포트'
    )
    
    print(f"\n==========================================")
    print(f" [{target_date.strftime('%Y-%m-%d')}] 2대 핵심 PDF 리포트 작성이 모두 완료되었습니다!")
    print(f"==========================================")

if __name__ == '__main__':
    main()
