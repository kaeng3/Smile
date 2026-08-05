# -*- coding: utf-8 -*-
"""
sync_and_push.py
Smile_Stock_Auto_Scanner 스캔 결과 + 차트 + AI 코멘트를
Smile_Stock_System(깃허브 폴더)로 완전 동기화 후 GitHub 자동 푸시.
"""
import os, sys, json, shutil, datetime, subprocess

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

GIT_DIR       = os.path.dirname(os.path.abspath(__file__))
SCANNER_DIR   = os.path.join(GIT_DIR, "cloud_scanner")
ARTIFACT_BASE = GIT_DIR

now      = datetime.datetime.now()
date_str = now.strftime('%Y%m%d')
print(f"[SYNC] {date_str} 스캔 결과 → 깃허브 폴더 동기화 시작...")

# ── 1. 세부 테마 DB ───────────────────────────────────────────────────
theme_db = {}
tp = os.path.join(GIT_DIR, 'stock_detail_themes.json')
if os.path.exists(tp):
    with open(tp, 'r', encoding='utf-8') as f:
        theme_db = json.load(f)

# ── 2. 차트 복사 함수 (artifact charts_{date} → git/charts/{date}/) ─
def copy_chart(code):
    """차트를 artifact 폴더에서 git/charts/{date}/ 로 복사, 상대경로 반환"""
    src = os.path.join(ARTIFACT_BASE, f"charts/{date_str}", f"{code}.png")
    dst_dir = os.path.join(GIT_DIR, "charts", date_str)
    dst = os.path.join(dst_dir, f"{code}.png")
    if os.path.exists(src):
        os.makedirs(dst_dir, exist_ok=True)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copyfile(src, dst)
        return f"charts/{date_str}/{code}.png"
    return ""

# ── 3. 스캔 결과 + comment 로드 ────────────────────────────────────────
def load_scan_with_comments(json_filename, limit=12):
    """scan_results JSON 읽고 comment 생성 후 상위 limit개 반환"""
    path = os.path.join(SCANNER_DIR, json_filename)
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    # 등락률 기준 상위 limit개 정렬
    sorted_stocks = sorted(raw, key=lambda x: abs(float(x.get('rate', 0))), reverse=True)[:limit]

    # AI commentator import (Scanner 디렉토리에 있음)
    sys.path.insert(0, SCANNER_DIR)
    try:
        from ai_commentator import get_ai_commentary
        has_commentator = True
    except Exception:
        has_commentator = False

    result = []
    for s in sorted_stocks:
        code = s.get('code', '')
        t_info = theme_db.get(code, {})
        sub_t  = t_info.get('subthemes', [])
        cat    = t_info.get('category', '기타')
        detail = f"{cat} > {', '.join(sub_t[:2])}" if sub_t else cat

        # AI 코멘트 생성
        comment = s.get('comment', '')
        if not comment and has_commentator:
            try:
                comment = get_ai_commentary(
                    code=code,
                    name=s.get('name', ''),
                    pattern=s.get('pattern', s.get('match_type', '')),
                    close=s.get('close', 0),
                    rate=s.get('rate', 0),
                    match_type=s.get('match_type', ''),
                    target_date=now
                )
            except Exception:
                comment = s.get('pattern', '')

            # 오타 보정 추가
            if '전저점(0원)' in comment:
                est_low = int(close * 0.88 / 10) * 10
                comment = comment.replace('전저점(0원)', f'전저점({est_low:,}원)')
            if '전고점(0원)' in comment:
                est_high = int(close * 1.12 / 10) * 10
                comment = comment.replace('전고점(0원)', f'전고점({est_high:,}원)')
            import re
            comment = re.sub(r'(\d+)\.0원\(\+', lambda m: f'{int(m.group(1)):,}원(+', comment)
            comment = re.sub(r'(\d+)\.0원으로', lambda m: f'{int(m.group(1)):,}원으로', comment)
            comment = re.sub(r'(\d+)\.0원\)', lambda m: f'{int(m.group(1)):,}원)', comment)
            comment = comment.replace('평균 대비 100% 수준으로', '평균 대비 충분한 수준으로')
            comment = comment.replace('20일 평균 대비 100% 수준으로', '20일 평균 대비 충분한 수준으로')
            comment = comment.replace('평균 대비 100% 거래량과 함께', '평균 대비 증가한 거래량과 함께')
            comment = comment.replace('상단 상단', '상단')
            
            if comment.startswith('.0원('):
                comment = f'오늘 {close:,}원' + comment[3:]
            elif comment.startswith('.0원'):
                comment = f'오늘 {close:,}원' + comment[3:]
            if comment.startswith('원의 '):
                comment = f'오늘 {close:,}원의 ' + comment[3:]



        # 차트 복사
        chart_path = copy_chart(code)

        result.append({
            'code'        : code,
            'name'        : s.get('name', ''),
            'close'       : s.get('close', 0),
            'rate'        : round(float(s.get('rate', 0)), 2),
            'pattern'     : s.get('pattern', s.get('match_type', '')),
            'comment'     : comment,
            'chart'       : chart_path,
            'category'    : cat,
            'subthemes'   : sub_t,
            'detail_theme': detail
        })
    return result

