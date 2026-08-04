# -*- coding: utf-8 -*-
import datetime
import FinanceDataReader as fdr
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def test_scans(stocks, target_date):
    long_start = target_date - datetime.timedelta(days=220)
    candidates = []
    
    # 1단계 filter (이격 10% 이내)
    def filter_light(stock):
        code = stock['Code']
        try:
            df = fdr.DataReader(code, (target_date - datetime.timedelta(days=40)).strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
            if len(df) < 20: return None
            if df.index[-1].to_pydatetime().date() != target_date.date(): return None
            ma20 = df['Close'].rolling(20).mean().iloc[-1]
            close_curr = df['Close'].iloc[-1]
            if abs(close_curr - ma20) / ma20 <= 0.10:
                return stock
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=40) as executor:
        futures = {executor.submit(filter_light, s): s for s in stocks}
        for f in as_completed(futures):
            res = f.result()
            if res: candidates.append(res)
            
    p1_matches = []
    p23_matches = []
    
    def check_details(stock):
        code = stock['Code']
        name = stock['Name']
        try:
            df = fdr.DataReader(code, long_start.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
            if len(df) < 140: return None
            
            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA10'] = df['Close'].rolling(10).mean()
            df['MA13'] = df['Close'].rolling(13).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            df['MA120'] = df['Close'].rolling(120).mean()
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            
            close_curr = df['Close'].iloc[-1]
            ma5_curr = df['MA5'].iloc[-1]
            ma10_curr = df['MA10'].iloc[-1]
            ma13_curr = df['MA13'].iloc[-1]
            ma20_curr = df['MA20'].iloc[-1]
            ma60_curr = df['MA60'].iloc[-1]
            ma120_curr = df['MA120'].iloc[-1]
            
            is_ma120_down_or_flat = ma120_curr <= df['MA120'].iloc[-11] * 1.015
            is_ma60_down_or_flat = ma60_curr <= df['MA60'].iloc[-11] * 1.015
            is_ma20_down_or_flat = ma20_curr <= df['MA20'].iloc[-11] * 1.015
            
            day0 = df.iloc[-1]
            day1 = df.iloc[-2]
            day2 = df.iloc[-3]
            
            rate_1 = ((day1['Close'] - day2['Close']) / day2['Close']) * 100
            rate_0 = ((day0['Close'] - day1['Close']) / day1['Close']) * 100
            
            # Relax yesterday's Yang volume multiplier to 1.5x (from 2.5x)
            is_yesterday_yang = 4.0 <= rate_1 <= 22.0 and day1['Close'] > day1['Open'] and day1['Volume'] >= df['Vol_MA20'].iloc[-2] * 1.5
            # Relax today's Eum volume check to 0.75x (from 0.65x)
            is_today_eum = day0['Close'] < day0['Open'] and day0['Volume'] <= day1['Volume'] * 0.75
            
            if not (is_yesterday_yang and is_today_eum):
                return None
                
            # Relax touch volume to 1.5x (from 1.8x)
            # Relax support distance to 5% (from 3.5%)
            
            # 패턴 1
            if is_ma120_down_or_flat:
                has_touch = False
                for idx in range(3, 18):
                    if idx > len(df): break
                    row = df.iloc[-idx]
                    high_val = row['High']
                    close_val = row['Close']
                    open_val = row['Open']
                    body = abs(close_val - open_val)
                    tail = high_val - max(close_val, open_val)
                    ma120_val = df['MA120'].iloc[-idx]
                    vol_ma20_val = df['Vol_MA20'].iloc[-idx]
                    
                    if tail >= body * 0.35 and high_val >= ma120_val * 0.975 and row['Volume'] >= vol_ma20_val * 1.5:
                        has_touch = True
                        break
                
                is_supported = (ma20_curr * 0.97 <= close_curr <= ma20_curr * 1.05) or (ma60_curr * 0.97 <= close_curr <= ma60_curr * 1.05)
                if has_touch and is_supported:
                    p1_matches.append(f"{code}|{name}|{close_curr}|{rate_0:.2f}%|P1")
                    return
            
            # 패턴 2
            if is_ma120_down_or_flat and is_ma60_down_or_flat:
                has_touch = False
                for idx in range(3, 18):
                    if idx > len(df): break
                    row = df.iloc[-idx]
                    high_val = row['High']
                    close_val = row['Close']
                    open_val = row['Open']
                    body = abs(close_val - open_val)
                    tail = high_val - max(close_val, open_val)
                    ma60_val = df['MA60'].iloc[-idx]
                    vol_ma20_val = df['Vol_MA20'].iloc[-idx]
                    
                    if tail >= body * 0.35 and high_val >= ma60_val * 0.975 and row['Volume'] >= vol_ma20_val * 1.5:
                        has_touch = True
                        break
                
                is_supported = (ma13_curr * 0.97 <= close_curr <= ma13_curr * 1.05) or (ma20_curr * 0.97 <= close_curr <= ma20_curr * 1.05)
                if has_touch and is_supported:
                    p23_matches.append(f"{code}|{name}|{close_curr}|{rate_0:.2f}%|P2")
                    return
                    
            # 패턴 3
            if is_ma120_down_or_flat and is_ma60_down_or_flat and is_ma20_down_or_flat:
                has_touch = False
                for idx in range(3, 18):
                    if idx > len(df): break
                    row = df.iloc[-idx]
                    high_val = row['High']
                    close_val = row['Close']
                    open_val = row['Open']
                    body = abs(close_val - open_val)
                    tail = high_val - max(close_val, open_val)
                    ma20_val = df['MA20'].iloc[-idx]
                    vol_ma20_val = df['Vol_MA20'].iloc[-idx]
                    
                    if tail >= body * 0.35 and high_val >= ma20_val * 0.975 and row['Volume'] >= vol_ma20_val * 1.5:
                        has_touch = True
                        break
                
                is_supported = (ma5_curr * 0.97 <= close_curr <= ma5_curr * 1.04) or (ma10_curr * 0.97 <= close_curr <= ma10_curr * 1.05)
                if has_touch and is_supported:
                    p23_matches.append(f"{code}|{name}|{close_curr}|{rate_0:.2f}%|P3")
                    return
        except Exception as e:
            pass
        return None

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_details, s): s for s in candidates}
        for f in as_completed(futures):
            f.result()
            
    print("P1_START")
    for m in p1_matches:
        print(m)
    print("P1_END")
    print("P23_START")
    for m in p23_matches:
        print(m)
    print("P23_END")

if __name__ == '__main__':
    target_date = datetime.datetime(2026, 7, 15)
    stocks = get_market_list()
    test_scans(stocks, target_date)
