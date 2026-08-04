import os
import sys
import pandas as pd
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

try:
    import FinanceDataReader as fdr
except ImportError:
    print("FinanceDataReader 라이브러리를 설치합니다...")
    os.system("pip install finance-datareader")
    import FinanceDataReader as fdr

def get_full_market_list():
    """KOSPI, KOSDAQ 전 종목 리스트를 가져옵니다."""
    print("시장 전 종목 정보를 가져오는 중...")
    try:
        df_kospi = fdr.StockListing('KOSPI')
        df_kosdaq = fdr.StockListing('KOSDAQ')
        
        # 우선주, ETF, ETN, SPAC 등 제외 필터링 (게임조아 기준)
        def is_excluded(name):
            exclude_keywords = ['우B', '우C', '스팩', '리츠', '레버리지', '인버스', 'ETN', 'ETF', '하이브리드']
            if name.endswith('우') or any(kw in name for kw in exclude_keywords):
                return True
            return False

        kospi_list = [s for s in df_kospi[['Code', 'Name', 'Marcap']].to_dict('records') if not is_excluded(s['Name'])]
        kosdaq_list = [s for s in df_kosdaq[['Code', 'Name', 'Marcap']].to_dict('records') if not is_excluded(s['Name'])]
        
        return kospi_list + kosdaq_list
    except Exception as e:
        print(f"시장 종목 정보를 가져오는 데 실패했습니다: {e}")
        return []

def analyze_single_stock(stock, start_date, today):
    """개별 종목 데이터를 분석하여 조건 충족 여부를 확인합니다."""
    code = stock['Code']
    name = stock['Name']
    marcap = stock.get('Marcap', 0)
    
    # 대형주(시총 1조원 이상) 예외 조항 추가: 거래량 기준 완화 (150% 급증으로 포착)
    # 중소형주는 보다 확실한 수급 유입(200% 급증)을 체크
    if marcap >= 1_000_000_000_000:
        vol_spike_factor = 1.5
    else:
        vol_spike_factor = 2.0
    
    try:
        df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
        if len(df) < 130:
            return None
            
        # 이평선 계산
        df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        df['MA120'] = df['Close'].rolling(window=120).mean()
        
        day0 = df.iloc[-1]
        day1 = df.iloc[-2]
        day2 = df.iloc[-3]
        
        close_0, open_0, high_0, low_0, vol_0 = day0['Close'], day0['Open'], day0['High'], day0['Low'], day0['Volume']
        close_1, open_1, high_1, low_1, vol_1 = day1['Close'], day1['Open'], day1['High'], day1['Low'], day1['Volume']
        
        # 1차 스캔: 최근 5영업일 중 한 번이라도 거래대금 20억 이상 + 거래량 vol_spike_factor배 급증이 있었는가?
        recent_5_days = df.iloc[-5:]
        stage1_passed = False
        for idx in range(len(recent_5_days)):
            d = recent_5_days.iloc[idx]
            d_amt = d['Close'] * d['Volume']
            if d_amt >= 2_000_000_000 and d['Volume'] >= d['Vol_MA20'] * vol_spike_factor:
                stage1_passed = True
                break
        
        if not stage1_passed:
            return None
            
        # 2차 스캔: 60일선 / 120일선의 법칙 검증
        near_ma60 = (day0['MA60'] * 0.965 <= close_0 <= day0['MA60'] * 1.05) or (day0['MA60'] * 0.965 <= low_0 <= day0['MA60'] * 1.05)
        near_ma120 = (day0['MA120'] * 0.965 <= close_0 <= day0['MA120'] * 1.05) or (day0['MA120'] * 0.965 <= low_0 <= day0['MA120'] * 1.05)
        
        recently_crossed = False
        for idx in range(-5, 0):
            d_prev = df.iloc[idx-1]
            d_curr = df.iloc[idx]
            if (d_prev['Close'] < d_prev['MA60'] and d_curr['Close'] >= d_curr['MA60']) or \
               (d_prev['Close'] < d_prev['MA120'] and d_curr['Close'] >= d_curr['MA120']):
                recently_crossed = True
                break
        
        if not (near_ma60 or near_ma120 or recently_crossed):
            return None
            
        rate_1 = ((close_1 - day2['Close']) / day2['Close']) * 100
        rate_0 = ((close_0 - close_1) / close_1) * 100
        
        p1_res, p2_res, p3_res = None, None, None
        match_type = None
        pattern_name = None

        # [Pattern 1 - 기본형]
        is_p1_yang = 4.0 <= rate_1 <= 22.0 and close_1 > open_1
        # Pattern 1 예측형: 오늘 음봉 조정 마감 + 거래량 감소
        is_p1_pred = is_p1_yang and (close_0 < open_0) and (vol_0 <= vol_1 * 0.7) and (close_0 >= day0['MA10'] * 0.99)
        # Pattern 1 완성형: 오늘 양봉 폭등 마감 + 거래량 폭발 (어제는 음봉 눌림이었음)
        is_p1_comp = is_p1_yang and (close_0 >= open_0 * 1.04) and (vol_0 >= vol_1 * 1.5) and (day1['Close'] < day1['Open'])
        
        if is_p1_pred:
            match_type = 'predictive'
            pattern_name = 'Pattern 1 (예측형 - 내일 종가매수/분할진입)'
        elif is_p1_comp:
            match_type = 'completed'
            pattern_name = 'Pattern 1 (완성형 - 금일 급등완료)'

        # [Pattern 2 - 윗꼬리 대량거래형]
        body_1 = abs(close_1 - open_1)
        tail_1 = high_1 - max(close_1, open_1)
        
        is_p2_yang = tail_1 >= body_1 * 0.75 and close_1 > open_1 and vol_1 >= day1['Vol_MA20'] * vol_spike_factor
        is_p2_above_ma10 = close_1 >= day1['MA10'] * 0.99
        
        if is_p2_yang and is_p2_above_ma10 and not match_type:
            # Pattern 2 예측형: 오늘 저점이 5일선 근처이면서, 오늘 캔들이 음봉 조정이거나 도지(폭등하지 않음)
            is_p2_pred = (low_0 <= day0['MA5'] * 1.025) and (close_0 <= open_0 * 1.03) and (vol_0 <= vol_1 * 0.8)
            # Pattern 2 완성형: 오늘 저점이 5일선 터치 후 오늘 곧바로 폭등 마감 (모나미 사례)
            is_p2_comp = (low_0 <= day0['MA5'] * 1.025) and (close_0 >= open_0 * 1.05) and (vol_0 >= vol_1 * 1.5)
            
            if is_p2_pred:
                match_type = 'predictive'
                pattern_name = 'Pattern 2 (예측형 - 내일 시초가이하 진입)'
            elif is_p2_comp:
                match_type = 'completed'
                pattern_name = 'Pattern 2 (완성형 - 금일 눌림목 급등완료)'

        # [Pattern 3 - 기간 조정형]
        if len(df) >= 7 and not match_type:
            yang_idx = -1
            for i in range(-5, -2):
                c_prev = df.iloc[i-1]['Close']
                c_curr = df.iloc[i]['Close']
                o_curr = df.iloc[i]['Open']
                r = ((c_curr - c_prev) / c_prev) * 100
                if 4.0 <= r <= 22.0 and c_curr > o_curr:
                    yang_idx = i
                    break
            
            if yang_idx != -1:
                vol_list = [df.iloc[j]['Volume'] for j in range(yang_idx, 0)]
                vol_decreasing = True
                for k in range(len(vol_list)-1):
                    if vol_list[k+1] >= vol_list[k]:
                        vol_decreasing = False
                        break
                        
                # Pattern 3 예측형: 10일선 지지 횡보 중이면서, 오늘 폭등하지 않음 (안전 매수 밴드)
                is_p3_pred = vol_decreasing and (close_0 >= day0['MA10']) and (low_0 >= day0['MA10'] * 0.99) and (rate_0 <= 3.5)
                # Pattern 3 완성형: 10일선 지지 횡보 후 오늘 장대양봉 돌파 분출
                is_p3_comp = vol_decreasing and (close_0 >= day0['MA10']) and (low_0 >= day0['MA10'] * 0.99) and (rate_0 >= 5.0) and (vol_0 >= day0['Vol_MA20'] * 1.5)
                
                if is_p3_pred:
                    match_type = 'predictive'
                    pattern_name = 'Pattern 3 (예측형 - 기간조정 매집중)'
                elif is_p3_comp:
                    match_type = 'completed'
                    pattern_name = 'Pattern 3 (완성형 - 금일 기간조정 돌파완료)'
                    
        if match_type:
            return {
                'code': code, 'name': name, 'close': close_0, 'rate': rate_0,
                'match_type': match_type, 'pattern_name': pattern_name,
                'ma60': day0['MA60'], 'ma120': day0['MA120']
            }
            
    except Exception as e:
        pass
    return None

