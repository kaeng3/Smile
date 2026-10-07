# -*- coding: utf-8 -*-
"""
fetch_featured_stock_news.py
오늘 스캔에 잡힌 종목들(양음양/v2/포도시/500억봉)을 대상으로
네이버 뉴스에서 "{종목명} 특징주"를 검색해 시간/언론사/링크가 포함된
기사 목록을 모아 featured_stock_news.json으로 저장한다.
(베타 실험실 1: 섹터별 > 종목별 특징주 뉴스)
"""
import os
import re
import json
import datetime
import urllib.parse
import concurrent.futures
import requests
from bs4 import BeautifulSoup

GIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_HISTORY_PATH = os.path.join(GIT_DIR, 'scan_history.json')
THEMES_PATH = os.path.join(GIT_DIR, 'stock_detail_themes.json')
OUTPUT_PATH = os.path.join(GIT_DIR, 'featured_stock_news.json')

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}


def get_today_stock_list(target_date_str):
    """오늘(target_date_str) 양음양 v2/포도시/500억봉에 잡힌 종목을 code 기준으로 합친다."""
    if not os.path.exists(SCAN_HISTORY_PATH):
        return {}
    with open(SCAN_HISTORY_PATH, 'r', encoding='utf-8') as f:
        scan_data = json.load(f)
    day = scan_data.get(target_date_str, {})
    stocks = {}
    for key in ('v2', 'podosi', 'b500m'):
        for s in day.get(key, []):
            code = s.get('code')
            if code and code not in stocks:
                stocks[code] = s.get('name')
    return stocks


def parse_time_text(time_text, today):
    """네이버 뉴스 검색결과의 상대/절대 시간 표기를 오늘 날짜의 HH:MM로 최대한 변환.
    예) '3시간 전' '52분 전' '2026.08.10.' 등. 오늘이 아닌 기사면 None을 반환해 제외시킨다."""
    time_text = (time_text or '').strip()
    m = re.match(r'^(\d+)분 전$', time_text)
    if m:
        t = today - datetime.timedelta(minutes=int(m.group(1)))
        return t.strftime('%H:%M')
    m = re.match(r'^(\d+)시간 전$', time_text)
    if m:
        t = today - datetime.timedelta(hours=int(m.group(1)))
        return t.strftime('%H:%M')
    m = re.match(r'^(\d{2}):(\d{2})$', time_text)
    if m:
        return time_text
    m = re.match(r'^(\d+)일 전$', time_text)
    if m:
        return None  # 오늘 기사가 아니면 제외
    m = re.match(r'^(\d{4})\.(\d{1,2})\.(\d{1,2})\.?\s*(\d{1,2}):(\d{2})$', time_text)
    if m:
        article_date = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return f'{int(m.group(4)):02d}:{m.group(5)}' if article_date == today.date() else None
    m = re.match(r'^(\d{4})\.(\d{1,2})\.(\d{1,2})\.?$', time_text)
    if m:
        article_date = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return '00:00' if article_date == today.date() else None
    return None  # 그 외 형식(절대 날짜 등)도 오늘인지 확신할 수 없어 일단 제외


def parse_article_datetime(time_text, today):
    """'3시간 전'/'2일 전'/'2026.10.01.' 같은 표기를 기사 시각(datetime)으로. 모르면 None.
    'N일 전'·날짜만 있는 경우는 시각을 알 수 없어 그날 00:00으로 둔다."""
    t = (time_text or '').strip()
    base = today.replace(second=0, microsecond=0, tzinfo=None)
    m = re.match(r'^(\d+)분 전$', t)
    if m:
        return base - datetime.timedelta(minutes=int(m.group(1)))
    m = re.match(r'^(\d+)시간 전$', t)
    if m:
        return base - datetime.timedelta(hours=int(m.group(1)))
    m = re.match(r'^(\d{2}):(\d{2})$', t)
    if m:
        return base.replace(hour=int(m.group(1)), minute=int(m.group(2)))
    m = re.match(r'^(\d+)일 전$', t)
    if m:
        d = (base - datetime.timedelta(days=int(m.group(1)))).date()
        return datetime.datetime(d.year, d.month, d.day)
    m = re.match(r'^(\d{4})\.(\d{1,2})\.(\d{1,2})\.?(?:\s*(\d{1,2}):(\d{2}))?$', t)
    if m:
        hh = int(m.group(4)) if m.group(4) else 0
        mm = int(m.group(5)) if m.group(5) else 0
        return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), hh, mm)
    return None


