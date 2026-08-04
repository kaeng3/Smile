import os
import pandas as pd
import datetime

# FinanceDataReader가 설치되어 있지 않다면 설치하는 코드 포함
try:
    import FinanceDataReader as fdr
except ImportError:
    print("FinanceDataReader 라이브러리를 설치합니다...")
    os.system("pip install finance-datareader")
    import FinanceDataReader as fdr

def get_market_list():
    """KOSPI, KOSDAQ 종목 리스트를 가져옵니다."""
    print("시장 종목 정보를 가져오는 중...")
    df_kospi = fdr.StockListing('KOSPI')
    df_kosdaq = fdr.StockListing('KOSDAQ')
    
    # 주요 컬럼(Code, Name)만 추출
    kospi_list = df_kospi[['Code', 'Name']].to_dict('records')
    kosdaq_list = df_kosdaq[['Code', 'Name']].to_dict('records')
    
    return kospi_list + kosdaq_list

def scan_yang_eum_yang(stock_list, limit=150):
    """양음양 패턴을 스캔합니다."""
    print(f"총 {len(stock_list)}개 종목 분석을 시작합니다. (우량주 및 첫 필터링 적용)")
    
    # 결과 저장용 리스트
    pattern_1_results = []
    pattern_2_results = []
    pattern_3_results = []
    
    # 분석 기준일 (최근 약 15영업일 데이터 확보)
    today = datetime.datetime.today()
    start_date = today - datetime.timedelta(days=30)
    
    count = 0
    for stock in stock_list:
        code = stock['Code']
        name = stock['Name']
        
        try:
            # 주가 데이터 가져오기
            df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'))
            if len(df) < 10:
                continue
                
            # 5일, 10일 이동평균선 계산
            df['MA5'] = df['Close'].rolling(window=5).mean()
            df['MA10'] = df['Close'].rolling(window=10).mean()
            
            # 최근 3영업일 데이터 추출
            # df.iloc[-1] -> 오늘 (0봉전)
            # df.iloc[-2] -> 어제 (1봉전)
            # df.iloc[-3] -> 그저께 (2봉전)
            
            day0 = df.iloc[-1]  # 오늘
            day1 = df.iloc[-2]  # 어제
            
            # 거래량 및 가격 변수
            close_0, open_0, high_0, low_0, vol_0 = day0['Close'], day0['Open'], day0['High'], day0['Low'], day0['Volume']
            close_1, open_1, high_1, low_1, vol_1 = day1['Close'], day1['Open'], day1['High'], day1['Low'], day1['Volume']
            
            # 1봉전(어제) 대비 0봉전(오늘) 등락률 계산
            prev_close = df.iloc[-3]['Close'] if len(df) >= 3 else open_1
            rate_1 = ((close_1 - prev_close) / prev_close) * 100  # 어제 등락률
            rate_0 = ((close_0 - close_1) / close_1) * 100        # 오늘 등락률
            
            # 동전주 및 거래량 없는 주식 필터링
            if close_0 < 1000 or vol_1 < 50000:
                continue

            # ----------------------------------------------------
            # [Pattern 1 스캔]
            # 1) 어제 5% 이상 20% 이하의 양봉
            # 2) 오늘 5일선을 이탈하지 않는 음봉 (종가가 5일선 위이고, 저가도 5일선 지지)
            # 3) 오늘 거래량이 어제 양봉 거래량의 60% 이하 (핵심)
            # ----------------------------------------------------
            is_pattern1_day1 = 5.0 <= rate_1 <= 20.0 and close_1 > open_1
            is_pattern1_day2 = close_0 < open_0 and vol_0 <= vol_1 * 0.60
            is_pattern1_support = close_0 >= day0['MA5'] and low_0 >= day0['MA5'] * 0.99
            
            if is_pattern1_day1 and is_pattern1_day2 and is_pattern1_support:
                pattern_1_results.append({
                    'code': code, 'name': name, 'close': close_0, 'rate': rate_0, 
                    'vol_ratio': (vol_0 / vol_1) * 100, 'ma5': day0['MA5']
                })
                
            # ----------------------------------------------------
            # [Pattern 2 스캔]
            # 1) 어제 윗꼬리가 긴 대량 거래량의 양봉
            # 2) 오늘 시초가 밑에서 단기 이평선(5일선) 부근 지지 확인
            # ----------------------------------------------------
            # 윗꼬리가 몸통보다 길거나 상당함 & 거래량 폭발
            body_1 = abs(close_1 - open_1)
            tail_1 = high_1 - max(close_1, open_1)
            is_pattern2_day1 = tail_1 > body_1 * 0.8 and close_1 > open_1 and vol_1 > df['Volume'].mean() * 2
            
            # 오늘 음봉성 흐름이면서 5일선 부근 터치
            is_pattern2_day2 = low_0 <= day0['MA5'] * 1.02 and close_0 >= day0['MA5'] * 0.98
            
            if is_pattern2_day1 and is_pattern2_day2:
                pattern_2_results.append({
                    'code': code, 'name': name, 'close': close_0, 'rate': rate_0, 'ma5': day0['MA5']
                })

            # ----------------------------------------------------
            # [Pattern 3 스캔]
            # 1) 5%~20% 양봉 이후 수일간 거래량 지속 감소하며 횡보
            # 2) 5일선 또는 10일선 부근 다분할 매수 타이밍 (단, 5일선을 이탈하지 않아야 함)
            # ----------------------------------------------------
            # 최근 4일 내에 5%~20% 장대양봉이 있었고, 그 이후 거래량이 계단식 감소하는지
            if len(df) >= 5:
                day2 = df.iloc[-3]
                day3 = df.iloc[-4]
                # 3봉전 또는 2봉전에 장대양봉이 발생했는지
                was_big_yang = (5.0 <= ((day2['Close'] - day3['Close']) / day3['Close']) * 100 <= 20.0) or \
                               (5.0 <= ((day3['Close'] - df.iloc[-5]['Close']) / df.iloc[-5]['Close']) * 100 <= 20.0)
                
                # 거래량이 계속 줄어드는 추세인지 (오늘 거래량이 3일전 거래량보다 훨씬 적음)
                vol_decreasing = vol_0 < day1['Volume'] and day1['Volume'] < day2['Volume']
                
                # 5일선 위에 안착 (이탈하지 않음)
                on_support = close_0 >= day0['MA5'] and low_0 >= day0['MA5'] * 0.99
                
                # 횡보하는 기간(어제, 그저께 등) 동안 종가가 5일선을 이탈하지 않았어야 함 (PDF 기준)
                consolidating_above_ma5 = day1['Close'] >= day1['MA5'] and day2['Close'] >= day2['MA5']
                
                if was_big_yang and vol_decreasing and on_support and consolidating_above_ma5:
                    pattern_3_results.append({
                        'code': code, 'name': name, 'close': close_0, 'ma5': day0['MA5'], 'ma10': day0['MA10']
                    })

            count += 1
            if count >= limit:
                break
                
        except Exception as e:
            continue
            
    return pattern_1_results, pattern_2_results, pattern_3_results

