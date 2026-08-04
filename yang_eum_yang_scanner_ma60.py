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
    """우선주, ETF 등을 제외한 KOSPI, KOSDAQ 전 종목 리스트를 가져옵니다."""
    try:
        df_kospi = fdr.StockListing('KOSPI')
        df_kosdaq = fdr.StockListing('KOSDAQ')
        
        def is_excluded(name):
            exclude_keywords = ['우B', '우C', '스팩', '리츠', '레버리지', '인버스', 'ETN', 'ETF', '하이브리드']
            if name.endswith('우') or any(kw in name for kw in exclude_keywords):
                return True
            return False

        kospi_list = [s for s in df_kospi[['Code', 'Name']].to_dict('records') if not is_excluded(s['Name'])]
        kosdaq_list = [s for s in df_kosdaq[['Code', 'Name']].to_dict('records') if not is_excluded(s['Name'])]
        
        return kospi_list + kosdaq_list
    except Exception as e:
        print(f"시장 종목 정보를 가져오는 데 실패했습니다: {e}")
        return []

def analyze_ma60_law_stock(stock, start_date, today):
    """신준경의 '60일선 법칙 실전 매매 기준'을 엄격히 계량화하여 분석합니다."""
    code = stock['Code']
    name = stock['Name']
    
    try:
        # 과거 2년치 데이터 가져오기 (2년 = 730일)
        df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
        if len(df) < 150:  # 최소한의 거래일수 확인
            return None
            
        day0 = df.iloc[-1]  # 오늘
        day1 = df.iloc[-2]  # 어제
        close_0, low_0, vol_0 = day0['Close'], day0['Low'], day0['Volume']
        
        # 1. 과거 시세 분출 이력 확인 (과거 2년 내 최고가가 현재가보다 2배 이상인가?)
        # 낙폭과대주일수록 유리
        max_price_2y = df['High'].max()
        if max_price_2y < close_0 * 2.0:
            return None
            
        # 이동평균선 계산
        df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        df['MA120'] = df['Close'].rolling(window=120).mean()
        
        # 다시 오늘과 어제의 데이터 갱신 (이평선 포함)
        day0 = df.iloc[-1]
        day1 = df.iloc[-2]
        
        # 2. 역배열 상태에서의 이평선 혼조
        # 기본적으로 중장기 이평선이 역배열 (120일선 > 60일선)
        is_reverse_alignment = day0['MA120'] > day0['MA60']
        if not is_reverse_alignment:
            return None
            
        # 5일선이 20일선 위에 위치 (골든크로스 먹은 상태)
        is_gold_cross = day0['MA5'] > day0['MA20']
        if not is_gold_cross:
            return None
            
        # 3. 120일선 돌파 후 60일선 지지 (최근 20영업일 내에 발생했는가?)
        # 120일선 돌파 이력 및 거래대금 20억 & 거래량 300% 급증일자 확인
        crossed_ma120 = False
        breakout_idx = -1
        
        # 최근 20영업일 분석
        for idx in range(-20, 0):
            if idx-1 < -len(df):
                continue
            d_prev = df.iloc[idx-1]
            d_curr = df.iloc[idx]
            
            # 대량 거래량을 실으며 120일선을 강하게 돌파
            d_amt = d_curr['Close'] * d_curr['Volume']
            is_volume_spike = d_curr['Volume'] >= d_curr['Vol_MA20'] * 3.0 and d_amt >= 2_000_000_000
            
            # 120일선 상향 돌파 조건
            is_breakout = d_prev['Close'] < d_prev['MA120'] and d_curr['Close'] >= d_curr['MA120']
            
            if is_breakout and is_volume_spike:
                crossed_ma120 = True
                breakout_idx = idx
                break
                
        if not crossed_ma120 or breakout_idx == -1:
            return None
            
        # 120일선 돌파 이전(횡보/하락기)의 전저점(Local Min)을 찾습니다.
        # 돌파일 기준 60일 전부터 3일 전 사이의 최저 저가(Low)
        hist_len = len(df)
        abs_breakout_idx = hist_len + breakout_idx  # 음수 인덱스를 양수 절대 인덱스로 변환
        search_start = max(0, abs_breakout_idx - 60)
        search_end = max(1, abs_breakout_idx - 3)
        
        pre_low = df.iloc[search_start:search_end]['Low'].min()
        if pd.isna(pre_low) or pre_low <= 0:
            pre_low = day0['MA60'] * 0.95  # 전저점이 없는 경우 대안값
            
        # 4. 현재 조정 및 지지 구간 확인 (120일선 ~ 60일선 매수 밴드 전략 + 휩소 대비 전저점 지지)
        # 매수 밴드: 종가가 120일선 이하에 있으며, 60일선 부근 혹은 전저점 이상
        in_buy_band = (day0['MA60'] * 0.95 <= close_0 <= day0['MA120'] * 1.05)
        
        # 휩소 극복: 60일선을 살짝 깨더라도 전저점을 훼손하지 않으면 지지 성공으로 판단
        held_pre_low = (low_0 >= pre_low * 0.975)  # 전저점 대비 -2.5% 마진 내 사수
        
        # 단기 이평선(5일선, 20일선)이 고개를 들며 상향하고 있는지 확인 (디딤돌 역할)
        mas_curling_up = day0['MA5'] >= day1['MA5'] or day0['MA20'] >= day1['MA20']
        
        # 지지 조건 결합 (매수 밴드 내에 위치하고, 전저점 지지를 지켜냈으며, 단기선이 돌아나가는지)
        if in_buy_band and held_pre_low and mas_curling_up:
            gap_ratio = (max_price_2y / close_0)  # 현재가 대비 최고가 낙폭 배수
            double_support = abs(day0['MA60'] - pre_low) / pre_low <= 0.05  # 60일선과 전저점의 수렴 여부
            
            return {
                'code': code, 'name': name, 'close': close_0, 'max_2y': max_price_2y, 
                'gap_ratio': gap_ratio, 'ma60': day0['MA60'], 'ma120': day0['MA120'],
                'pre_low': pre_low, 'double_support': double_support
            }
            
    except Exception as e:
        pass
    return None

