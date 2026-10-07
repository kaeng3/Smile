# -*- coding: utf-8 -*-
"""
fetch_infostock_reasons.py
인포스탁 '당일 증시 요약'에서 종목별 상승 사유를 읽어온다.

- 사용 꼭지: 증시요약(6) 특징 상한가 및 급등종목 / (4)(5) 특징 종목(코스피·코스닥)
- 인포스탁 정책상 당일 자료는 유료 회원용이고, 무료로는 전일자부터 볼 수 있다.
  그래서 '오늘(KST)보다 이전 날짜'만 조회한다. (오늘 날짜를 넣으면 빈 결과)
- 원문은 저작권이 있으므로 화면에 그대로 게시하지 않고 AI 분석의 참고 자료로만 쓴다.
"""
import re
import datetime
import requests
from bs4 import BeautifulSoup

LIST_URL = 'https://api.infostock.co.kr:9081/web/flash/list'
SOURCE_PAGE = 'https://infostock.co.kr/MarketNews/TodaySummary'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Content-Type': 'application/json',
    'Origin': 'https://infostock.co.kr',
    'Referer': SOURCE_PAGE,
}
JUMP = 'MARKET_FLASH_STOCK_JUMP'
FEATURED = ('MARKET_FLASH_STOCK_FEATURED_KOSPI', 'MARKET_FLASH_STOCK_FEATURED_KOSDAQ')
MAX_DETAIL = 500


def _kst_today():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime('%Y%m%d')


def _clean(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def _code_of(cell):
    a = cell.find('a', href=re.compile(r'code='))
    if a:
        m = re.search(r'code=([0-9A-Z]{6})', a['href'])
        if m:
            return m.group(1)
    m = re.search(r'\(([0-9A-Z]{6})\)', cell.get_text())
    return m.group(1) if m else None


def parse_jump(html):
    """증시요약(6): 종목 | 상한가일수 | 사유 표 → {code: 사유}"""
    out = {}
    for tr in BeautifulSoup(html, 'html.parser').find_all('tr'):
        tds = tr.find_all('td')
        if len(tds) < 3:
            continue
        code = _code_of(tds[0])
        reason = _clean(tds[-1].get_text(' '))
        if code and reason:
            out[code] = reason
    return out


def parse_featured(html, name_to_code):
    """증시요약(4)(5): [종목 칸(rowspan=2) | 이슈 제목] 다음 줄에 [상세 설명].
    그룹주 칸('HLB 그룹주')은 상세 설명 끝의 '[종목]: A, B' 목록으로 종목을 찾는다.
    → {code: (제목, 상세)}"""
    out = {}
    rows = BeautifulSoup(html, 'html.parser').find_all('tr')
    for i, tr in enumerate(rows):
        tds = tr.find_all('td')
        if len(tds) != 2 or not tds[0].get('rowspan'):
            continue
        headline = _clean(tds[1].get_text(' '))
        detail = ''
        if i + 1 < len(rows):
            nxt = rows[i + 1].find_all('td')
            if len(nxt) == 1:
                detail = _clean(nxt[0].get_text(' '))
        codes = []
        code = _code_of(tds[0])
        if code:
            codes.append(code)
        m = re.search(r'\[종목\]\s*:\s*(.+)$', detail)
        if m:
            for nm in m.group(1).split(','):
                c = name_to_code.get(nm.strip())
                if c:
                    codes.append(c)
        for c in codes:
            out.setdefault(c, (headline, detail[:MAX_DETAIL]))
    return out


def fetch_reasons(date_str, name_to_code=None, timeout=15):
    """date_str(YYYYMMDD) 하루치 {code: {'reason', 'detail'}}. 오늘 이후 날짜는 조회하지 않는다."""
    if date_str >= _kst_today():
        return {}
    body = {'menuType': 'MENU_TODAY_SUMMARY', 'count': 50, 'startDate': date_str, 'endDate': date_str}
    resp = requests.post(LIST_URL, json=body, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    items = [it for it in (resp.json().get('data') or {}).get('items') or [] if it.get('sendDate') == date_str]

    result = {}
    for it in items:
        if it.get('newsType1') == JUMP:
            for code, reason in parse_jump(it.get('content', '')).items():
                result.setdefault(code, {'reason': reason, 'detail': ''})
    for it in items:
        if it.get('newsType1') in FEATURED:
            for code, (headline, detail) in parse_featured(it.get('content', ''), name_to_code or {}).items():
                entry = result.setdefault(code, {'reason': headline, 'detail': ''})
                if not entry['detail']:
                    entry['detail'] = detail
    return result


if __name__ == '__main__':
    import sys, json
    d = sys.argv[1] if len(sys.argv) > 1 else (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y%m%d')
    print(json.dumps(fetch_reasons(d), ensure_ascii=False, indent=1)[:3000])