if __name__ == "__main__":
    stocks = get_market_list()
    # 전체 시장 종목 중 상위 300개를 우선 스캔 테스트 (실전 사용 시 stocks[:300]의 슬라이싱을 지워 전체 종목을 보거나 KOSPI200 종목 필터 등을 사용하세요)
    p1, p2, p3 = scan_yang_eum_yang(stocks[:300], limit=300)
    
    print("\n" + "="*50)
    print("★ 양음양 패턴 1 (기본형) 포착 종목 ★")
    print("="*50)
    for s in p1:
        print(f"[{s['name']}({s['code']})] 종가: {s['close']:,}원 | 오늘 등락률: {s['rate']:.2f}% | 오늘 거래량 비율: {s['vol_ratio']:.1f}% (어제대비)")
        
    print("\n" + "="*50)
    print("★ 양음양 패턴 2 (윗꼬리 대량거래 돌파형) 포착 종목 ★")
    print("="*50)
    for s in p2:
        print(f"[{s['name']}({s['code']})] 종가: {s['close']:,}원 | 오늘 등락률: {s['rate']:.2f}%")

    print("\n" + "="*50)
    print("★ 양음양 패턴 3 (기간 조정/거래량 점감형) 포착 종목 ★")
    print("="*50)
    for s in p3:
        print(f"[{s['name']}({s['code']})] 종가: {s['close']:,}원 | 5일선: {s['ma5']:.0f}원 | 10일선: {s['ma10']:.0f}원")
