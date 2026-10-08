# -*- coding: utf-8 -*-
import os
import json
import datetime
import time
import requests


def kst_now():
    """GitHub Actions 러너는 UTC라서, sync_and_push.py/fetch_featured_stock_news.py와
    같은 한국시간 기준 날짜를 쓰도록 보정한다(날짜 키가 어긋나지 않게)."""
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)


MAX_NEWS_FOR_AI = 15


def _normalize_featured(article, target_date_str):
    """featured_stock_news.json의 예전 기사(날짜 필드 없음)에 기준일 날짜를 채운다."""
    a = dict(article)
    day = f"{target_date_str[:4]}-{target_date_str[4:6]}-{target_date_str[6:]}"
    a.setdefault('date', day)
    if not a.get('datetime'):
        t = a.get('time') or ''
        a['datetime'] = f"{day} {t}" if len(t) == 5 and t[2] == ':' else day
    return a


def get_news_articles(code, name, system_dir, target_date_str):
    """AI 분석에 넘길 뉴스를 (기사목록, 출처)로 돌려준다.

    - 특징주 기사: fetch_featured_stock_news.py가 먼저 만들어둔 당일 특징주 기사 재사용
    - 일반 기사: '{종목명}'으로 검색한 최근 3일 기사(제목에 종목명 또는 줄인 이름 포함).
      전날 장마감 후 나온 재료나, 특징주로 다뤄지지 않은 종목도 잡기 위함.
    둘을 합쳐 링크 기준으로 중복을 없애고 시간순으로 최대 MAX_NEWS_FOR_AI건.
    출처는 'featured'(특징주 기사 있음) / 'general'(일반 기사만) / 'none'."""
    featured = []
    featured_path = os.path.join(system_dir, "featured_stock_news.json")
    if os.path.exists(featured_path):
        try:
            with open(featured_path, 'r', encoding='utf-8') as f:
                all_featured = json.load(f)
            info = all_featured.get(target_date_str, {}).get(code) or {}
            featured = [_normalize_featured(a, target_date_str) for a in info.get('articles', [])]
        except Exception as e:
            print(f"[{code}] featured_stock_news.json 조회 실패: {e}")

    general = []
    try:
        from fetch_featured_stock_news import get_general_news
        general = get_general_news(name, kst_now(), limit=MAX_NEWS_FOR_AI, lookback_days=3)
    except Exception as e:
        print(f"[{name}] 일반 뉴스 검색 실패: {e}")

    merged, seen = [], set()
    for a in featured + general:
        key = a.get('link') or a.get('title')
        if key in seen:
            continue
        seen.add(key)
        merged.append(a)
    merged.sort(key=lambda a: a.get('datetime') or '')
    merged = merged[-MAX_NEWS_FOR_AI:]

    source = 'featured' if featured else ('general' if merged else 'none')
    print(f"  - 뉴스: 특징주 {len(featured)}건 + 일반 {len(general)}건 -> {len(merged)}건 ({source})")
    return merged, source


def get_trading_value(code, target_date_str):
    """500억봉 스캐너와 같은 기준(종가×거래량)의 당일 거래대금을 로컬 시세 DB에서 읽는다."""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_ohlcv_cache.db")
    if not os.path.exists(db_path):
        return None
    day = f"{target_date_str[:4]}-{target_date_str[4:6]}-{target_date_str[6:]}"
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT close, volume FROM daily_prices WHERE code = ? AND date = ?;", (code, day)
        ).fetchone()
        conn.close()
        if row and row[0] and row[1]:
            return float(row[0]) * float(row[1])
    except Exception as e:
        print(f"[{code}] 거래대금 조회 실패: {e}")
    return None