def scan_yang_eum_yang_v4_parallel(stock_list, max_workers=30):
    """멀티스레딩을 활용하여 전체 종목을 빠르게 스캔합니다."""
    print(f"총 {len(stock_list)}개 종목 대상: [게임조아 60일선 + 양음양 멀티스레드 스캔] 시작...")
    
    results = []
    today = datetime.datetime.today()
    start_date = today - datetime.timedelta(days=220)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze_single_stock, stock, start_date, today): stock for stock in stock_list}
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if completed % 300 == 0:
                print(f"진행 상황: {completed}/{len(stock_list)} 종목 완료...")
                
            res = future.result()
            if res:
                results.append(res)
                
    return results

if __name__ == "__main__":
    stocks = get_full_market_list()
    results = scan_yang_eum_yang_v4_parallel(stocks, max_workers=30)
    
    predictive_list = [r for r in results if r['match_type'] == 'predictive']
    completed_list = [r for r in results if r['match_type'] == 'completed']
    
    print("\n" + "="*80)
    print("★ [예측형] 내일 공략 관심 종목 (오늘 저거래량 음봉/조정 눌림목) ★")
    print("="*80)
    if predictive_list:
        for idx, s in enumerate(predictive_list, 1):
            print(f"#{idx:02d} [{s['name']}({s['code']})] 종가: {s['close']:,}원 (등락률: {s['rate']:.2f}%) | {s['pattern_name']}")
    else:
        print("조건에 만족하는 종목이 없습니다.")
        
    print("\n" + "="*80)
    print("★ [완성형] 금일 패턴 완성/시세 분출 완료 종목 (사후 공부/패턴 학습용) ★")
    print("="*80)
    if completed_list:
        for idx, s in enumerate(completed_list, 1):
            print(f"#{idx:02d} [{s['name']}({s['code']})] 종가: {s['close']:,}원 (등락률: {s['rate']:.2f}%) | {s['pattern_name']}")
    else:
        print("조건에 만족하는 종목이 없습니다.")
