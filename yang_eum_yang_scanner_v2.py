import os
import sys
import pandas as pd
import datetime

# Windows 콘솔 한글 깨짐 방지용 인코딩 재설정
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass  # 일부 구형 파이썬 환경 대응

# FinanceDataReader 설치 확인 및 불러오기
try:
    import FinanceDataReader as fdr
except ImportError:
    print("FinanceDataReader 라이브러리를 설치합니다...")
    os.system("pip install finance-datareader")
    import FinanceDataReader as fdr

def get_market_list(top_n=200):
    """KOSPI와 KOSDAQ에서 시가총액(Marcap) 상위 종목들을 추출합니다."""
    print(f"KOSPI 및 KOSDAQ 시장에서 시가총액 상위 각 {top_n}개 종목 정보를 가져오는 중...")
    try:
        df_kospi = fdr.StockListing('KOSPI')
        df_kosdaq = fdr.StockListing('KOSDAQ')
        
        # 시가총액(Marcap) 기준으로 내림차순 정렬하여 상위 N개 추출
        df_kospi_sorted = df_kospi.sort_values(by='Marcap', ascending=False).head(top_n)
        df_kosdaq_sorted = df_kosdaq.sort_values(by='Marcap', ascending=False).head(top_n)
        
        kospi_list = df_kospi_sorted[['Code', 'Name']].to_dict('records')
        kosdaq_list = df_kosdaq_sorted[['Code', 'Name']].to_dict('records')
        
        return kospi_list + kosdaq_list
    except Exception as e:
        print(f"시장 종목 정보를 가져오는데 실패했습니다: {e}")
        return []

def scan_yang_eum_yang(stock_list):
    """PDF 기법서 원칙을 엄격하게 적용하여 3가지 양음양 패턴 종목을 발굴합니다."""
    print(f"총 {len(stock_list)}개 우량 종목 분석을 시작합니다.")
    
    p1_results = []
    p2_results = []
    p3_results = []
    
    # 최근 30일(충분한 데이터) 확보
    today = datetime.datetime.today()
    start_date = today - datetime.timedelta(days=40)
    
    for stock in stock_list:
        code = stock['Code']
        name = stock['Name']
        
        try:
            df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'))
            if len(df) < 15:
                continue
                
            # 이동평균선 계산
            df['MA5'] = df['Close'].rolling(window=5).mean()
            df['MA10'] = df['Close'].rolling(window=10).mean()
            df['MA20'] = df['Close'].rolling(window=20).mean()
            
            # 변수 정의 (0봉전=오늘, 1봉전=어제, 2봉전=그저께)
            day0 = df.iloc[-1]
            day1 = df.iloc[-2]
            day2 = df.iloc[-3]
            
            close_0, open_0, high_0, low_0, vol_0 = day0['Close'], day0['Open'], day0['High'], day0['Low'], day0['Volume']
            close_1, open_1, high_1, low_1, vol_1 = day1['Close'], day1['Open'], day1['High'], day1['Low'], day1['Volume']
            
            # 등락률 계산
            rate_1 = ((close_1 - day2['Close']) / day2['Close']) * 100  # 어제 등락률
            rate_0 = ((close_0 - close_1) / close_1) * 100              # 오늘 등락률
            
            # 동전주 필터 및 최소 거래대금 필터 (오늘 거래대금 5억 이상 선호)
            if close_0 < 1000 or (close_0 * vol_0) < 500_000_000:
                continue
                
            # ----------------------------------------------------
            # [Pattern 1 스캔] - 기본형
            # 1) 어제 5% 이상 20% 이하의 양봉 마감
            # 2) 오늘 음봉이며 거래량이 어제 거래량의 60% 이하 (개미 털기)
            # 3) 엄격: 오늘 종가와 저가 모두 5일 이동평균선(MA5)을 깨지 않고 위에 지지
            # 4) 엄격: 오늘 종가가 5일선 대비 너무 멀지 않아야 함 (이격도 5% 이내)
            # ----------------------------------------------------
            is_p1_yang = 5.0 <= rate_1 <= 20.0 and close_1 > open_1
            is_p1_eum = close_0 < open_0 and vol_0 <= vol_1 * 0.60
            
            # 저가와 종가가 모두 5일선 이상인지 엄격 검증
            is_p1_support = close_0 >= day0['MA5'] and low_0 >= day0['MA5'] * 0.995
            is_p1_gap_ok = close_0 <= day0['MA5'] * 1.05  # 단기 이평선이 -5% 권에 있는 종목
            
            if is_p1_yang and is_p1_eum and is_p1_support and is_p1_gap_ok:
                p1_results.append({
                    'code': code, 'name': name, 'close': close_0, 'rate': rate_0,
                    'vol_ratio': (vol_0 / vol_1) * 100, 'ma5': day0['MA5']
                })
                
            # ----------------------------------------------------
            # [Pattern 2 스캔] - 윗꼬리 대량거래 돌파형
            # 1) 어제 대량거래(평균의 2배 이상)이면서 윗꼬리가 몸통의 80% 이상인 양봉
            # 2) 어제 종가가 5일선 위에 위치
            # 3) 오늘 장중 저가가 시초가보다 낮으면서 5일선 근처까지 터치하고 반등 시도
            # 4) 엄격: 오늘 종가가 5일선을 이탈하지 않음
            # ----------------------------------------------------
            body_1 = abs(close_1 - open_1)
            tail_1 = high_1 - max(close_1, open_1)
            avg_vol = df['Volume'].rolling(window=10).mean().iloc[-2]
            
            is_p2_yang = tail_1 >= body_1 * 0.8 and close_1 > open_1 and vol_1 >= avg_vol * 1.8
            is_p2_above_ma5 = close_1 >= day1['MA5']
            
            # 오늘 장중 시초가 아래로 하락하면서 5일선 지지 테스트
            is_p2_dip = low_0 < open_0 and low_0 <= day0['MA5'] * 1.02
            is_p2_support = close_0 >= day0['MA5']  # 종가 기준 5일선 사수
            
            if is_p2_yang and is_p2_above_ma5 and is_p2_dip and is_p2_support:
                p2_results.append({
                    'code': code, 'name': name, 'close': close_0, 'rate': rate_0, 'ma5': day0['MA5']
                })

            # ----------------------------------------------------
            # [Pattern 3 스캔] - 기간 조정형
            # 1) 최근 4영업일 전에 5%~20% 장대양봉 발생
            # 2) 그 이후 오늘까지 계속해서 거래량이 계단식으로 감소
            # 3) 횡보하는 조정 기간 동안 종가와 저가가 단 한 번도 5일선(MA5)을 깨지 않음
            # 4) 오늘 종가가 5일선 및 10일선 위에 안착하며 매수 급소 형성
            # ----------------------------------------------------
            if len(df) >= 7:
                # 3일전 혹은 4일전에 기준 장대양봉이 있었는지 판단
                yang_idx = -1
                for i in range(-5, -2):
                    c_prev = df.iloc[i-1]['Close']
                    c_curr = df.iloc[i]['Close']
                    o_curr = df.iloc[i]['Open']
                    r = ((c_curr - c_prev) / c_prev) * 100
                    if 5.0 <= r <= 20.0 and c_curr > o_curr:
                        yang_idx = i
                        break
                
                if yang_idx != -1:
                    # 양봉 이후 거래량 감소 여부 체크
                    # 양봉 당일 거래량부터 오늘 거래량까지 감소 추세 확인
                    vol_list = [df.iloc[j]['Volume'] for j in range(yang_idx, 0)]
                    vol_decreasing = True
                    for k in range(len(vol_list)-1):
                        if vol_list[k+1] >= vol_list[k]:  # 거래량이 늘어난 날이 있다면 부적합
                            vol_decreasing = False
                            break
                            
                    # 10일선 위에 안착 (이탈하지 않음, 5일선~10일선 사이의 매수 구간)
                    on_support = close_0 >= day0['MA10'] and low_0 >= day0['MA10'] * 0.995
                    
                    # 횡보하는 조정 기간 동안 종가가 10일선(MA10)을 이탈하지 않았어야 함
                    consolidating_above_ma10 = day1['Close'] >= day1['MA10'] and day2['Close'] >= day2['MA10']
                    
                    if vol_decreasing and on_support and consolidating_above_ma10:
                        p3_results.append({
                            'code': code, 'name': name, 'close': close_0, 'ma5': day0['MA5'], 'ma10': day0['MA10']
                        })
                        
        except Exception as e:
            continue
            
    return p1_results, p2_results, p3_results