# 사용자가 지정한 프롬프트 원문. {stock_name} 등은 build_prompt에서 채운다.
PROMPT_TEMPLATE = """너는 한국 주식시장의 "종목 재료 분석기"다.

목적은 스캐너에 잡힌 종목이 왜 상승했는지,
제공된 뉴스만 근거로 핵심 재료를 찾아 짧고 정확하게 정리하는 것이다.

[입력]
종목명: {stock_name}
종목코드: {stock_code}
기준일: {date}
당일 등락률: {change_rate}
당일 거래대금: {trading_value}

뉴스 목록:
{news_list}

[분석 원칙]

1. 가장 먼저 "왜 이 종목이 올랐는가?"를 판단한다.

2. 비슷한 기사 여러 개가 있어도 같은 사건이면 하나의 재료로 묶는다.
기사 개수가 아니라 EVENT 개수를 센다.

3. 제공된 뉴스에 없는 사실을 만들지 않는다.
확실하지 않으면 "확인불가" 또는 "추정"이라고 표시한다.

4. 종목명만 기사에 등장했다고 핵심 재료로 판단하지 않는다.
실제 주가 상승과 연결될 가능성이 높은 사건을 우선한다.

5. 재료는 중요도 순으로 최대 3개만 선정한다.

6. 각 재료를 다음 중 하나로 분류한다.

NEW
= 새롭게 발생한 사건

FOLLOW_UP
= 기존 재료에 새로운 사실이 추가됨

CONFIRMATION
= 계약, 공시, 정부발표 등 기존 기대가 공식 확인됨

RECYCLED
= 새로운 내용 없이 과거 내용을 다시 기사화함

NEGATIVE
= 주가에 부정적일 가능성이 있는 사건

7. 뉴스 게시일과 실제 사건 발생일이 다르면
가능한 경우 최초 사건 발생 시점을 기준으로 판단한다.

8. 기사에 언급된 관련주와
실제 사업관계가 확인되는 관련주는 구분한다.

9. 관련종목을 억지로 만들지 않는다.
제공된 뉴스로 연결 근거가 없으면 관련종목을 작성하지 않는다.

10. 장황한 설명은 하지 않는다.
매매자가 10초 안에 읽을 수 있도록 핵심만 작성한다.

[출력]

반드시 아래 JSON 형식으로만 출력한다.

{
  "stock": "{stock_name}",

  "main_material": {
    "title": "핵심 재료를 25자 이내로 요약",
    "reason": "왜 상승했는지 1~2문장",
    "event_type": "NEW | FOLLOW_UP | CONFIRMATION | RECYCLED | NEGATIVE",
    "theme": ["핵심테마1", "핵심테마2"],
    "origin_date": "YYYY-MM-DD 또는 확인불가"
  },

  "secondary_materials": [
    {
      "title": "보조 재료",
      "event_type": "NEW | FOLLOW_UP | CONFIRMATION | RECYCLED | NEGATIVE"
    }
  ],

  "related_stocks": [
    {
      "stock": "관련종목",
      "reason": "연결 근거를 한 문장으로",
      "relation": "DIRECT | BUSINESS | MARKET_THEME"
    }
  ],

  "evidence": [
    {
      "headline": "근거가 된 기사 제목",
      "date": "기사 날짜"
    }
  ],

  "summary": "이 종목이 왜 올랐는지 한 문장으로 최종 요약",

  "confidence": "HIGH | MEDIUM | LOW"
}

[중요]

- main_material은 반드시 하나만 선정한다.
- 핵심 재료를 찾지 못하면 title을 "뚜렷한 재료 확인불가"로 한다.
- 동일 사건의 반복기사를 서로 다른 재료로 처리하지 않는다.
- 관련주보다 해당 종목의 상승 이유 분석이 우선이다.
- 주가 상승 이후 나온 기사를 상승 원인으로 착각하지 않는다.
- 기준일 이후 뉴스는 기준일 상승 원인으로 사용하지 않는다.
- 출력 외의 설명은 절대 작성하지 않는다."""

EVENT_TYPES = {"NEW", "FOLLOW_UP", "CONFIRMATION", "RECYCLED", "NEGATIVE"}
CONFIDENCES = {"HIGH", "MEDIUM", "LOW"}


def build_prompt(name, code, target_date_str, rate, trading_value, articles):
    day = f"{target_date_str[:4]}-{target_date_str[4:6]}-{target_date_str[6:]}"
    tv = f"약 {trading_value / 100_000_000:,.0f}억원 (종가×거래량 기준)" if trading_value else "확인불가"
    news_lines = []
    for a in articles:
        when = a.get('datetime') or a.get('date') or '날짜 확인불가'
        press = f" ({a['press']})" if a.get('press') else ''
        line = f"- [{when}] {a['title']}{press}"
        if a.get('body'):
            line += f"\n  내용: {a['body']}"
        news_lines.append(line)
    values = {
        '{stock_name}': name,
        '{stock_code}': code,
        '{date}': day,
        '{change_rate}': f"{float(rate or 0):+.2f}%",
        '{trading_value}': tv,
        '{news_list}': "\n".join(news_lines),
    }
    prompt = PROMPT_TEMPLATE
    for k, v in values.items():
        prompt = prompt.replace(k, v)
    return prompt


def no_news_analysis(name):
    """뉴스가 전혀 없을 때(AI 호출 없이) 프롬프트 규칙대로 남기는 결과."""
    return {
        "stock": name,
        "main_material": {
            "title": "뚜렷한 재료 확인불가",
            "reason": "기준일 전후로 이 종목 관련 뉴스를 찾지 못했습니다.",
            "event_type": None,
            "theme": [],
            "origin_date": "확인불가",
        },
        "secondary_materials": [],
        "related_stocks": [],
        "evidence": [],
        "summary": "관련 뉴스를 찾지 못해 상승 재료를 확인할 수 없습니다.",
        "confidence": "LOW",
    }


