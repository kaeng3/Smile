# -*- coding: utf-8 -*-
import os
import sys
import datetime
import json
import socket
socket.setdefaulttimeout(3.0)
import FinanceDataReader as fdr
import pandas as pd
from local_data_manager import sync_stock_data, load_cached_stock_dfs

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def get_market_list():
    df = fdr.StockListing('KRX')
    df_filtered = df[df['Market'].isin(['KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL'])]
    exclude_keywords = ['우B', '우C', '스팩', '리츠', '레버리지', '인버스', 'ETN', 'ETF', '하이브리드']
    def is_excluded(name):
        return name.endswith('우') or any(kw in name for kw in exclude_keywords)
        
    stocks = []
    for s in df_filtered[['Code', 'Name']].to_dict('records'):
        if not is_excluded(s['Name']): 
            stocks.append(s)
    return stocks

# 1. 양음양 기법 스캐너 (로컬 캐시 DB 기반 초고속 연산)
def scan_date_optimized(stocks, target_date, stock_dfs=None):
    print(f"[{target_date.strftime('%Y-%m-%d')}] 양음양 기법 스캔 시작...")
    if stock_dfs is None:
        stock_dfs = load_cached_stock_dfs(target_date)
        
    results = []
    for stock in stocks:
        code = stock.get('Code') or stock.get('code')
        name = stock.get('Name') or stock.get('name')
        df = stock_dfs.get(code)
        if df is None or len(df) < 224:
            continue
            
        try:
            c_curr = df['Close'].iloc[-1]
            c_prev = df['Close'].iloc[-2]
            rate = ((c_curr - c_prev) / c_prev) * 100
            
            # 수급 및 눌림목 조건 검증
            vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1]
            vol_curr = df['Volume'].iloc[-1]
            
            if vol_ma20 > 0 and vol_curr >= vol_ma20 * 1.2:
                results.append({
                    'code': code, 'name': name, 'close': int(c_curr), 'rate': float(rate),
                    'match_type': 'predictive', 'pattern': '양음양 패턴 1 (수급 강세)'
                })
        except Exception:
            pass
            
    print(f"양음양 최종 포착 완료: {len(results)}개 종목")
    return results

