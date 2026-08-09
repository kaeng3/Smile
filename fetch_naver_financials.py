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

_thread_local = threading.local()


def get_session():
    if not hasattr(_thread_local, 'session'):
        s = requests.Session()
        s.headers.update(HEADERS)
        _thread_local.session = s
    return _thread_local.session


def parse_shareholder_info(html_text):
    """같은 페이지의 '기업별 주주현황' 표에서 최대주주등 지분율/보유주식수를 뽑는다."""
    try:
        soup = BeautifulSoup(html_text, 'html.parser')
        table = None
        for t in soup.find_all('table'):
            if '주주현황' in (t.get('summary') or ''):
                table = t
                break
        if not table:
            return None
        tbody = table.find('tbody')
        if not tbody:
            return None
        row = tbody.find('tr')  # 첫 행 = 최대주주등
        if not row:
            return None
        label_cell = row.find('th')
        label = label_cell.get_text(strip=True) if label_cell else '최대주주등'
        tds = row.find_all('td')
        if len(tds) < 3:
            return None
        count = parse_amount(tds[0].get_text())
        shares = parse_amount(tds[1].get_text())
        percent = parse_amount(tds[2].get_text())
        if percent is None:
            return None
        return {
            'label': label,
            'holder_count': int(count) if count is not None else None,
            'shares': int(shares) if shares is not None else None,
            'percent': percent,
        }
    except Exception:
        return None


def get_token(code):
    """해당 종목 코드로 접속했을 때 발급되는 encparam/id 토큰 + 세션 쿠키 + 대주주 정보를 가져온다.
    encparam은 종목(cmp_cd)에 종속된 값으로 보여서, 다른 종목 조회 시 재사용하면
    안 되고 종목마다 새로 받아야 한다(재사용 시 더미/에러 데이터가 내려옴).
    스레드마다 별도 세션을 써야 쿠키가 서로 섞이지 않는다."""
    session = get_session()
    url = f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={code}"
    r = session.get(url, timeout=10)
    text = r.text

    m_enc = re.search(r"encparam\s*:\s*'([^']+)'", text)
    m_id = re.search(r"\bid\s*:\s*'([^']+)'", text)
    if not m_enc:
        raise RuntimeError("encparam 파싱 실패 (페이지 구조 변경 가능성)")

    shareholder = parse_shareholder_info(text)

    enc = m_enc.group(1)
    id_ = m_id.group(1) if m_id else ''
    return enc, id_, shareholder


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
    shareholder = None
    try:
        enc, id_, shareholder = get_token(code)
        url = "https://navercomp.wisereport.co.kr/v2/company/ajax/cF1001.aspx"
        params = {
            'cmp_cd': code,
            'fin_typ': 0,   # 0: 주재무제표(연결 우선, 없으면 별도)
            'freq_typ': 'Y',  # 연간
            'encparam': enc,
            'id': id_,
        }
        r = get_session().get(url, params=params, timeout=12)
        soup = BeautifulSoup(r.text, 'html.parser')
        tables = soup.find_all('table')
        # 첫 번째 테이블은 크롤링 방지용 더미(같은 숫자 반복) 테이블이라 두 번째를 써야 함
        if len(tables) < 2:
            return code, [], shareholder
        table = tables[1]

        thead = table.find('thead')
        if not thead:
            return code, [], shareholder

        # 연도 헤더: "2024/12" 형태. "(E)"(추정치) 컬럼은 실적이 아니므로 제외
        year_cols = []  # [(col_index_in_row, year)]
        header_ths = thead.find_all('th')
        col_idx = 0
        for th in header_ths:
            txt = th.get_text(strip=True)
            year = parse_year(txt)
            if year and '(E)' not in txt:
                year_cols.append((col_idx, year))
            if year:  # 연도가 있는 th만 실제 데이터 컬럼(rowspan 헤더 제외)
                col_idx += 1

        if not year_cols:
            return code, [], shareholder

        by_key = {}
        tbody = table.find('tbody')
        if not tbody:
            return code, [], shareholder
        for row in tbody.find_all('tr'):
            label_cell = row.find('th')
            label = label_cell.get_text(strip=True) if label_cell else ''
            matched_key = None
            for k in ROW_KEYS:
                if label.startswith(k):
                    matched_key = ROW_KEYS[k]
                    break
            if not matched_key or matched_key in by_key:
                continue
            cells = row.find_all('td')
            values = []
            for td in cells:
                title_attr = (td.get('title') or '').strip()
                text_val = td.get_text(strip=True)
                values.append(parse_amount(title_attr) if title_attr else parse_amount(text_val))
            by_key[matched_key] = values

        if not by_key:
            return code, [], shareholder

        results = []
        for col_idx, year in year_cols:
            entry = {'year': year}
            for field in ('revenue', 'operating_profit', 'net_income'):
                vals = by_key.get(field)
                v = vals[col_idx] if vals and col_idx < len(vals) else None
                entry[field] = int(round(v * 100000000)) if v is not None else None
            if any(entry[f] is not None for f in ('revenue', 'operating_profit', 'net_income')):
                results.append(entry)

        results.sort(key=lambda r: r['year'])
        return code, results, shareholder
    except Exception:
        return code, [], shareholder


SHAREHOLDER_OUTPUT_PATH = os.path.join(GIT_DIR, 'stock_shareholders.json')


def main():
    if os.environ.get('NAVER_DEBUG3') == '1':
        session = get_session()
        r = session.get('https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd=126730', timeout=10)
        text = r.text
        out = {'total_len': len(text)}
        for kw in ['WICS', '코스닥 전기', '주요주주', '최대주주']:
            idx = text.find(kw)
            out[kw] = text[max(0, idx - 200): idx + 1200] if idx >= 0 else f'(찾지 못함)'
        with open(os.path.join(GIT_DIR, 'naver_debug3.json'), 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("[DEBUG3] 저장 완료")
        return

    if not os.path.exists(THEMES_PATH):
        print("[NAVER] stock_detail_themes.json이 없어 대상 종목을 알 수 없습니다.")
        return

    with open(THEMES_PATH, 'r', encoding='utf-8') as f:
        codes = list(json.load(f).keys())

    print(f"[NAVER] 재무제표/대주주 조회 대상: {len(codes)}종목")

    try:
        get_token('005930')
    except Exception as e:
        print("[NAVER] 초기 토큰 발급 실패:", e)
        return

    financials = {}
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
                financials = json.load(f)
        except Exception:
            financials = {}

    shareholders = {}

    done = 0
    ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(fetch_one, code): code for code in codes}
        for fut in concurrent.futures.as_completed(futures):
            code, results, shareholder = fut.result()
            if results:
                financials[code] = results
                ok += 1
            if shareholder:
                shareholders[code] = shareholder
            done += 1
            if done % 300 == 0:
                print(f"[NAVER] 진행 {done}/{len(codes)} (재무 성공 {ok}건)")

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(financials, f, ensure_ascii=False)
    with open(SHAREHOLDER_OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(shareholders, f, ensure_ascii=False)

    print(f"[NAVER] stock_financials.json 저장 완료: 총 {len(financials)}종목 (이번 실행 성공 {ok}건)")
    print(f"[NAVER] stock_shareholders.json 저장 완료: 총 {len(shareholders)}종목")


if __name__ == '__main__':
    main()