def parse_analysis(text):
    """모델 응답(JSON)을 검증해서 dict로. 형식이 맞지 않으면 None."""
    t = (text or '').strip()
    if t.startswith('```'):
        t = t.strip('`')
        t = t[t.find('{'):] if '{' in t else t
    if '{' in t and '}' in t:
        t = t[t.find('{'):t.rfind('}') + 1]
    try:
        data = json.loads(t)
    except Exception:
        return None
    main = data.get('main_material')
    if not isinstance(main, dict) or not isinstance(data.get('summary'), str) or not main.get('title'):
        return None
    if main.get('event_type') not in EVENT_TYPES:
        main['event_type'] = None
    if not isinstance(main.get('theme'), list):
        main['theme'] = []
    for key in ('secondary_materials', 'related_stocks', 'evidence'):
        if not isinstance(data.get(key), list):
            data[key] = []
    data['secondary_materials'] = [m for m in data['secondary_materials'] if isinstance(m, dict) and m.get('title')][:2]
    data['related_stocks'] = [r for r in data['related_stocks'] if isinstance(r, dict) and r.get('stock')]
    if data.get('confidence') not in CONFIDENCES:
        data['confidence'] = None
    return data


def analyze_with_gemini(name, code, target_date_str, rate, trading_value, articles, api_key):
    """(analysis dict, 한 줄 요약)을 돌려준다."""
    if not articles:
        analysis = no_news_analysis(name)
        return analysis, analysis['summary']
    if not api_key:
        return None, "AI 요약 생성에 실패했습니다. (API 키 없음)"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": build_prompt(name, code, target_date_str, rate, trading_value, articles)}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500, "responseMimeType": "application/json"},
    }
    for attempt in range(2):  # 형식이 깨진 응답이면 한 번 더 시도
        try:
            response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=30)
            response.raise_for_status()
            text = response.json()['candidates'][0]['content']['parts'][0]['text']
            analysis = parse_analysis(text)
            if analysis:
                return analysis, analysis['summary'].strip()
            print(f"[{name}] AI 응답 형식 오류 (시도 {attempt + 1}/2)")
        except Exception as e:
            print(f"[{name}] Gemini 분석 실패 (시도 {attempt + 1}/2): {e}")
    return None, "AI 요약 생성에 실패했습니다."


INFOSTOCK_PRESS = '인포스탁 증시요약'


def backfill_with_infostock(all_issues, api_key, today_str):
    """인포스탁 증시요약은 무료로는 전일자부터 볼 수 있어, 지난 거래일 500억봉 종목의
    AI 요약을 다음 날 보강한다. 날짜별로 한 번만 조회하고(infostock_checked),
    사유가 있는 종목만 그 사유를 근거에 더해 다시 분석한다. 바뀐 날짜 목록을 돌려준다."""
    try:
        from fetch_infostock_reasons import fetch_reasons, SOURCE_PAGE
    except Exception as e:
        print(f"[INFOSTOCK] 모듈 로드 실패: {e}")
        return []
    changed = []
    for date_str in sorted(all_issues):
        issues = all_issues[date_str]
        if date_str >= today_str or not issues or all(i.get('infostock_checked') for i in issues):
            continue
        try:
            reasons = fetch_reasons(date_str, {i['name']: i['code'] for i in issues})
        except Exception as e:
            print(f"[INFOSTOCK] {date_str} 조회 실패(다음 실행 때 재시도): {e}")
            continue
        day = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        hit = 0
        for issue in issues:
            issue['infostock_checked'] = True
            info = reasons.get(issue['code'])
            if not info:
                continue
            hit += 1
            note = {
                'time': '장마감', 'date': day, 'datetime': f"{day} 17:00",
                'title': info['reason'], 'press': INFOSTOCK_PRESS, 'link': SOURCE_PAGE,
            }
            articles = [a for a in issue.get('articles') or [] if a.get('press') != INFOSTOCK_PRESS]
            for_ai = articles + [dict(note, body=info.get('detail', ''))]  # 상세 원문은 AI 입력에만
            time.sleep(4)  # 무료 Gemini 분당 호출 한도 대비(몰아서 부르면 실패함)
            analysis, summary = analyze_with_gemini(
                issue['name'], issue['code'], date_str, issue.get('rate', 0.0),
                issue.get('trading_value'), for_ai, api_key,
            )
            if analysis is None:
                issue['infostock_checked'] = False  # AI 실패 시 다음 실행 때 다시
                continue
            issue['articles'] = articles + [note]
            issue['headlines'] = [a['title'] for a in issue['articles']]
            issue['analysis'], issue['summary'] = analysis, summary
            if issue.get('news_source') in (None, 'none'):
                issue['news_source'] = 'infostock'
        print(f"[INFOSTOCK] {date_str}: 사유 {len(reasons)}종목 중 500억봉 {hit}종목 보강")
        changed.append(date_str)
    return changed


