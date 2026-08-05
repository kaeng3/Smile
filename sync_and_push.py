# -*- coding: utf-8 -*-
"""
sync_and_push.py
Smile_Stock_Auto_Scanner 스캔 결과를 Smile_Stock_System(깃허브 연결 폴더)으로
복사하고 GitHub에 자동 푸시하는 스크립트.
"""
import os
import sys
import json
import shutil
import datetime
import subprocess

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

SCANNER_DIR = r"C:\Users\pc\Desktop\Smile_Stock_Auto_Scanner"
GIT_DIR     = os.path.dirname(os.path.abspath(__file__))  # Smile_Stock_System

now      = datetime.datetime.now()
date_str = now.strftime('%Y%m%d')

print(f"[SYNC] {date_str} 스캔 결과 동기화 시작...")

# ── 1. 세부 테마 DB 읽기 ─────────────────────────────────────────────
theme_db = {}
theme_path = os.path.join(GIT_DIR, 'stock_detail_themes.json')
if os.path.exists(theme_path):
    with open(theme_path, 'r', encoding='utf-8') as f:
        theme_db = json.load(f)

# ── 2. 각 전략 스캔 JSON 읽기 ────────────────────────────────────────
def load_scan(fname):
    path = os.path.join(SCANNER_DIR, fname)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def enrich(stocks, limit=12):
    result = []
    for s in stocks[:limit]:
        code = s.get('code', '')
        t_info   = theme_db.get(code, {})
        sub_t    = t_info.get('subthemes', [])
        cat      = t_info.get('category', '기타')
        detail   = f"{cat} > {', '.join(sub_t[:2])}" if sub_t else cat

        # 차트 이미지 복사 (Auto_Scanner → Smile_Stock_System/charts/날짜/)
        chart_path = ''
        src_chart = os.path.join(SCANNER_DIR, 'charts', date_str, f'{code}.png')
        dst_chart_dir = os.path.join(GIT_DIR, 'charts', date_str)
        dst_chart = os.path.join(dst_chart_dir, f'{code}.png')
        if os.path.exists(src_chart):
            os.makedirs(dst_chart_dir, exist_ok=True)
            if not os.path.exists(dst_chart):
                shutil.copyfile(src_chart, dst_chart)
            chart_path = f'charts/{date_str}/{code}.png'

        result.append({
            'code'        : code,
            'name'        : s.get('name', ''),
            'close'       : s.get('close', 0),
            'rate'        : round(float(s.get('rate', 0)), 2),
            'pattern'     : s.get('pattern', s.get('match_type', '')),
            'comment'     : s.get('comment', ''),
            'chart'       : chart_path,
            'category'    : cat,
            'subthemes'   : sub_t,
            'detail_theme': detail
        })
    return result

yey_list  = enrich(load_scan(f'scan_results_yey_{date_str}.json'))
v2_list   = enrich(load_scan(f'scan_results_v2_{date_str}.json'))
pod_list  = enrich(load_scan(f'scan_results_podosi_{date_str}.json'))

# ── 3. 500억 스캐너 연동 ─────────────────────────────────────────────
b500m_file = os.path.join(GIT_DIR, 'stock_scanner_500m', f'scan_results_integrated_{date_str}.json')
b500m_list = []
if os.path.exists(b500m_file):
    try:
        with open(b500m_file, 'r', encoding='utf-8') as f:
            d = json.load(f)
        for s in d.get('scan_results', [])[:15]:
            code   = s.get('code', '')
            t_info = theme_db.get(code, {})
            sub_t  = t_info.get('subthemes', [])
            cat    = t_info.get('category', '기타')
            b500m_list.append({
                'code'        : code,
                'name'        : s.get('name', ''),
                'close'       : s.get('close', 0),
                'rate'        : round(float(s.get('rate', 0)), 2),
                'pattern'     : f"{s.get('candle_class','500억봉')} 기준봉",
                'comment'     : s.get('commentary', '500억/150억 대량 수급 발생'),
                'chart'       : f"charts/{date_str}/{code}.png" if os.path.exists(os.path.join(GIT_DIR,'charts',date_str,f'{code}.png')) else '',
                'category'    : cat,
                'subthemes'   : sub_t,
                'detail_theme': f"{cat} > {', '.join(sub_t[:2])}" if sub_t else cat
            })
    except Exception as e:
        print(f"[500억봉 읽기 예외] {e}")

# ── 4. scan_history.json 갱신 ────────────────────────────────────────
history_file = os.path.join(GIT_DIR, 'scan_history.json')
history_data = {}
if os.path.exists(history_file):
    with open(history_file, 'r', encoding='utf-8') as f:
        history_data = json.load(f)

# 이전 500억 데이터 fallback
if not b500m_list:
    latest = sorted(history_data.keys(), reverse=True)
    if latest:
        b500m_list = history_data[latest[0]].get('b500m', [])

history_data[date_str] = {
    'yey'    : yey_list,
    'v2'     : v2_list,
    'podosi' : pod_list,
    'b500m'  : b500m_list
}

# 최근 5일치만 유지
sorted_dates = sorted(history_data.keys(), reverse=True)
purged = {d: history_data[d] for d in sorted_dates[:5]}

with open(history_file, 'w', encoding='utf-8') as f:
    json.dump(purged, f, ensure_ascii=False, indent=2)

print(f"[SYNC] scan_history.json {date_str} 반영 완료!")
print(f"  양음양:{len(yey_list)}개 / v2:{len(v2_list)}개 / 포도시:{len(pod_list)}개 / 500억:{len(b500m_list)}개")

# ── 5. GitHub 자동 푸시 ──────────────────────────────────────────────
print("\n[GitHub] 자동 업로드 시작...")
try:
    subprocess.run(["git", "add", "scan_history.json", "charts/"], cwd=GIT_DIR, check=False)
    subprocess.run(["git", "commit", "-m", f"Auto Update: {date_str}"], cwd=GIT_DIR, check=False)
    subprocess.run(["git", "push", "origin", "main"], cwd=GIT_DIR, check=False)
    print("[GitHub] 깃허브 웹사이트 반영 100% 완료!")
except Exception as e:
    print("[GitHub 업로드 오류]:", e)
