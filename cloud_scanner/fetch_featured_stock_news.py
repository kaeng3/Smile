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
    """오늘(target_date_str) 양음양/v2/포도시/500억봉에 잡힌 종목을 code 기준으로 합친다."""
    if not os.path.exists(SCAN_HISTORY_PATH):
        return {}
    with open(SCAN_HISTORY_PATH, 'r', encoding='utf-8') as f:
        scan_data = json.load(f)
    day = scan_data.get(target_date_str, {})
    stocks = {}
    for key in ('yey', 'v2', 'podosi', 'b500m'):
        for s in day.get(key, []):
            code = s.get('code')
            if code and code not in stocks:
                stocks[code] = s.get('name')
    return stocks


def parse_time_text(time_text, today):
    """네이버 뉴스 검색결과의 상대/절대 시간 표기를 오늘 날짜의 HH:MM로 최대한 변환.
    예) '3시간 전' '52분 전' '2026.08.10.' 등"""
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
    return time_text  # 그 외(날짜 등)는 원문 그대로


def get_featured_news(stock_name, today):
    """'{종목명} 특징주' 네이버 뉴스 검색 결과에서 시간/제목/언론사/링크를 모은다."""
    query = urllib.parse.quote(f"{stock_name} 특징주")
    url = f"https://search.naver.com/search.naver?where=news&query={query}&sort=1"  # sort=1: 최신순
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('div.news_wrap, li.bx')
        seen_links = set()
        for item in items[:20]:
            title_tag = item.select_one('a.news_tit')
            if not title_tag:
                continue
            title = title_tag.get('title') or title_tag.get_text(strip=True)
            link = title_tag.get('href')
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            press_tag = item.select_one('a.info.press, .press')
            press = press_tag.get_text(strip=True) if press_tag else ''

            time_tag = item.select_one('span.info')
            time_text = time_tag.get_text(strip=True) if time_tag else ''
            time_display = parse_time_text(time_text, today)

            if '특징주' not in title:
                continue

            articles.append({
                'time': time_display,
                'title': title,
                'press': press,
                'link': link,
            })
    except Exception as e:
        print(f"[{stock_name}] 특징주 뉴스 검색 실패: {e}")

    articles.sort(key=lambda a: a['time'])
    return stock_name, articles


def main():
    today = datetime.datetime.now()
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
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
