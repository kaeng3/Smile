# -*- coding: utf-8 -*-
"""
fetch_dart_financials.py
DART(전자공시시스템) Open API로 종목별 최근 3개년 연간 재무 요약
(매출액/영업이익/당기순이익)을 받아와 stock_financials.json으로 저장한다.

매일 돌 필요 없는 무거운 작업이라 별도의 주간 워크플로우(weekly_financials.yml)에서 실행한다.
"""
import os
import io
import sys
import json
import time
import zipfile
import datetime
import concurrent.futures
import xml.etree.ElementTree as ET
import requests

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

GIT_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY = os.environ.get('DART_API_KEY', '')
CORP_CODE_CACHE = os.path.join(GIT_DIR, 'dart_corp_code_map.json')
THEMES_PATH = os.path.join(GIT_DIR, 'stock_detail_themes.json')
OUTPUT_PATH = os.path.join(GIT_DIR, 'stock_financials.json')

# 사업보고서(연간), 최신 연도부터 최대 3개년 조회
REPRT_CODE = '11011'
THIS_YEAR = datetime.datetime.now().year


def fetch_corp_code_map():
    """DART: 6자리 종목코드 -> 8자리 고유번호(corp_code) 매핑. 하루 한 번만 새로 받고 로컬 캐시."""
    if os.path.exists(CORP_CODE_CACHE):
        age_days = (time.time() - os.path.getmtime(CORP_CODE_CACHE)) / 86400
        if age_days < 25:  # 회사 목록은 자주 안 바뀌므로 캐시를 오래 재사용
            with open(CORP_CODE_CACHE, 'r', encoding='utf-8') as f:
                return json.load(f)

    print("[DART] corp_code 매핑 파일 다운로드 중...")
    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={API_KEY}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    xml_bytes = zf.read('CORPCODE.xml')
    root = ET.fromstring(xml_bytes)

    mapping = {}
    for item in root.findall('list'):
        stock_code = (item.findtext('stock_code') or '').strip()
        corp_code = (item.findtext('corp_code') or '').strip()
        if stock_code and corp_code:
            mapping[stock_code] = corp_code

    with open(CORP_CODE_CACHE, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False)

    print(f"[DART] corp_code 매핑 {len(mapping)}건 저장")
    return mapping


def extract_accounts(items):
    """fnlttSinglAcntAll 응답 list에서 매출액/영업이익/당기순이익 당기(thstrm) 금액 추출"""
    wanted = {
        '매출액': None, '수익(매출액)': None,
        '영업이익': None,
        '당기순이익': None, '당기순이익(손실)': None,
    }
    for it in items:
        nm = (it.get('account_nm') or '').strip()
        if nm in wanted:
            amt = it.get('thstrm_amount', '')
            try:
                wanted[nm] = int(amt.replace(',', '')) if amt not in (None, '', '-') else None
            except Exception:
                wanted[nm] = None

    revenue = wanted['매출액'] if wanted['매출액'] is not None else wanted['수익(매출액)']
    net_income = wanted['당기순이익'] if wanted['당기순이익'] is not None else wanted['당기순이익(손실)']
    return revenue, wanted['영업이익'], net_income


def fetch_one_stock(code, corp_code):
    """한 종목의 최근 3개년 연간 재무 요약을 가져온다."""
    results = []
    for offset in range(1, 4):  # 작년, 재작년, 3년전 (올해 사업보고서는 아직 미공시)
        year = THIS_YEAR - offset
        url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
        params = {
            'crtfc_key': API_KEY,
            'corp_code': corp_code,
            'bsns_year': str(year),
            'reprt_code': REPRT_CODE,
            'fs_div': 'CFS',  # 연결재무제표 우선
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
            if data.get('status') == '013':  # 연결 없으면 개별로 재시도
                params['fs_div'] = 'OFS'
                resp = requests.get(url, params=params, timeout=15)
                data = resp.json()

            if data.get('status') != '000':
                continue

            revenue, op_profit, net_income = extract_accounts(data.get('list', []))
            if revenue is None and op_profit is None and net_income is None:
                continue

            results.append({
                'year': year,
                'revenue': revenue,
                'operating_profit': op_profit,
                'net_income': net_income,
            })
        except Exception:
            continue
    results.sort(key=lambda r: r['year'])
    return code, results


def main():
    if not API_KEY:
        print("[DART] DART_API_KEY 시크릿이 없습니다. 건너뜁니다.")
        return

    if not os.path.exists(THEMES_PATH):
        print("[DART] stock_detail_themes.json이 없어 대상 종목을 알 수 없습니다.")
        return

    with open(THEMES_PATH, 'r', encoding='utf-8') as f:
        theme_codes = list(json.load(f).keys())

    corp_map = fetch_corp_code_map()

    targets = [(c, corp_map[c]) for c in theme_codes if c in corp_map]
    print(f"[DART] 재무제표 조회 대상: {len(targets)}종목 (테마DB 기준 {len(theme_codes)}종목 중 DART 매핑 성공)")

    financials = {}
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
                financials = json.load(f)
        except Exception:
            financials = {}

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_one_stock, code, corp_code): code for code, corp_code in targets}
        for fut in concurrent.futures.as_completed(futures):
            code, results = fut.result()
            if results:
                financials[code] = results
            done += 1
            if done % 200 == 0:
                print(f"[DART] 진행 {done}/{len(targets)}")

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(financials, f, ensure_ascii=False)

    print(f"[DART] stock_financials.json 저장 완료: {len(financials)}종목")


if __name__ == '__main__':
    main()
