# -*- coding: utf-8 -*-
import os
import json
import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
import requests
import datetime

def get_news_headlines(stock_name):
    query = urllib.parse.quote(f"{stock_name} 특징주")
    url = f"https://search.naver.com/search.naver?where=news&query={query}"
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    
    try:
        html = urllib.request.urlopen(req, timeout=5).read()
        soup = BeautifulSoup(html, 'html.parser')
        
        articles = soup.find_all('a', class_='news_tit')
        headlines = []
        for a in articles[:5]:
            headlines.append(a.get('title'))
        return headlines
    except Exception as e:
        print(f"[{stock_name}] 뉴스 검색 실패: {e}")
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
        headlines = get_news_headlines(name)
        summary = summarize_issue_with_gemini(name, headlines, api_key)
        
        issues.append({
            "code": code,
            "name": name,
            "rate": stock.get('rate', 0.0),
            "summary": summary,
            "headlines": headlines
        })
        
    # daily_issues.json 에 저장 (누적 또는 덮어쓰기)
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
        
    print(f"[{target_date_str}] 주요 이슈 요약 완료 및 저장.")

if __name__ == "__main__":
    today = datetime.datetime.now().strftime("%Y%m%d")
    generate_daily_issues(today)
