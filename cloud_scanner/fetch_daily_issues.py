# -*- coding: utf-8 -*-
import os
import json
import datetime
import requests


def get_news_headlines(code, system_dir, target_date_str):
    """fetch_featured_stock_news.py가 이미 만들어둔 featured_stock_news.json에서
    이 종목의 오늘자 특징주 기사 제목만 뽑는다.

    예전엔 여기서 get_featured_news()를 별도로 한 번 더 호출했는데, 이 스크립트가
    fetch_featured_stock_news.py보다 먼저 실행되다 보니 같은 '{종목명} 특징주' 검색을
    몇 분 간격으로 두 번 하는 꼴이었다. 그 사이에 실제 기사가 막 올라오면
    먼저 도는 쪽(여기)만 0건으로 잡히는 경우가 있었다(예: 2026-10-01 윈팩).
    이제 fetch_featured_stock_news.py를 먼저 돌리고 그 결과를 그대로 재사용해서
    같은 검색을 두 번 하지 않고, 결과도 완전히 일치하게 만든다."""
    featured_path = os.path.join(system_dir, "featured_stock_news.json")
    debug_lines = []
    debug_lines.append(f"[DEBUG] featured_path={featured_path} exists={os.path.exists(featured_path)}")
    if os.path.exists(featured_path):
        debug_lines.append(f"[DEBUG] mtime={os.path.getmtime(featured_path)} size={os.path.getsize(featured_path)}")
    try:
        with open(os.path.join(system_dir, "debug_news_lookup.log"), 'a', encoding='utf-8') as dbg:
            dbg.write("\n".join(debug_lines) + "\n")
    except Exception:
        pass
    if not os.path.exists(featured_path):
        return []
    try:
        with open(featured_path, 'r', encoding='utf-8') as f:
            all_featured = json.load(f)
        day = all_featured.get(target_date_str, {})
        with open(os.path.join(system_dir, "debug_news_lookup.log"), 'a', encoding='utf-8') as dbg:
            dbg.write(f"[DEBUG] code={code} target_date_str={target_date_str} day_keys_count={len(day)} code_in_day={code in day}\n")
        info = day.get(code)
        if not info:
            return []
        return [a['title'] for a in info.get('articles', [])[:10]]
    except Exception as e:
        print(f"[{code}] featured_stock_news.json 조회 실패: {e}")
        return []

def summarize_issue_with_gemini(stock_name, headlines, api_key):
    if not headlines:
        return "관련 특징주 뉴스가 없습니다."
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    
    news_text = "\n".join([f"- {h}" for h in headlines])
    prompt = f"""당신은 주식 시황 분석가입니다.
종목명: {stock_name}
오늘 검색된 특징주 뉴스 헤드라인입니다:
{news_text}

위 뉴스들을 바탕으로, 오늘 이 종목에 대량의 거래대금(500억 이상)이 몰리며 급등한 핵심 이유(이슈/테마)를 1~2줄의 깔끔한 문장으로 요약해 주세요.
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
        headlines = get_news_headlines(code, system_dir, target_date_str)
        summary = summarize_issue_with_gemini(name, headlines, api_key)
        
        issues.append({
            "code": code,
            "name": name,
            "rate": stock.get('rate', 0.0),
            "summary": summary,
            "headlines": headlines
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
    today = datetime.datetime.now().strftime("%Y%m%d")
    generate_daily_issues(today)