_RELEVANCE_WORDS = ('특징주', '호재', '계약', '수주', '승인', '임상', '공급', '상한가', '급등', '상승')


NAVER_API_URL = 'https://openapi.naver.com/v1/search/news.json'


def _naver_api_keys():
    cid = os.environ.get('NAVER_CLIENT_ID', '').strip()
    secret = os.environ.get('NAVER_CLIENT_SECRET', '').strip()
    return (cid, secret) if cid and secret else None


def _press_from_link(link):
    host = urllib.parse.urlparse(link or '').netloc.lower()
    return host[4:] if host.startswith('www.') else host


def _fetch_naver_api(query, keys, display=100):
    """네이버 공식 뉴스 검색 API(최신순). 실패하면 최대 3번까지 쉬었다가 다시 시도하고,
    끝내 실패하면 예외를 올린다(빈 결과로 '뉴스 없음' 처리되지 않도록)."""
    import time
    headers = {'X-Naver-Client-Id': keys[0], 'X-Naver-Client-Secret': keys[1]}
    params = {'query': query, 'display': display, 'sort': 'date'}
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(NAVER_API_URL, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('items', [])
            last_err = f'HTTP {resp.status_code}: {resp.text[:120]}'
            if resp.status_code in (401, 403):
                break  # 키 문제는 재시도해도 소용없음
        except Exception as e:
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last_err)


def _api_articles(today, query, keep_title, keys):
    import html as _html
    from email.utils import parsedate_to_datetime
    articles, seen = [], set()
    for it in _fetch_naver_api(query, keys):
        title = _html.unescape(re.sub(r'<[^>]+>', '', it.get('title', ''))).strip()
        link = it.get('originallink') or it.get('link')
        if not link or link in seen or not keep_title(title):
            continue
        seen.add(link)
        try:
            dt = parsedate_to_datetime(it['pubDate']).replace(tzinfo=None)  # pubDate는 KST(+0900)
        except Exception:
            dt = None
        is_today = dt is not None and dt.date() == today.date()
        articles.append({
            'time': dt.strftime('%H:%M') if is_today else None,
            'date': dt.strftime('%Y-%m-%d') if dt else None,
            'datetime': dt.strftime('%Y-%m-%d %H:%M') if dt else None,
            'title': title,
            'press': _press_from_link(it.get('originallink') or link),
            'link': link,
        })
    return articles


def _search_naver_news(today, query, keep_title, lookback_days=0):
    """NAVER_CLIENT_ID/SECRET이 있으면 공식 API, 없으면(또는 API 실패 시) 검색 페이지 스크래핑."""
    keys = _naver_api_keys()
    if keys:
        try:
            return _filter_by_date(_api_articles(today, query, keep_title, keys), today, lookback_days)
        except Exception as e:
            print(f"[{query}] 네이버 API 실패 → 스크래핑으로 재시도: {e}")
    return _scrape_naver_news(today, query, keep_title, lookback_days)


def _scrape_naver_news(today, query, keep_title, lookback_days=0):
    """네이버 뉴스 검색(최신순) 결과에서 오늘자 기사의 시간/제목/언론사/링크를 모은다.
    (2026년 기준 네이버 뉴스 검색 결과는 SDS 컴포넌트 구조라 클래스명이 해시화되어 있어,
    data-heatmap-target / data-sds-comp 같은 안정적인 속성 기준으로 선택한다.)
    keep_title(title)이 False인 기사는 제외한다."""
    url = f"https://search.naver.com/search.naver?where=news&query={urllib.parse.quote(query)}&sort=1"  # sort=1: 최신순
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.text, 'html.parser')

        title_links = soup.select('a[data-heatmap-target=".tit"], a.news_tit')
        seen_links = set()
        for title_link in title_links:
            link = title_link.get('href')
            if not link or link in seen_links:
                continue

            title_span = title_link.select_one('span.sds-comps-text-type-headline1')
            title = title_span.get_text(strip=True) if title_span else title_link.get_text(strip=True)
            if not keep_title(title):
                continue
            seen_links.add(link)

            profile = title_link.find_previous('div', attrs={'data-sds-comp': 'Profile'})
            press = ''
            time_text = ''
            if profile:
                press_el = profile.select_one('.sds-comps-profile-info-title-text')
                if press_el:
                    press = press_el.get_text(strip=True).replace('새 창 열림', '').strip()
                subtext_el = profile.select_one('.sds-comps-profile-info-subtext')
                if subtext_el:
                    time_text = subtext_el.get_text(strip=True)

            dt = parse_article_datetime(time_text, today)
            articles.append({
                'time': parse_time_text(time_text, today),
                'date': dt.strftime('%Y-%m-%d') if dt else None,
                'datetime': dt.strftime('%Y-%m-%d %H:%M') if dt else None,
                'title': title,
                'press': press,
                'link': link,
            })
    except Exception as e:
        print(f"[{query}] 뉴스 검색 실패: {e}")

    return _filter_by_date(articles, today, lookback_days)


