# -*- coding: utf-8 -*-
import os
import sys
import json
import datetime
import socket
socket.setdefaulttimeout(3.0)

try:
    import FinanceDataReader as fdr
except ImportError:
    pass

WATCHLIST_PATH = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\scratch\yangeumyang_watchlist.json"

def load_watchlist():
    if os.path.exists(WATCHLIST_PATH):
        try:
            with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_watchlist(watchlist):
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(watchlist, f, ensure_ascii=False, indent=2)

def register_anchor_stocks(stocks_list, signal_date):
    """기준봉 발생 종목 및 시그널 종목을 DB에 등록"""
    watchlist = load_watchlist()
    date_str = signal_date.strftime('%Y-%m-%d')
    
    added_count = 0
    for s in stocks_list:
        code = s['code']
        if code not in watchlist:
            watchlist[code] = {
                'code': code,
                'name': s.get('name', ''),
                'anchor_date': date_str,
                'anchor_close': s.get('close', 0),
                'pattern': s.get('pattern', ''),
                'status': 'tracking',
                'registered_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            added_count += 1
            
    save_watchlist(watchlist)
    print(f"[Watchlist DB] 신규 {added_count}개 종목 추적 DB에 등록 완료. (총 {len(watchlist)}개 관리 중)")
    return watchlist

def scan_tracked_pullbacks(target_date, stock_dfs=None):
    """
    로컬 DB 캐시(stock_dfs) 기반 초고속 0.01초 추적 스캔
    DB에 등록된 종목들을 대상으로 오늘(target_date) 우상향하는 5/10/15/20선 지지 타점 검증
    """
    watchlist = load_watchlist()
    if not watchlist:
        return []
        
    print(f"[{target_date.strftime('%Y-%m-%d')}] 과거 DB 등록 종목({len(watchlist)}개) 이평선(5/10/15/20선) 초고속 추적 스캔 시작...")
    
    matched_signals = []
    
    for code, info in watchlist.items():
        try:
            anchor_dt = datetime.datetime.strptime(info['anchor_date'], '%Y-%m-%d')
            days_diff = (target_date - anchor_dt).days
            if days_diff <= 0 or days_diff > 35:
                continue
                
            df = stock_dfs.get(code) if stock_dfs else None
            if df is None or len(df) < 25:
                continue
                
            # 이평선 연산
            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA10'] = df['Close'].rolling(10).mean()
            df['MA15'] = df['Close'].rolling(15).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            
            close_curr = df['Close'].iloc[-1]
            low_curr = df['Low'].iloc[-1]
            
            ma5 = df['MA5'].iloc[-1]
            ma10 = df['MA10'].iloc[-1]
            ma15 = df['MA15'].iloc[-1]
            ma20 = df['MA20'].iloc[-1]
            
            ma5_up = ma5 > df['MA5'].iloc[-2]
            ma10_up = ma10 > df['MA10'].iloc[-2]
            ma15_up = ma15 > df['MA15'].iloc[-2]
            ma20_up = ma20 > df['MA20'].iloc[-2]
            
            touched_ma = None
            if ma5_up and (ma5 * 0.975 <= close_curr <= ma5 * 1.03 or low_curr <= ma5 * 1.01 <= close_curr):
                touched_ma = "우상향 5일선"
            elif ma10_up and (ma10 * 0.975 <= close_curr <= ma10 * 1.03 or low_curr <= ma10 * 1.01 <= close_curr):
                touched_ma = "우상향 10일선"
            elif ma15_up and (ma15 * 0.975 <= close_curr <= ma15 * 1.03 or low_curr <= ma15 * 1.01 <= close_curr):
                touched_ma = "우상향 15일선"
            elif ma20_up and (ma20 * 0.975 <= close_curr <= ma20 * 1.03 or low_curr <= ma20 * 1.01 <= close_curr):
                touched_ma = "우상향 20일선"
                
            if touched_ma:
                c_prev = df['Close'].iloc[-2]
                rate = ((close_curr - c_prev) / c_prev) * 100
                elapsed_days = len(df.loc[anchor_dt:target_date]) - 1 if anchor_dt in df.index else days_diff
                
                matched_signals.append({
                    'code': code,
                    'name': info['name'],
                    'close': int(close_curr),
                    'rate': float(rate),
                    'match_type': 'predictive',
                    'pattern': f"[추적관리] 기준봉 D+{elapsed_days}일 ({touched_ma} 지지 매수 타점)",
                    'touched_ma': touched_ma,
                    'anchor_date': info['anchor_date']
                })
        except Exception:
            pass
            
    print(f"[{target_date.strftime('%Y-%m-%d')}] 추적 DB 스캔 완료: 총 {len(matched_signals)}개 이평선 눌림목 타점 포착!")
    return matched_signals
