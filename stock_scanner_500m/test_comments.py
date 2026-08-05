# -*- coding: utf-8 -*-
import sys
from ai_commentator import get_ai_commentary

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

dummy = {
    'code': '005930',
    'name': '삼성전자',
    'day_type': 1,
    'close': 85000,
    'rate': -1.2,
    'low': 84200,
    'vol_ratio': 45.2,
    'expected_ma': {
        'ma3': 85200.0, 'ma3_trend': '우하향',
        'ma5': 84800.0, 'ma5_trend': '우상향',
        'ma8': 84200.0, 'ma8_trend': '우상향',
        'ma20': 83500.0, 'ma20_trend': '우상향'
    },
    'former_peak': 88000,
    'ref_date': '2026-07-13'
}

# 에러 메시지가 표시되도록 get_ai_commentary 내부의 예외 처리를 디버깅할 수 있도록 구성
import traceback
import requests
import json
import os

def test_api():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "config.json")
    api_key = None
    with open(config_path, 'r', encoding='utf-8') as f:
        api_key = json.load(f).get('GEMINI_API_KEY')
        
    print("API Key loaded:", api_key[:10] + "...")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"parts": [{"text": "Hello, write a short greeting."}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 50}
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        print("Status Code:", response.status_code)
        print("Response Text:", response.text)
    except Exception as e:
        traceback.print_exc()

if __name__ == "__main__":
    test_api()