def _filter_by_date(articles, today, lookback_days):
    if lookback_days <= 0:
        articles = [a for a in articles if a['time']]
        articles.sort(key=lambda a: a['time'])
        return articles

    # 최근 lookback_days일 기사까지 포함(전날 장마감 후 나온 재료 등). 날짜를 모르는 기사는 제외.
    oldest = (today - datetime.timedelta(days=lookback_days)).date()
    kept = []
    for a in articles:
        if not a['date']:
            continue
        if datetime.date.fromisoformat(a['date']) < oldest:
            continue
        if not a['time']:
            a['time'] = a['date'][5:].replace('-', '/')  # 오늘이 아니면 화면에는 MM/DD로
        kept.append(a)
    kept.sort(key=lambda a: a['datetime'])
    return kept


def get_featured_news(stock_name, today):
    """'{종목명} 특징주' 검색 결과 중 종목명이나 급등 관련 단어가 들어간 오늘자 기사."""
    articles = _search_naver_news(
        today,
        f"{stock_name} 특징주",
        lambda title: stock_name in title or any(word in title for word in _RELEVANCE_WORDS),
    )
    return stock_name, articles


def name_variants(stock_name, min_len=5):
    """기사 제목에서 종목을 알아보기 위한 이름 후보.
    긴 이름은 줄여 쓰는 경우가 많아('나라스페이스테크놀로지' -> '나라스페이스')
    5글자 이상인 앞부분도 인정한다. 짧은 이름은 전체 이름만."""
    name = stock_name.strip()
    if len(name) <= min_len:
        return [name]
    return [name[:k] for k in range(len(name), min_len - 1, -1)]


def get_general_news(stock_name, today, limit=10, lookback_days=3):
    """'{종목명}'으로 검색해서, 제목에 종목명(또는 줄인 이름)이 들어간
    최근 lookback_days일 기사를 모은다(최신 limit건)."""
    variants = name_variants(stock_name)
    articles = _search_naver_news(
        today, stock_name, lambda title: any(v in title for v in variants), lookback_days=lookback_days
    )
    return articles[-limit:]


def main():
    # GitHub Actions 러너는 시스템 시각이 UTC라, 한국시간(KST=UTC+9) 기준으로 보정해서 사용
    today = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)
    target_date_str = os.environ.get('FEATURED_NEWS_TARGET_DATE') or today.strftime('%Y%m%d')

    stocks = get_today_stock_list(target_date_str)
    if not stocks:
        print(f"[{target_date_str}] 오늘 스캔에 잡힌 종목이 없어 건너뜁니다.")
        return

    themes_db = {}
    if os.path.exists(THEMES_PATH):
        with open(THEMES_PATH, 'r', encoding='utf-8') as f:
            themes_db = json.load(f)

    print(f"[FEATURED] 대상 종목: {len(stocks)}개")

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4 if _naver_api_keys() else 8) as ex:
        futures = {ex.submit(get_featured_news, name, today): code for code, name in stocks.items()}
        code_by_name = {v: k for k, v in stocks.items()}
        for fut in concurrent.futures.as_completed(futures):
            name, articles = fut.result()
            code = code_by_name.get(name)
            if not code or not articles:
                continue
            category = (themes_db.get(code) or {}).get('category', '기타')
            results[code] = {
                'name': name,
                'category': category,
                'articles': articles,
            }

    all_data = {}
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
        except Exception:
            all_data = {}

    all_data[target_date_str] = results

    # 최근 5일치만 보관
    sorted_dates = sorted(all_data.keys(), reverse=True)
    for d in sorted_dates[5:]:
        del all_data[d]

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False)

    print(f"[FEATURED] featured_stock_news.json 저장 완료: {len(results)}종목 (뉴스 있는 종목만)")


if __name__ == '__main__':
    main()
