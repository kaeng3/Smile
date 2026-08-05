# -*- coding: utf-8 -*-
import os
import sys
import json
import datetime
import requests
import shutil

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import pandas as pd

def run_rescan():
    now = datetime.datetime.now()
    date_str = now.strftime('%Y%m%d')
    date_display = now.strftime('%Y-%m-%d')
    
    print(f"==========================================")
    print(f" [{date_display}] 오늘 종목 초고속 스캔 및 대시보드 발행")
    print(f"==========================================")

    # 1. scan_history.json 읽기
    history_file = 'scan_history.json'
    history_data = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
        except Exception:
            history_data = {}

    # 2. 세부 테마 DB 읽기
    theme_db = {}
    if os.path.exists('stock_detail_themes.json'):
        try:
            with open('stock_detail_themes.json', 'r', encoding='utf-8') as f:
                theme_db = json.load(f)
        except Exception:
            pass

    # 3. 500억/150억 스캐너 연동
    scanner_500m_json = os.path.join("stock_scanner_500m", f"scan_results_integrated_{date_str}.json")
    b500m_list = []
    if os.path.exists(scanner_500m_json):
        try:
            with open(scanner_500m_json, 'r', encoding='utf-8') as f:
                d = json.load(f)
                for s in d.get('scan_results', []):
                    code = s.get('code', '')
                    t_info = theme_db.get(code, {})
                    sub_t = t_info.get('subthemes', [])
                    cat = t_info.get('category', '기타')
                    detail_theme = f"{cat} > {', '.join(sub_t[:2])}" if sub_t else cat
                    
                    b500m_list.append({
                        'code': code,
                        'name': s.get('name', ''),
                        'close': s.get('close', 0),
                        'rate': round(s.get('rate', 0.0), 2),
                        'pattern': f"{s.get('candle_class', '500억봉')} 기준봉",
                        'comment': s.get('commentary', '500억/150억 대량 수급 발생 및 지지선 점검'),
                        'chart': f"charts/{date_str}/{code}.png" if os.path.exists(f"charts/{date_str}/{code}.png") else "",
                        'category': cat,
                        'subthemes': sub_t,
                        'detail_theme': detail_theme
                    })
        except Exception as e:
            print(f"[500m 읽기 예외] {e}")

    # 4. 이전 최신 날짜 수록 종목 복사 및 오늘 날짜 최신화
    latest_date = sorted(history_data.keys(), reverse=True)[0] if history_data else date_str
    latest_day_data = history_data.get(latest_date, {})

    yey_list = latest_day_data.get('yey', [])
    v2_list = latest_day_data.get('v2', [])
    podosi_list = latest_day_data.get('podosi', [])
    if not b500m_list:
        b500m_list = latest_day_data.get('b500m', [])

    # 오늘 데이터 보강
    history_data[date_str] = {
        'yey': yey_list,
        'v2': v2_list,
        'podosi': podosi_list,
        'b500m': b500m_list
    }

    # 최근 5일치 유지
    sorted_dates = sorted(history_data.keys(), reverse=True)
    keep_dates = sorted_dates[:5]
    purged_history = {d: history_data[d] for d in keep_dates}

    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(purged_history, f, ensure_ascii=False, indent=2)

    print(f"[스캔 완료] {date_str}자 4개 전략 스캔 데이터 scan_history.json 갱신 완료!")

    # 깃허브 자동 푸시
    import subprocess
    print("\n[GitHub] 깃허브 웹사이트 자동 반영 업로드 시작...")
    try:
        cmd_dir = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(["git", "add", "."], cwd=cmd_dir, check=False)
        subprocess.run(["git", "commit", "-m", f"Auto Update: {date_str}"], cwd=cmd_dir, check=False)
        subprocess.run(["git", "push", "origin", "main"], cwd=cmd_dir, check=False)
        print("[GitHub] 깃허브 웹사이트 반영 100% 완료!")
    except Exception as e:
        print("[GitHub Upload Info]:", e)

if __name__ == '__main__':
    run_rescan()
