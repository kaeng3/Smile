import os
import sys
import datetime
import json
import socket
socket.setdefaulttimeout(6.0)
import FinanceDataReader as fdr
from concurrent.futures import ThreadPoolExecutor, as_completed

def test_podosi_scan(target_date_str):
    target_date = datetime.datetime.strptime(target_date_str, '%Y-%m-%d')
    stocks = fdr.StockListing('KRX')
    stocks = stocks[stocks['Market'].isin(['KOSPI', 'KOSDAQ'])].to_dict('records')
    
    long_start = target_date - datetime.timedelta(days=380)
    
    results = []

    def check(s):
        code = s['Code']
        name = s['Name']
        try:
            df = fdr.DataReader(code, long_start.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
            if len(df) < 224: return None
            
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            df['MA120'] = df['Close'].rolling(120).mean()
            df['MA224'] = df['Close'].rolling(224).mean()
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            
            close_curr = df['Close'].iloc[-1]
            ma20_curr = df['MA20'].iloc[-1]
            ma60_curr = df['MA60'].iloc[-1]
            
            # 기준봉 탐색 (최근 7일 이내)
            breakout_idx_60 = -1
            for idx in range(1, 8):
                if idx >= len(df) - 1: break
                c_val = df['Close'].iloc[-idx]
                ma60_val = df['MA60'].iloc[-idx]
                vol_val = df['Volume'].iloc[-idx]
                vol_ma20_val = df['Vol_MA20'].iloc[-idx]
                
                is_cross_above = c_val > ma60_val and df['Close'].iloc[-idx-1] <= df['MA60'].iloc[-idx-1]
                if is_cross_above and (c_val * vol_val >= 2_000_000_000) and (vol_val >= vol_ma20_val * 2.5):
                    breakout_idx_60 = len(df) - idx
                    break
                    
            if breakout_idx_60 != -1 and ma60_curr > ma20_curr:
                if ma20_curr * 0.96 <= close_curr <= ma60_curr * 1.04:
                    return f"{name}({code})"
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(check, s) for s in stocks]
        for f in as_completed(futures):
            r = f.result()
            if r: results.append(r)
            
    return results

print("7월 23일 신 포도시 스캔 결과:", test_podosi_scan("2026-07-23"))
print("7월 24일 신 포도시 스캔 결과:", test_podosi_scan("2026-07-24"))
