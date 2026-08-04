import os
import sys
import pandas as pd
import datetime

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
    """KOSPI, KOSDAQ 전 종목 리스트를 가져옵니다 (약 2,600+ 종목)."""
    print("시장 전 종목 정보를 가져오는 중...")
    try:
        df_kospi = fdr.StockListing('KOSPI')
        df_kosdaq = fdr.StockListing('KOSDAQ')
        
        kospi_list = df_kospi[['Code', 'Name']].to_dict('records')
        kosdaq_list = df_kosdaq[['Code', 'Name']].to_dict('records')
        
        return kospi_list + kosdaq_list
    except Exception as e:
        print(f"시장 종목 정보를 가져오는 데 실패했습니다: {e}")
        return []

def scan_yang_eum_yang_v3(stock_list):
    """
    거래량 증가율로 1차 필터링 후 양음양 패턴을 스캔합니다.
    이 방식은 전 종목(2,600개) 스캔도 수 분 내로 고속 수행할 수 있게 합니다.
    """
    print(f"총 {len(stock_list)}개 종목 대상: [1차 거래량 급증 스캔] 시작...")
    
    p1_results = []
    p2_results = []
    p3_results = []
    
    # 데이터 조회 기간 (최근 30영업일 확보를 위해 45일전부터 조회)
    today = datetime.datetime.today()
    start_date = today - datetime.timedelta(days=45)
    
    # 1차 필터링 기준: 최근 5영업일 중 최소 1회 이상 평소 거래량의 500% 이상 급증한 이력이 있는가?
    scanned_count = 0
    match_stage1_count = 0
    
    for stock in stock_list:
        code = stock['Code']
        name = stock['Name']
        
        try:
            # 주가 데이터 가져오기
            df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'))
            scanned_count += 1
            
            if len(df) < 25:  # 최소 20일 이동평균을 구할 수 있는 데이터 필요
                continue
                
            # 거래량 및 이평선 계산
            df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()  # 20일 평균 거래량
            df['MA5'] = df['Close'].rolling(window=5).mean()
            df['MA10'] = df['Close'].rolling(window=10).mean()
            
            # 최근 5영업일 동안 거래량이 20일 평균 거래량 대비 500% 이상 증가한 적이 있는지 1차 검사
            # (양음양 기법의 기본 전제는 '세력 유입 = 거래량 폭발'이기 때문)
            recent_5_days = df.iloc[-5:]
            volume_spike_detected = False
            for idx in range(len(recent_5_days)):
                day_data = recent_5_days.iloc[idx]
                if day_data['Volume'] >= day_data['Vol_MA20'] * 5.0:  # 500% 이상 증가율 (5배)
                    volume_spike_detected = True
                    break
            
            if not volume_spike_detected:
                # 1차 필터링 탈락: 최근 5일간 대량 거래가 없는 종목은 즉시 패스
                continue
                
            match_stage1_count += 1
            
            # ----------------------------------------------------
            # 2차 세부 분석 (양음양 패턴 조건 검증)
            # ----------------------------------------------------
            day0 = df.iloc[-1]
            day1 = df.iloc[-2]
            day2 = df.iloc[-3]
            
            close_0, open_0, high_0, low_0, vol_0 = day0['Close'], day0['Open'], day0['High'], day0['Low'], day0['Volume']
            close_1, open_1, high_1, low_1, vol_1 = day1['Close'], day1['Open'], day1['High'], day1['Low'], day1['Volume']
            
            rate_1 = ((close_1 - day2['Close']) / day2['Close']) * 100
            rate_0 = ((close_0 - close_1) / close_1) * 100
            
            # 동전주 제외
            if close_0 < 1000:
                continue

            # ----------------------------------------------------
            # [Pattern 1 스캔]
            # ----------------------------------------------------
            is_p1_yang = 5.0 <= rate_1 <= 20.0 and close_1 > open_1
            is_p1_eum = close_0 < open_0 and vol_0 <= vol_1 * 0.60
            is_p1_support = close_0 >= day0['MA5'] and low_0 >= day0['MA5'] * 0.995
            is_p1_gap_ok = close_0 <= day0['MA5'] * 1.05
            
            if is_p1_yang and is_p1_eum and is_p1_support and is_p1_gap_ok:
                p1_results.append({
                    'code': code, 'name': name, 'close': close_0, 'rate': rate_0,
                    'vol_ratio': (vol_0 / vol_1) * 100, 'ma5': day0['MA5']
                })
                
            # ----------------------------------------------------
            # [Pattern 2 스캔]
            # ----------------------------------------------------
            body_1 = abs(close_1 - open_1)
            tail_1 = high_1 - max(close_1, open_1)
            
            is_p2_yang = tail_1 >= body_1 * 0.8 and close_1 > open_1 and vol_1 >= day1['Vol_MA20'] * 5.0
            is_p2_above_ma5 = close_1 >= day1['MA5']
            is_p2_dip = low_0 < open_0 and low_0 <= day0['MA5'] * 1.02
            is_p2_support = close_0 >= day0['MA5']
            
            if is_p2_yang and is_p2_above_ma5 and is_p2_dip and is_p2_support:
                p2_results.append({
                    'code': code, 'name': name, 'close': close_0, 'rate': rate_0, 'ma5': day0['MA5']
                })

            # ----------------------------------------------------
            # [Pattern 3 스캔]
            # ----------------------------------------------------
            if len(df) >= 7:
                # 3일전 혹은 4일전에 기준 장대양봉이 있었는지
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
                    vol_list = [df.iloc[j]['Volume'] for j in range(yang_idx, 0)]
                    vol_decreasing = True
                    for k in range(len(vol_list)-1):
                        if vol_list[k+1] >= vol_list[k]:
                            vol_decreasing = False
                            break
                            
                    on_support = close_0 >= day0['MA10'] and low_0 >= day0['MA10'] * 0.995
                    consolidating_above_ma10 = day1['Close'] >= day1['MA10'] and day2['Close'] >= day2['MA10']
                    
                    if vol_decreasing and on_support and consolidating_above_ma10:
                        p3_results.append({
                            'code': code, 'name': name, 'close': close_0, 'ma5': day0['MA5'], 'ma10': day0['MA10']
                        })
                        
        except Exception as e:
            continue
            
    print(f"\n[스캔 요약] 전체 {scanned_count}개 중 1차 거래량 증가율 필터 통과: {match_stage1_count}개 종목")
    return p1_results, p2_results, p3_results

if __name__ == "__main__":
    # KOSPI 및 KOSDAQ 전 종목 대상 고속 스캔 실행
    stocks = get_full_market_list()
    
    p1, p2, p3 = scan_yang_eum_yang_v3(stocks)
    
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