def update_archive(archive, issues, date_str, max_entries=200):
    for issue in issues:
        code = issue["code"]
        # 같은 날짜 재실행 시 중복 저장되지 않도록 그날 항목은 교체
        entries = [e for e in archive.get(code, []) if e.get("date") != date_str]
        main = (issue.get("analysis") or {}).get("main_material") or {}
        entries.append({
            "date": date_str,
            "name": issue["name"],
            "rate": issue["rate"],
            "summary": issue["summary"],
            "title": main.get("title"),
            "event_type": main.get("event_type"),
            "confidence": (issue.get("analysis") or {}).get("confidence"),
            "themes": main.get("theme") or [],
            "trading_value": issue.get("trading_value"),
        })
        entries.sort(key=lambda e: e["date"])
        archive[code] = entries[-max_entries:]


def generate_daily_issues(target_date_str):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    system_dir = os.path.dirname(current_dir)
    
    config_path = os.path.join(current_dir, "config.json")
    api_key = None
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            api_key = json.load(f).get('GEMINI_API_KEY')
    if not api_key:
        api_key = os.environ.get('GEMINI_API_KEY')
        
    scan_file = os.path.join(system_dir, "scan_history.json")
    if not os.path.exists(scan_file):
        print(f"스캔 이력 파일 없음: {scan_file}")
        return

    with open(scan_file, 'r', encoding='utf-8') as f:
        scan_data = json.load(f)
        
    daily_data = scan_data.get(target_date_str, {})
    b500m_list = daily_data.get('b500m', [])
    
    # 0일차(당일 기준봉) 종목만 필터링
    day0_stocks = [s for s in b500m_list if s.get('elapsed_days', -1) == 0]
    
    print(f"[{target_date_str}] 당일 500억/150억봉 종목 수: {len(day0_stocks)}개")
    
    issues = []
    for stock in day0_stocks:
        name = stock['name']
        code = stock['code']
        print(f"'{name}' 뉴스 검색 및 요약 중...")
        articles, source = get_news_articles(code, name, system_dir, target_date_str)
        trading_value = get_trading_value(code, target_date_str)
        analysis, summary = analyze_with_gemini(
            name, code, target_date_str, stock.get('rate', 0.0), trading_value, articles, api_key
        )

        issues.append({
            "code": code,
            "name": name,
            "rate": stock.get('rate', 0.0),
            "trading_value": trading_value,
            "summary": summary,
            "analysis": analysis,
            "headlines": [a['title'] for a in articles],
            "articles": articles,
            "news_source": source,
        })
        
    # daily_issues.json 에 저장 (누적 또는 덮어쓰기) - 최근 5영업일만 보관하는 롤링 캐시
    issues_file = os.path.join(system_dir, "daily_issues.json")
    all_issues = {}
    if os.path.exists(issues_file):
        with open(issues_file, 'r', encoding='utf-8') as f:
            try:
                all_issues = json.load(f)
            except:
                pass
                
    all_issues[target_date_str] = issues
    backfilled = backfill_with_infostock(all_issues, api_key, kst_now().strftime("%Y%m%d"))
    
    # 5일치만 보관
    sorted_dates = sorted(all_issues.keys(), reverse=True)
    if len(sorted_dates) > 5:
        for d in sorted_dates[5:]:
            del all_issues[d]
            
    with open(issues_file, 'w', encoding='utf-8') as f:
        json.dump(all_issues, f, ensure_ascii=False, indent=2)

    # ai_summary_archive.json: 종목코드별로 AI 요약을 영구 보관(5일 롤링과 무관).
    # 종목 상세 모달의 "AI 요약 이력" 섹션에서 이 파일을 그대로 사용한다.
    archive_file = os.path.join(system_dir, "ai_summary_archive.json")
    archive = {}
    if os.path.exists(archive_file):
        with open(archive_file, 'r', encoding='utf-8') as f:
            try:
                archive = json.load(f)
            except Exception:
                archive = {}

    update_archive(archive, issues, target_date_str)
    for d in backfilled:
        if d in all_issues:
            update_archive(archive, all_issues[d], d)

    with open(archive_file, 'w', encoding='utf-8') as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)

    # 영구 보관소(event_archive/, archive 브랜치)에 분석 전문까지 반영 — 5일 롤링과 무관
    try:
        from event_archive import record
        record(all_issues, archive)
    except Exception as e:
        print(f"[이벤트보관] 실패: {e}")

    print(f"[{target_date_str}] 주요 이슈 요약 완료 및 저장. (영구 아카이브 {len(issues)}건 반영)")

if __name__ == "__main__":
    today = kst_now().strftime("%Y%m%d")
    generate_daily_issues(today)