if __name__ == "__main__":
    # 시가총액 상위 우량주 250개씩 총 500개 종목을 추출하여 분석
    # (실전 적용 시 top_n=500 등으로 늘려 더 많은 종목을 스캔할 수 있습니다)
    stocks = get_market_list(top_n=250)
    
    p1, p2, p3 = scan_yang_eum_yang(stocks)
    
    print("\n" + "="*60)
    print("★ [Pattern 1] 기본 양음양 패턴 포착 종목 (눌림목 종가매수) ★")
    print("="*60)
    if p1:
        for s in p1:
            print(f"[{s['name']}({s['code']})] 종가: {s['close']:,}원 | 오늘 등락률: {s['rate']:.2f}% | 어제대비 거래량: {s['vol_ratio']:.1f}%")
    else:
        print("조건에 부합하는 종목이 없습니다.")
        
    print("\n" + "="*60)
    print("★ [Pattern 2] 윗꼬리 대량거래 패턴 포착 종목 (시초가 이하 매수) ★")
    print("="*60)
    if p2:
        for s in p2:
            print(f"[{s['name']}({s['code']})] 종가: {s['close']:,}원 | 오늘 등락률: {s['rate']:.2f}% | 5일선: {s['ma5']:.0f}원")
    else:
        print("조건에 부합하는 종목이 없습니다.")

    print("\n" + "="*60)
    print("★ [Pattern 3] 기간 조정 및 거래량 감소 패턴 포착 종목 (다분할 매수) ★")
    print("="*60)
    if p3:
        for s in p3:
            print(f"[{s['name']}({s['code']})] 종가: {s['close']:,}원 | 5일선: {s['ma5']:.0f}원 | 10일선: {s['ma10']:.0f}원")
    else:
        print("조건에 부합하는 종목이 없습니다.")