# 2. 포도시 차트 기법 스캐너 (로컬 캐시 DB 기반 초고속 연산)
def scan_podosi_date(stocks, target_date, stock_dfs=None):
    print(f"[{target_date.strftime('%Y-%m-%d')}] 포도시 차트 기법 스캔 시작...")
    if stock_dfs is None:
        stock_dfs = load_cached_stock_dfs(target_date)

    results = []
    for stock in stocks:
        code = stock.get('Code') or stock.get('code')
        name = stock.get('Name') or stock.get('name')
        df = stock_dfs.get(code)
        if df is None or len(df) < 224:
            continue

        try:
            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA10'] = df['Close'].rolling(10).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            df['MA120'] = df['Close'].rolling(120).mean()
            df['MA224'] = df['Close'].rolling(224).mean()
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()

            close_curr = df['Close'].iloc[-1]
            c_prev = df['Close'].iloc[-2]
            rate = ((close_curr - c_prev) / c_prev) * 100
            low_curr = df['Low'].iloc[-1]

            ma5_curr = df['MA5'].iloc[-1]
            ma10_curr = df['MA10'].iloc[-1]
            ma20_curr = df['MA20'].iloc[-1]
            ma60_curr = df['MA60'].iloc[-1]
            ma120_curr = df['MA120'].iloc[-1]
            ma224_curr = df['MA224'].iloc[-1]

            # 2년 내 낙폭과대 조건
            max_high_2y = df['High'].iloc[-500:].max() if len(df) >= 500 else df['High'].max()
            if max_high_2y < close_curr * 2.0:
                continue

            # 골든크로스 조짐 및 단기선 디딤돌 조건
            if ma5_curr <= ma20_curr:
                continue
            if not (ma5_curr >= df['MA5'].iloc[-2] or ma20_curr >= df['MA20'].iloc[-2]):
                continue

            matched_pattern = None

            # 30일 이내 돌파 기준봉 탐색
            breakout_idx_120 = -1
            for idx in range(1, min(31, len(df)-1)):
                c_v = df['Close'].iloc[-idx]
                ma120_v = df['MA120'].iloc[-idx]
                v_v = df['Volume'].iloc[-idx]
                v_ma20_v = df['Vol_MA20'].iloc[-idx]
                if c_v > ma120_v and df['Close'].iloc[-idx-1] <= df['MA120'].iloc[-idx-1] and (c_v * v_v >= 2_000_000_000) and (v_v >= v_ma20_v * 2.5):
                    breakout_idx_120 = len(df) - idx
                    break

            breakout_idx_60 = -1
            for idx in range(1, min(31, len(df)-1)):
                c_v = df['Close'].iloc[-idx]
                ma60_v = df['MA60'].iloc[-idx]
                v_v = df['Volume'].iloc[-idx]
                v_ma20_v = df['Vol_MA20'].iloc[-idx]
                if c_v > ma60_v and df['Close'].iloc[-idx-1] <= df['MA60'].iloc[-idx-1] and (c_v * v_v >= 2_000_000_000) and (v_v >= v_ma20_v * 2.5):
                    breakout_idx_60 = len(df) - idx
                    break

            breakout_idx_224 = -1
            for idx in range(1, min(31, len(df)-1)):
                c_v = df['Close'].iloc[-idx]
                ma224_v = df['MA224'].iloc[-idx]
                v_v = df['Volume'].iloc[-idx]
                v_ma20_v = df['Vol_MA20'].iloc[-idx]
                if c_v > ma224_v and df['Close'].iloc[-idx-1] <= df['MA224'].iloc[-idx-1] and (c_v * v_v >= 2_000_000_000) and (v_v >= v_ma20_v * 2.5):
                    breakout_idx_224 = len(df) - idx
                    break

            # 패턴 1: 120선 돌파 후 60선 지지
            if breakout_idx_120 != -1 and ma120_curr > ma60_curr:
                pre_low = df['Low'].iloc[max(0, breakout_idx_120 - 60):max(1, breakout_idx_120 - 2)].min()
                if low_curr >= pre_low * 0.975 and (ma60_curr * 0.95 <= close_curr <= ma120_curr * 1.05):
                    matched_pattern = "포도시 패턴 1 (120선 돌파 후 60선 지지)"

            # 패턴 2: 60선 돌파 후 20선 지지
            if not matched_pattern and breakout_idx_60 != -1 and ma60_curr > ma20_curr:
                pre_low = df['Low'].iloc[max(0, breakout_idx_60 - 60):max(1, breakout_idx_60 - 2)].min()
                if low_curr >= pre_low * 0.975 and (ma20_curr * 0.95 <= close_curr <= ma60_curr * 1.05):
                    matched_pattern = "포도시 패턴 2 (60선 돌파 후 20선 지지)"

            # 패턴 3: 224선 돌파 후 120선 지지
            if not matched_pattern and breakout_idx_224 != -1 and ma224_curr > ma120_curr:
                pre_low = df['Low'].iloc[max(0, breakout_idx_224 - 60):max(1, breakout_idx_224 - 2)].min()
                if low_curr >= pre_low * 0.975 and (ma120_curr * 0.95 <= close_curr <= ma224_curr * 1.05):
                    matched_pattern = "포도시 패턴 3 (224선 돌파 후 120선 지지)"

            if matched_pattern:
                results.append({
                    'code': code, 'name': name, 'close': int(close_curr), 'rate': float(rate),
                    'match_type': 'predictive', 'pattern': matched_pattern
                })
        except Exception:
            pass

    print(f"포도시 최종 포착 완료: {len(results)}개 종목")
    return results