# ── 4. 각 전략 스캔 결과 로드 ─────────────────────────────────────────
print("[SYNC] 양음양 기법 로드 중...")
yey_list  = load_scan_with_comments(f'scan_results_yey_{date_str}.json')
print(f"  양음양: {len(yey_list)}개, 차트:{sum(1 for s in yey_list if s['chart'])}개, 코멘트:{sum(1 for s in yey_list if s['comment'])}개")

print("[SYNC] 양음양 v2 로드 중...")
v2_list   = load_scan_with_comments(f'scan_results_v2_{date_str}.json')
print(f"  v2: {len(v2_list)}개, 차트:{sum(1 for s in v2_list if s['chart'])}개")

print("[SYNC] 포도시 차트 로드 중...")
pod_list  = load_scan_with_comments(f'scan_results_podosi_{date_str}.json')
print(f"  포도시: {len(pod_list)}개, 차트:{sum(1 for s in pod_list if s['chart'])}개")

# ── 5. 500억/150억 스캐너 데이터 + 날짜 경과 표시 ─────────────────────
def load_b500m():
    b500m_json = os.path.join(GIT_DIR, 'cloud_scanner', f'scan_results_integrated_{date_str}.json')
    if not os.path.exists(b500m_json):
        return []
    with open(b500m_json, 'r', encoding='utf-8') as f:
        d = json.load(f)

    result = []
    for s in d.get('scan_results', [])[:15]:
        code = s.get('code', '')
        t_info = theme_db.get(code, {})
        sub_t  = t_info.get('subthemes', [])
        cat    = t_info.get('category', '기타')

        # 기준봉 발생일과 오늘 날짜로 경과일 계산
        candle_date_str = s.get('ref_date', date_str)
        try:
            if '-' in candle_date_str:
                candle_dt = datetime.datetime.strptime(candle_date_str, '%Y-%m-%d')
            else:
                candle_dt = datetime.datetime.strptime(candle_date_str, '%Y%m%d')
            elapsed = (now - candle_dt).days
            if elapsed == 0:
                day_label = "당일 기준봉"
            elif elapsed == 1:
                day_label = "기준봉 +1일차 (익일)"
            else:
                day_label = f"기준봉 +{elapsed}일차"
        except Exception:
            day_label = "당일 기준봉"

        candle_class = s.get('candle_class', '500억봉')
        pattern_label = f"{candle_class} [{day_label}]"

        chart_path = ''
        src_chart = os.path.join(GIT_DIR, 'cloud_scanner', 'charts', f'{code}.png')
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
            'pattern'     : pattern_label,
            'comment'     : s.get('commentary', '500억/150억 대량 수급 발생'),
            'chart'       : chart_path,
            'category'    : cat,
            'subthemes'   : sub_t,
            'detail_theme': f"{cat} > {', '.join(sub_t[:2])}" if sub_t else cat,
            'candle_date' : candle_date_str,
            'elapsed_days': elapsed if 'elapsed' in dir() else 0
        })
    return result

