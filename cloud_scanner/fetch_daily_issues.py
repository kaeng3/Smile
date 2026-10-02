# -*- coding: utf-8 -*-
import os
import json
import datetime
import requests


def kst_now():
    """GitHub Actions 러너는 UTC라서, sync_and_push.py/fetch_featured_stock_news.py와
    같은 한국시간 기준 날짜를 쓰도록 보정한다(날짜 키가 어긋나지 않게)."""
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)


def get_news_articles(code, name, system_dir, target_date_str):
    """이 종목의 오늘자 뉴스를 (기사목록, 출처)로 돌려준다.

    1순위: fetch_featured_stock_news.py가 먼저 만들어둔 featured_stock_news.json의
           특징주 기사를 재사용 (같은 검색을 두 번 하지 않기 위해).
    2순위: 특징주 기사가 하나도 없으면 '{종목명}'으로 일반 뉴스를 검색해서
           제목에 종목명이 들어간 오늘자 기사를 쓴다. 언론에 '특징주'로 다뤄지지
           않은 종목도 요약이 비지 않도록 하기 위함.
    출처는 'featured' / 'general' / 'none'."""
    featured_path = os.path.join(system_dir, "featured_stock_news.json")
    if os.path.exists(featured_path):
        try:
            with open(featured_path, 'r', encoding='utf-8') as f:
                all_featured = json.load(f)
            info = all_featured.get(target_date_str, {}).get(code)
            if info and info.get('articles'):
                return info['articles'][:10], 'featured'
        except Exception as e:
            print(f"[{code}] featured_stock_news.json 조회 실패: {e}")

    try:
        from fetch_featured_stock_news import get_general_news
        articles = get_general_news(name, kst_now())
        if articles:
            return articles, 'general'
    except Exception as e:
        print(f"[{name}] 일반 뉴스 검색 실패: {e}")

    return [], 'none'


def summarize_issue_with_gemini(stock_name, articles, source, api_key):
    if not articles:
        return "오늘 관련 뉴스를 찾지 못했습니다."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}

    news_text = "\n".join([f"- {a['title']}" for a in articles])
    if source == 'featured':
        intro = "오늘 검색된 특징주 뉴스 헤드라인입니다:"
        caution = ""
    else:
        intro = "오늘 이 종목명으로 검색된 일반 뉴스 헤드라인입니다(특징주 기사는 없었음):"
        caution = "\n헤드라인이 오늘 급등과 직접 관련이 없어 보이면, 추측하지 말고 '뚜렷한 급등 재료가 보도되지 않았다'는 취지로 짧게 정리하세요."
    prompt = f"""당신은 주식 시황 분석가입니다.
종목명: {stock_name}
{intro}
{news_text}

위 뉴스들을 바탕으로, 오늘 이 종목에 대량의 거래대금(500억 이상)이 몰리며 급등한 핵심 이유(이슈/테마)를 1~2줄의 깔끔한 문장으로 요약해 주세요.{caution}
인사말 없이 바로 요약 내용만 작성하세요."""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 200}
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        res_json = response.json()
        summary = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
        return summary
    except Exception as e:
        print(f"[{stock_name}] Gemini 요약 실패: {e}")
        return "AI 요약 생성에 실패했습니다."


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
        summary = summarize_issue_with_gemini(name, articles, source, api_key)

        issues.append({
            "code": code,
            "name": name,
            "rate": stock.get('rate', 0.0),
            "summary": summary,
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

    MAX_ENTRIES_PER_STOCK = 200
    for issue in issues:
        code = issue["code"]
        entries = archive.get(code, [])
        # 같은 날짜 재실행 시 중복 저장되지 않도록 그날 항목은 교체
        entries = [e for e in entries if e.get("date") != target_date_str]
        entries.append({
            "date": target_date_str,
            "name": issue["name"],
            "rate": issue["rate"],
            "summary": issue["summary"],
        })
        entries.sort(key=lambda e: e["date"])
        archive[code] = entries[-MAX_ENTRIES_PER_STOCK:]

    with open(archive_file, 'w', encoding='utf-8') as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)

    print(f"[{target_date_str}] 주요 이슈 요약 완료 및 저장. (영구 아카이브 {len(issues)}건 반영)")

if __name__ == "__main__":
    today = kst_now().strftime("%Y%m%d")
    generate_daily_issues(today)
