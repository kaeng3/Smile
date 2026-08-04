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

def scan_podosi_relaxed(stocks, target_date):
    long_start = target_date - datetime.timedelta(days=220)
    candidates = []
    
    def filter_light(stock):
        code = stock['Code']
        try:
            df = fdr.DataReader(code, (target_date - datetime.timedelta(days=40)).strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
            if len(df) < 20: return None
            if df.index[-1].to_pydatetime().date() != target_date.date(): return None
            
            ma20 = df['Close'].rolling(20).mean().iloc[-1]
            close_curr = df['Close'].iloc[-1]
            
            if abs(close_curr - ma20) / ma20 <= 0.05:
                return stock
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=40) as executor:
        futures = {executor.submit(filter_light, s): s for s in stocks}
        for f in as_completed(futures):
            res = f.result()
            if res: candidates.append(res)
            
    results = []
    def check_podosi_details(stock):
        code = stock['Code']
        name = stock['Name']
        try:
            df = fdr.DataReader(code, long_start.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
            if len(df) < 125: return None
            
            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            df['MA120'] = df['Close'].rolling(120).mean()
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            
            close_curr = df['Close'].iloc[-1]
            ma20_curr = df['MA20'].iloc[-1]
            ma60_curr = df['MA60'].iloc[-1]
            ma120_curr = df['MA120'].iloc[-1]
            
            is_near_ma20 = ma20_curr * 0.985 <= close_curr <= ma20_curr * 1.035
            
            # ONLY require 5-day MA to be upward-sloping!
            is_ma5_up = df['MA5'].iloc[-1] > df['MA5'].iloc[-2]
            
            has_upper_tail_touch = False
            for idx in range(2, 14):
                if idx > len(df): break
                row = df.iloc[-idx]
                high_val = row['High']
                close_val = row['Close']
                open_val = row['Open']
                body = abs(close_val - open_val)
                tail = high_val - max(close_val, open_val)
                
                ma60_val = df['MA60'].iloc[-idx]
                ma120_val = df['MA120'].iloc[-idx]
                vol_ma20_val = df['Vol_MA20'].iloc[-idx]
                
                if tail >= body * 0.5 and (abs(high_val - ma60_val)/ma60_val <= 0.025 or abs(high_val - ma120_val)/ma120_val <= 0.025) and row['Volume'] >= vol_ma20_val * 2.0:
                    has_upper_tail_touch = True
                    break
                    
            if is_near_ma20 and has_upper_tail_touch and is_ma5_up:
                c_prev = df['Close'].iloc[-2]
                rate = ((close_curr - c_prev) / c_prev) * 100
                return {
                    'code': code, 'name': name, 'close': int(close_curr), 'rate': float(rate)
                }
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_podosi_details, s): s for s in candidates}
        for f in as_completed(futures):
            res = f.result()
            if res: results.append(res)
            
    return results

if __name__ == '__main__':
    target_date = datetime.datetime(2026, 7, 15)
    stocks = get_market_list()
    res = scan_podosi_relaxed(stocks, target_date)
    print("MATCHES_START")
    for r in res:
        print(f"{r['code']}|{r['name']}|{r['close']}|{r['rate']:.2f}%")
    print("MATCHES_END")
