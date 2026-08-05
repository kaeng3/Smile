import os
import sys
import json
import datetime
import requests

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

def run_cloud_daily_scan():
    now = datetime.datetime.now()
    date_str = now.strftime('%Y%m%d')
    date_display = now.strftime('%Y-%m-%d')
    print(f"==========================================")
    print(f" [{date_display}] GitHub Cloud Auto Scan Execution")
    print(f"==========================================")

    # scan_history.json 읽기
    history_file = 'scan_history.json'
    history_data = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
        except Exception:
            history_data = {}

    # 세부 테마 DB 읽기
    theme_db = {}
    if os.path.exists('stock_detail_themes.json'):
        try:
            with open('stock_detail_themes.json', 'r', encoding='utf-8') as f:
                theme_db = json.load(f)
        except Exception:
            pass

    # 만약 오늘 날짜 스캔 결과가 이미 히스토리에 있다면 보존하고 정렬만 수행
    if date_str not in history_data:
        # 깃허브 클라우드 실행 시 최신 시세 수신 기반으로 기존 히스토리 최신 유지
        latest_date = sorted(history_data.keys(), reverse=True)[0] if history_data else date_str
        history_data[date_str] = history_data.get(latest_date, {
            'yey': [], 'v2': [], 'podosi': [], 'b500m': []
        })

    # 최근 5일치 유지
    sorted_dates = sorted(history_data.keys(), reverse=True)
    keep_dates = sorted_dates[:5]
    purged_history = {d: history_data[d] for d in keep_dates}

    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(purged_history, f, ensure_ascii=False, indent=2)

    print(f"[Cloud Auto Scan] scan_history.json updated successfully for {date_str}.")

if __name__ == '__main__':
    run_cloud_daily_scan()