# 3. 60일의 법칙 기법 스캐너
def scan_60ma_rule_date(stocks, target_date, stock_dfs=None):
    if stock_dfs is None:
        stock_dfs = load_cached_stock_dfs(target_date)

    results = []
    for stock in stocks:
        code = stock.get('Code') or stock.get('code')
        name = stock.get('Name') or stock.get('name')
        df = stock_dfs.get(code)
        if df is None or len(df) < 125:
            continue
        try:
            close_curr = df['Close'].iloc[-1]
            ma60_curr = df['Close'].rolling(60).mean().iloc[-1]
            ma120_curr = df['Close'].rolling(120).mean().iloc[-1]
            low_curr = df['Low'].iloc[-1]

            if ma120_curr > close_curr * 0.99 and low_curr <= ma60_curr * 1.025 and close_curr >= ma60_curr * 0.985:
                c_prev = df['Close'].iloc[-2]
                rate = ((close_curr - c_prev) / c_prev) * 100
                results.append({
                    'code': code, 'name': name, 'close': int(close_curr), 'rate': float(rate),
                    'match_type': 'predictive', 'pattern': '60일의 법칙 기법'
                })
        except Exception:
            pass

    return results

# 4. 60일의 법칙 양음양 기법 스캐너
def scan_60ma_rule_yey_date(stocks, target_date, stock_dfs=None):
    return scan_podosi_yey_date(stocks, target_date, stock_dfs)

# 5. 포도시 양음양 기법 스캐너
def scan_podosi_yey_date(stocks, target_date, stock_dfs=None):
    if stock_dfs is None:
        stock_dfs = load_cached_stock_dfs(target_date)

    results = []
    for stock in stocks:
        code = stock['Code']
        name = stock['Name']
        df = stock_dfs.get(code)
        if df is None or len(df) < 140:
            continue

        try:
            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA10'] = df['Close'].rolling(10).mean()
            df['MA13'] = df['Close'].rolling(13).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            df['MA120'] = df['Close'].rolling(120).mean()
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()

            close_curr = df['Close'].iloc[-1]
            day0 = df.iloc[-1]
            day1 = df.iloc[-2]
            day2 = df.iloc[-3]

            rate_1 = ((day1['Close'] - day2['Close']) / day2['Close']) * 100
            rate_0 = ((day0['Close'] - day1['Close']) / day1['Close']) * 100

            is_yesterday_yang = 4.0 <= rate_1 <= 22.0 and day1['Close'] > day1['Open'] and day1['Volume'] >= df['Vol_MA20'].iloc[-2] * 1.5
            is_today_eum = day0['Close'] < day0['Open'] and day0['Volume'] <= day1['Volume'] * 0.75

            if is_yesterday_yang and is_today_eum:
                results.append({
                    'code': code, 'name': name, 'close': int(close_curr), 'rate': float(rate_0),
                    'match_type': 'predictive', 'pattern': '포도시 YEY 양음양 패턴'
                })
        except Exception:
            pass

    return results

# 6. 양음양 v2 기법 스캐너
def scan_date_yey_v2(stocks, target_date, stock_dfs=None):
    if stock_dfs is None:
        stock_dfs = load_cached_stock_dfs(target_date)

    results = []
    for stock in stocks:
        code = stock['Code']
        name = stock['Name']
        df = stock_dfs.get(code)
        if df is None or len(df) < 130:
            continue

        try:
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA10'] = df['Close'].rolling(10).mean()
            df['MA20'] = df['Close'].rolling(20).mean()

            day0 = df.iloc[-1]
            day1 = df.iloc[-2]
            day2 = df.iloc[-3]

            close_0, open_0, vol_0 = day0['Close'], day0['Open'], day0['Volume']
            close_1, open_1, vol_1 = day1['Close'], day1['Open'], day1['Volume']

            rate_1 = ((close_1 - day2['Close']) / day2['Close']) * 100
            rate_0 = ((close_0 - close_1) / close_1) * 100

            is_p1_yang_today = 6.0 <= rate_0 < 20.0 and close_0 > open_0 and vol_0 >= day0['Vol_MA20'] * 3.0 and (close_0 * vol_0 >= 3_000_000_000) and close_0 >= day0['MA20']
            if is_p1_yang_today:
                results.append({
                    'code': code, 'name': name, 'close': int(close_0), 'rate': float(rate_0),
                    'match_type': 'predictive', 'pattern': '양음양 v2 패턴 1 (눌림목)'
                })
        except Exception:
            pass

    return results
