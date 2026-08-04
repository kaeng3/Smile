# -*- coding: utf-8 -*-
import datetime
import json
import FinanceDataReader as fdr
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_market_list():
    df_kospi = fdr.StockListing('KOSPI')
    df_kosdaq = fdr.StockListing('KOSDAQ')
    
    exclude_keywords = ['우B', '우C', '스팩', '리츠', '레버리지', '인버스', 'ETN', 'ETF', '하이브리드']
    def is_excluded(name):
        return name.endswith('우') or any(kw in name for kw in exclude_keywords)
        
    stocks = []
    for s in df_kospi[['Code', 'Name', 'Marcap']].to_dict('records'):
        if not is_excluded(s['Name']): stocks.append(s)
    for s in df_kosdaq[['Code', 'Name', 'Marcap']].to_dict('records'):
        if not is_excluded(s['Name']): stocks.append(s)
    return stocks

def scan_date_strict(stocks, target_date):
    print(f"[{target_date.strftime('%Y-%m-%d')}] 정밀 검증 스캔 시작...")
    short_start = target_date - datetime.timedelta(days=45) # 30영업일치 (Vol_MA20 계산을 위해)
    
    candidates = []
    
    def filter_lightweight(stock):
        code = stock['Code']
        marcap = stock.get('Marcap', 0)
        
        # 대형주 1.5배, 중소형주 2.0배 거래량 조건
        vol_factor = 1.5 if marcap >= 1_000_000_000_000 else 2.0
        
        try:
            df = fdr.DataReader(code, short_start.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
            if len(df) < 22: return None
            
            # 마지막 거래일 매칭 확인
            if df.index[-1].to_pydatetime().date() != target_date.date():
                return None
                
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            
            # 최근 5영업일 중 돌파봉이 있었는지 엄격히 필터링
            has_breakout = False
            for i in range(-5, 0):
                if i-1 < -len(df): continue
                c_prev = df.iloc[i-1]['Close']
                c_curr = df.iloc[i]['Close']
                o_curr = df.iloc[i]['Open']
                vol_curr = df.iloc[i]['Volume']
                vol_ma20 = df.iloc[i]['Vol_MA20']
                
                rate = ((c_curr - c_prev) / c_prev) * 100
                amt = c_curr * vol_curr
                
                # 조건 1: 양봉 등락률 4% ~ 22%
                # 조건 2: 거래량 증가 (vol_factor배)
                # 조건 3: 거래대금 20억 이상
                if 4.0 <= rate <= 22.0 and c_curr > o_curr and amt >= 2_000_000_000 and vol_curr >= vol_ma20 * vol_factor:
                    has_breakout = True
                    break
            
            # 60일선의 법칙은 breakout이 없어도 지지원에 닿으면 되므로 1단계 필터링에 우회 경로 마련
            # 60일선 체크를 위해 최근 종가가 대략 60일선 부근에 위치할 만한 조건은 2단계에서 정밀 체크
            # 단, 60일선의 법칙도 최근 거래량 감소 음봉이어야 함
            day0 = df.iloc[-1]
            is_down = day0['Close'] < day0['Open']
            
            if has_breakout or is_down:
                return stock
        except Exception:
            pass
        return None

    print("1단계: 양봉/거래량/거래대금 기준 필터링 중...")
    with ThreadPoolExecutor(max_workers=40) as executor:
        futures = {executor.submit(filter_lightweight, s): s for s in stocks}
        for f in as_completed(futures):
            res = f.result()
            if res: candidates.append(res)
            
    print(f"1단계 통과 종목: {len(candidates)}개. 2단계 정밀 이평선 매칭 시작...")
    
    results = []
    long_start = target_date - datetime.timedelta(days=220)
    
    def check_details(stock):
        code = stock['Code']
        name = stock['Name']
        marcap = stock.get('Marcap', 0)
        vol_factor = 1.5 if marcap >= 1_000_000_000_000 else 2.0
        
        try:
            df = fdr.DataReader(code, long_start.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
            if len(df) < 125: return None
            
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
            
            rate_1 = ((close_1 - day2['Close']) / day2['Close']) * 100
            rate_0 = ((close_0 - close_1) / close_1) * 100
            
            # Pattern 1
            is_p1_yang = 4.0 <= rate_1 <= 22.0 and close_1 > open_1 and vol_1 >= day1['Vol_MA20'] * vol_factor and (close_1 * vol_1 >= 2_000_000_000)
            is_p1_pred = is_p1_yang and (close_0 < open_0) and (vol_0 <= vol_1 * 0.7) and (close_0 >= day0['MA10'] * 0.99)
            is_p1_comp = is_p1_yang and (close_0 >= open_0 * 1.04) and (vol_0 >= vol_1 * 1.5) and (day1['Close'] < day1['Open'])
            
            # Pattern 2
            body_1 = abs(close_1 - open_1)
            tail_1 = high_1 - max(close_1, open_1)
            is_p2_yang = tail_1 >= body_1 * 0.75 and close_1 > open_1 and vol_1 >= day1['Vol_MA20'] * vol_factor and (close_1 * vol_1 >= 2_000_000_000)
            is_p2_pred = is_p2_yang and (low_0 <= day0['MA5'] * 1.025) and (close_0 <= open_0 * 1.03) and (vol_0 <= vol_1 * 0.8)
            is_p2_comp = is_p2_yang and (low_0 <= day0['MA5'] * 1.025) and (close_0 >= open_0 * 1.05) and (vol_0 >= vol_1 * 1.5)
            
            # 60일선/120일선 수렴 및 지지 법칙
            is_near_ma60 = (day0['MA60'] * 0.97 <= close_0 <= day0['MA60'] * 1.03) or (day0['MA60'] * 0.97 <= low_0 <= day0['MA60'] * 1.03)
            is_near_ma120 = (day0['MA120'] * 0.97 <= close_0 <= day0['MA120'] * 1.03) or (day0['MA120'] * 0.97 <= low_0 <= day0['MA120'] * 1.03)
            
            is_60ma_predictive = is_near_ma60 and (close_0 < open_0) and (vol_0 <= day0['Vol_MA20'] * 0.8)
            is_120ma_predictive = is_near_ma120 and (close_0 < open_0) and (vol_0 <= day0['Vol_MA20'] * 0.8)
            
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
            elif is_60ma_predictive:
                match_type = 'predictive'
                pattern_name = '60일선 지지' if close_0 >= day0['MA60'] else '60일선 터치/테스트'
            elif is_120ma_predictive:
                match_type = 'predictive'
                pattern_name = '120일선 지지' if close_0 >= day0['MA120'] else '120일선 터치/테스트'
                
            if match_type:
                return {
                    'code': code, 'name': name, 'close': int(close_0), 'rate': float(rate_0),
                    'match_type': match_type, 'pattern': pattern_name
                }
        except Exception as e:
            pass
        return None

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(check_details, c): c for c in candidates}
        for f in as_completed(futures):
            res = f.result()
            if res: results.append(res)
            
    return results

if __name__ == '__main__':
    stocks = get_market_list()
    target_date = datetime.datetime(2026, 7, 10)
    results = scan_date_strict(stocks, target_date)
    print('=== STRICT RESULTS ===')
    for r in results:
        print(r)