def scan_gamejoa_ma60_law(stock_list):
    """멀티스레딩 고속 병렬 처리로 60일선 법칙 종목을 스캔합니다."""
    print(f"총 {len(stock_list)}개 종목 대상: [신준경 60일선 법칙 실전 매매 기준] 스캔 시작...")
    
    results = []
    today = datetime.datetime.today()
    start_date = today - datetime.timedelta(days=730)  # 과거 2년 데이터 확보
    
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(analyze_ma60_law_stock, stock, start_date, today): stock for stock in stock_list}
        
        for future in as_completed(futures):
            res = future.result()
            if res:
                results.append(res)
                
    # 낙폭과대(최고가 대비 격차) 순으로 내림차순 정렬
    results = sorted(results, key=lambda x: x['gap_ratio'], reverse=True)
    return results

if __name__ == "__main__":
    stocks = get_full_market_list()
    candidates = scan_gamejoa_ma60_law(stocks)
    
    print("\n" + "="*85)
    print("★ [결과] 신준경(게임조아)의 60일선 법칙 (휩소/전저점 지지 결합) 추천 종목 ★")
    print("="*85)
    
    if candidates:
        for idx, s in enumerate(candidates, 1):
            double_str = " (★60일선 + 전저점 중첩지지 구간★)" if s['double_support'] else ""
            print(f"#{idx:02d} [{s['name']}({s['code']})] 종가: {s['close']:,}원 | 2년 최고가: {s['max_2y']:,}원 (현재가 대비 {s['gap_ratio']:.1f}배 낙폭과대)")
            print(f"    - 매수 밴드: 120일선({s['ma120']:.0f}원) ~ 60일선({s['ma60']:.0f}원) 사이 위치")
            print(f"    - 전저점 지지 가격: {s['pre_low']:.0f}원 사수 중{double_str}")
            print("-" * 85)
    else:
        print("조건에 만족하는 종목이 없습니다.")