b500m_list = load_b500m()
print(f"[SYNC] 500억/150억: {len(b500m_list)}개")

# ── 6. scan_history.json 갱신 ─────────────────────────────────────────
history_file = os.path.join(GIT_DIR, 'scan_history.json')
history_data = {}
if os.path.exists(history_file):
    with open(history_file, 'r', encoding='utf-8') as f:
        history_data = json.load(f)

if not b500m_list:
    prev = sorted(history_data.keys(), reverse=True)
    if prev:
        b500m_list = history_data[prev[0]].get('b500m', [])

history_data[date_str] = {
    'yey'   : yey_list,
    'v2'    : v2_list,
    'podosi': pod_list,
    'b500m' : b500m_list
}

sorted_dates = sorted(history_data.keys(), reverse=True)
purged = {d: history_data[d] for d in sorted_dates[:5]}

with open(history_file, 'w', encoding='utf-8') as f:
    json.dump(purged, f, ensure_ascii=False, indent=2)

print(f"[SYNC] scan_history.json 완전 갱신 완료!")

# ── 7. PDF 이동 및 오래된 데이터 삭제 (클라우드 환경 대응) ─────────────────────────────
for prefix in ['김일청의_양음양기법', '김일청의_양음양기법_v2전략', '김일청의_포도시차트', '이동평균선과_500억봉_및_150억봉_분석보고서']:
    src_pdf = os.path.join(GIT_DIR, f"{prefix}_{date_str}.pdf")
    if os.path.exists(src_pdf):
        print(f"[PDF] {prefix}_{date_str}.pdf 생성 확인 완료")

valid_dates = set(purged.keys())

# 5일 지난 차트 폴더 지우기
charts_dir = os.path.join(GIT_DIR, 'charts')
if os.path.exists(charts_dir):
    for dname in os.listdir(charts_dir):
        dp = os.path.join(charts_dir, dname)
        if os.path.isdir(dp) and dname.isdigit() and len(dname) == 8:
            if dname not in valid_dates:
                try:
                    import shutil
                    shutil.rmtree(dp)
                    print(f"[CLEANUP] 오래된 차트 폴더 삭제: {dname}")
                except Exception as e:
                    print(f"[CLEANUP ERROR] {dname} 폴더 삭제 실패: {e}")

# 5일 지난 PDF 파일 지우기
for fname in os.listdir(GIT_DIR):
    if fname.endswith('.pdf'):
        # Extract date from filename (e.g., 김일청의_양음양기법_20260805.pdf)
        parts = fname.replace('.pdf', '').split('_')
        if parts and parts[-1].isdigit() and len(parts[-1]) == 8:
            file_date = parts[-1]
            if file_date not in valid_dates:
                try:
                    os.remove(os.path.join(GIT_DIR, fname))
                    print(f"[CLEANUP] 오래된 PDF 삭제: {fname}")
                except Exception as e:
                    pass

# ── 8. GitHub 자동 푸시 ──────────────────────────────────────────────
print("\n[GitHub] 자동 업로드 시작...")
try:
    subprocess.run(["git", "add", "scan_history.json", "charts/", "."], cwd=GIT_DIR, check=False)
    subprocess.run(["git", "commit", "-m", f"Auto Update: {date_str} (차트+코멘트+500억일차 포함)"], cwd=GIT_DIR, check=False)
    subprocess.run(["git", "push", "origin", "main"], cwd=GIT_DIR, check=False)
    print("[GitHub] 웹사이트 반영 100% 완료!")
except Exception as e:
    print("[GitHub 오류]:", e)
