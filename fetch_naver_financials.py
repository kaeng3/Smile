# -*- coding: utf-8 -*-
"""
fetch_naver_financials.py
네이버금융(WiseReport) 기업정보 페이지에서 연간 매출액/영업이익/당기순이익
추이를 스크래핑해서 stock_financials.json으로 저장한다.

DART Open API보다 응답이 훨씬 빨라서(공식 정부 API가 아닌 일반 웹 요청)
같은 주간 워크플로우 안에서 짧은 시간에 전 종목을 처리할 수 있다.
"""
import os
import re
import sys
import json
import time
import threading
import concurrent.futures
import requests
from bs4 import BeautifulSoup

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

GIT_DIR = os.path.dirname(os.path.abspath(__file__))
THEMES_PATH = os.path.join(GIT_DIR, 'stock_detail_themes.json')
OUTPUT_PATH = os.path.join(GIT_DIR, 'stock_financials.json')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Referer': 'https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx',
}

_token_lock = threading.Lock()
_token_cache = {'encparam': None, 'id': None, 'fetched_at': 0}


def get_token(sample_code='005930'):
    """페이지 진입 시 발급되는 encparam/id 토큰. 세션성이라 주기적으로만 새로 받는다."""
    with _token_lock:
        now = time.time()
        if _token_cache['encparam'] and (now - _token_cache['fetched_at'] < 300):
            return _token_cache['encparam'], _token_cache['id']

        url = f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={sample_code}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        text = r.text

        m_enc = re.search(r"encparam\s*:\s*'([^']+)'", text)
        m_id = re.search(r"\bid\s*:\s*'([^']+)'", text)
        if not m_enc:
            raise RuntimeError("encparam 파싱 실패 (페이지 구조 변경 가능성)")

        enc = m_enc.group(1)
        id_ = m_id.group(1) if m_id else ''
        _token_cache.update({'encparam': enc, 'id': id_, 'fetched_at': now})
        return enc, id_


ROW_KEYS = {
    '매출액': 'revenue',
    '영업이익': 'operating_profit',
    '당기순이익': 'net_income',
}


def parse_year(header_text):
    """'2024/12' 또는 '2024.12' 같은 헤더에서 연도만 추출"""
    m = re.search(r'(20\d{2})', header_text)
    return int(m.group(1)) if m else None


def parse_amount(text):
    """'1,234' -> 1234 (억원 단위 그대로 사용). '-'나 빈값이면 None"""
    text = (text or '').strip().replace(',', '')
    if text in ('', '-', 'N/A'):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_one(code):
    try:
        enc, id_ = get_token()
        url = "https://navercomp.wisereport.co.kr/v2/company/ajax/cF1001.aspx"
        params = {
            'cmp_cd': code,
            'fin_typ': 0,   # 0: 주재무제표(연결 우선, 없으면 별도)
            'freq_typ': 'Y',  # 연간
            'encparam': enc,
            'id': id_,
        }
        r = requests.get(url, params=params, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table')
        if not table:
            return code, []

        header_cells = [th.get_text(strip=True) for th in table.find_all('th')]
        years = [parse_year(h) for h in header_cells]
        years = [y for y in years if y]

        by_key = {}
        for row in table.find_all('tr'):
            cells = row.find_all('td')
            if not cells:
                continue
            label_cell = row.find(['th', 'td'])
            label = label_cell.get_text(strip=True) if label_cell else ''
            matched_key = None
            for k in ROW_KEYS:
                if label.startswith(k):
                    matched_key = ROW_KEYS[k]
                    break
            if not matched_key or matched_key in by_key:
                continue
            values = [parse_amount(td.get_text()) for td in cells]
            by_key[matched_key] = values

        if not years or not by_key:
            return code, []

        # 단위: 네이버금융 표는 보통 '억원' 단위로 이미 표시됨 -> 원 단위로 환산해서
        # 기존(DART, 원단위) 구조와 통일
        results = []
        n = min(len(years), max((len(v) for v in by_key.values()), default=0))
        for i in range(n):
            year = years[i]
            entry = {'year': year}
            for field in ('revenue', 'operating_profit', 'net_income'):
                vals = by_key.get(field)
                v = vals[i] if vals and i < len(vals) else None
                entry[field] = int(v * 100000000) if v is not None else None
            results.append(entry)

        results = [r for r in results if any(r[f] is not None for f in ('revenue', 'operating_profit', 'net_income'))]
        results.sort(key=lambda r: r['year'])
        return code, results
    except Exception:
        return code, []


def main():
    if not os.path.exists(THEMES_PATH):
        print("[NAVER] stock_detail_themes.json이 없어 대상 종목을 알 수 없습니다.")
        return

    with open(THEMES_PATH, 'r', encoding='utf-8') as f:
        codes = list(json.load(f).keys())

    print(f"[NAVER] 재무제표 조회 대상: {len(codes)}종목")

    try:
        get_token()
    except Exception as e:
        print("[NAVER] 초기 토큰 발급 실패:", e)
        return

    # ── DEBUG: 샘플 3종목 원본 응답을 파일로 저장 (파싱 문제 진단용) ──
    if os.environ.get('NAVER_DEBUG') == '1':
        debug_info = {}
        for sample_code in codes[:3]:
            try:
                enc, id_ = get_token()
                url = "https://navercomp.wisereport.co.kr/v2/company/ajax/cF1001.aspx"
                params = {'cmp_cd': sample_code, 'fin_typ': 0, 'freq_typ': 'Y', 'encparam': enc, 'id': id_}
                r = requests.get(url, params=params, headers=HEADERS, timeout=12)
                debug_info[sample_code] = {
                    'status_code': r.status_code,
                    'url': r.url,
                    'text_head': r.text[:3000],
                }
            except Exception as e:
                debug_info[sample_code] = {'error': str(e)}
        with open(os.path.join(GIT_DIR, 'naver_debug.json'), 'w', encoding='utf-8') as f:
            json.dump(debug_info, f, ensure_ascii=False, indent=2)
        print("[NAVER] 디버그 덤프 저장 완료: naver_debug.json")
        return

    financials = {}
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
                financials = json.load(f)
        except Exception:
            financials = {}

    done = 0
    ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(fetch_one, code): code for code in codes}
        for fut in concurrent.futures.as_completed(futures):
            code, results = fut.result()
            if results:
                financials[code] = results
                ok += 1
            done += 1
            if done % 300 == 0:
                print(f"[NAVER] 진행 {done}/{len(codes)} (성공 {ok}건)")

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(financials, f, ensure_ascii=False)

    print(f"[NAVER] stock_financials.json 저장 완료: 총 {len(financials)}종목 (이번 실행 성공 {ok}건)")


if __name__ == '__main__':
    main()
