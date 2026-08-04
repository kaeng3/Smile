# -*- coding: utf-8 -*-
import os
import sys
import datetime
import json
import FinanceDataReader as fdr
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def get_market_list():
    df_kospi = fdr.StockListing('KOSPI')
    df_kosdaq = fdr.StockListing('KOSDAQ')
    
    exclude_keywords = ['우B', '우C', '스팩', '리츠', '레버리지', '인버스', 'ETN', 'ETF', '하이브리드']
    def is_excluded(name):
        return name.endswith('우') or any(kw in name for kw in exclude_keywords)
        
    stocks = []
    for s in df_kospi[['Code', 'Name']].to_dict('records'):
        if not is_excluded(s['Name']): stocks.append(s)
    for s in df_kosdaq[['Code', 'Name']].to_dict('records'):
        if not is_excluded(s['Name']): stocks.append(s)
    return stocks

def scan_date(stocks, target_date):
    print(f"[{target_date.strftime('%Y-%m-%d')}] 스캔 시작...")
    
    start_date = target_date - datetime.timedelta(days=220)
    
    results = []
    
    def check_stock(stock):
        code = stock['Code']
        name = stock['Name']
        try:
            df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
            # target_date must be the last row of df
            if len(df) < 125: return None
            
            # Check if last row is actually target_date
            last_date = df.index[-1].to_pydatetime().date()
            if last_date != target_date.date():
                return None
                
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA10'] = df['Close'].rolling(10).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            df['MA120'] = df['Close'].rolling(120).mean()
            
            day0 = df.iloc[-1]
            day1 = df.iloc[-2]
            day2 = df.iloc[-3]
            
            close_0, open_0, high_0, low_0, vol_0 = day0['Close'], day0['Open'], day0['High'], day0['Low'], day0['Volume']
            close_1, open_1, high_1, low_1, vol_1 = day1['Close'], day1['Open'], day1['High'], day1['Low'], day1['Volume']
            
            # 1. 20억 이상 + 거래량 급증 Stage 1 check
            recent_5_days = df.iloc[-5:]
            stage1_passed = False
            for idx in range(len(recent_5_days)):
                d = recent_5_days.iloc[idx]
                if d['Close'] * d['Volume'] >= 2_000_000_000 and d['Volume'] >= d['Vol_MA20'] * 1.5:
                    stage1_passed = True
                    break
            if not stage1_passed:
                return None
                
            # 2. 이평선 및 기법 매칭
            rate_1 = ((close_1 - day2['Close']) / day2['Close']) * 100
            rate_0 = ((close_0 - close_1) / close_1) * 100
            
            # Pattern 1 (기본형)
            is_p1_yang = 4.0 <= rate_1 <= 22.0 and close_1 > open_1
            is_p1_pred = is_p1_yang and (close_0 < open_0) and (vol_0 <= vol_1 * 0.7) and (close_0 >= day0['MA10'] * 0.99)
            is_p1_comp = is_p1_yang and (close_0 >= open_0 * 1.04) and (vol_0 >= vol_1 * 1.5) and (day1['Close'] < day1['Open'])
            
            # Pattern 2 (윗꼬리)
            body_1 = abs(close_1 - open_1)
            tail_1 = high_1 - max(close_1, open_1)
            is_p2_yang = tail_1 >= body_1 * 0.75 and close_1 > open_1 and vol_1 >= day1['Vol_MA20'] * 1.5
            is_p2_pred = is_p2_yang and (low_0 <= day0['MA5'] * 1.025) and (close_0 <= open_0 * 1.03) and (vol_0 <= vol_1 * 0.8)
            is_p2_comp = is_p2_yang and (low_0 <= day0['MA5'] * 1.025) and (close_0 >= open_0 * 1.05) and (vol_0 >= vol_1 * 1.5)
            
            # 60일의 법칙
            near_ma60 = (day0['MA60'] * 0.965 <= close_0 <= day0['MA60'] * 1.05) or (day0['MA60'] * 0.965 <= low_0 <= day0['MA60'] * 1.05)
            near_ma120 = (day0['MA120'] * 0.965 <= close_0 <= day0['MA120'] * 1.05) or (day0['MA120'] * 0.965 <= low_0 <= day0['MA120'] * 1.05)
            
            is_60ma_law = (near_ma60 or near_ma120) and (close_0 < open_0) and (vol_0 <= day0['Vol_MA20'] * 0.8)
            
            match_type = None
            pattern_name = None
            
            if is_p1_pred:
                match_type = 'predictive'
                pattern_name = 'Pattern 1'
            elif is_p1_comp:
                match_type = 'completed'
                pattern_name = 'Pattern 1'
            elif is_p2_pred:
                match_type = 'predictive'
                pattern_name = 'Pattern 2'
            elif is_p2_comp:
                match_type = 'completed'
                pattern_name = 'Pattern 2'
            elif is_60ma_law:
                match_type = 'predictive'
                pattern_name = '60일의 법칙'
                
            if match_type:
                return {
                    'code': code, 'name': name, 'close': int(close_0), 'rate': float(rate_0),
                    'match_type': match_type, 'pattern': pattern_name
                }
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_stock, s): s for s in stocks}
        for f in as_completed(futures):
            res = f.result()
            if res: results.append(res)
            
    print(f"[{target_date.strftime('%Y-%m-%d')}] 스캔 완료. 포착 개수: {len(results)}")
    return results

if __name__ == "__main__":
    stocks = get_market_list()
    dates = [
        datetime.datetime(2026, 7, 6),
        datetime.datetime(2026, 7, 7),
        datetime.datetime(2026, 7, 8)
    ]
    
    for d in dates:
        results = scan_date(stocks, d)
        filename = f"scan_results_{d.strftime('%Y%m%d')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"Saved {filename}")
