# -*- coding: utf-8 -*-
import os
import sys
import datetime
import pandas as pd
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
import utils_recent_scan as urs
def get_full_market_list():
    """KOSPI, KOSDAQ 전 종목 리스트를 가져옵니다 (우선주, ETF, SPAC 등 제외)."""
    print("시장 전 종목 정보를 가져오는 중...")
    try:
        df_kospi = fdr.StockListing('KOSPI')
        df_kosdaq = fdr.StockListing('KOSDAQ')
        
        exclude_keywords = ['우B', '우C', '스팩', '리츠', '레버리지', '인버스', 'ETN', 'ETF', '하이브리드']
        def is_excluded(name):
            return name.endswith('우') or any(kw in name for kw in exclude_keywords)

        stocks = []
        for s in df_kospi[['Code', 'Name']].to_dict('records'):
            if not is_excluded(s['Name']): 
                stocks.append(s)
        for s in df_kosdaq[['Code', 'Name']].to_dict('records'):
            if not is_excluded(s['Name']): 
                stocks.append(s)
                
        return stocks
    except Exception as e:
        print(f"시장 종목 정보 가져오기 실패: {e}")
        return []

def get_prefiltered_market_list(threshold_billion=150, change_pct_min=3.0):
    """
    StockListing에서 당일 거래대금·등락률로 1차 필터링 후 소수 종목만 반환합니다.
    - threshold_billion: 최소 거래대금 기준 (억원). 150억 이상이면 500억봉 후보도 포함.
    - change_pct_min: 최소 등락률 (%). 당일 급등(3% 이상)한 종목만 집중 분석.
    이 함수로 2,500개 종목을 보통 50~200개로 대폭 압축합니다.
    """
    print("[사전 필터링] 거래대금 + 등락률 기준으로 후보 종목 압축 중...")
    try:
        df_kospi = fdr.StockListing('KOSPI')
        df_kosdaq = fdr.StockListing('KOSDAQ')
        df_all = pd.concat([df_kospi, df_kosdaq], ignore_index=True)

        exclude_keywords = ['우B', '우C', '스팩', '리츠', '레버리지', '인버스', 'ETN', 'ETF', '하이브리드']
        def is_excluded(name):
            if not isinstance(name, str):
                return True
            return name.endswith('우') or any(kw in name for kw in exclude_keywords)

        # 기본 필터: 이름 기반 제외
        df_all = df_all[~df_all['Name'].apply(is_excluded)].copy()

        # 거래대금 필터: Marcap(시가총액)이 없으면 Volume * Close 사용
        # StockListing에 'Marcap', 'Volume', 'Close' 등의 컬럼이 있을 수 있음
        # 거래대금 = Volume * Close
        volume_col = None
        close_col = None
        change_col = None
        for c in df_all.columns:
            cl = c.lower()
            if 'volume' in cl or cl == 'vol':
                volume_col = c
            if cl in ('close', 'price', 'lastsale'):
                close_col = c
            if 'change' in cl:
                change_col = c

        filtered = []
        for _, row in df_all.iterrows():
            code = str(row.get('Code', ''))
            name = str(row.get('Name', ''))
            # 거래대금 계산
            amt = 0
            if volume_col and close_col:
                try:
                    amt = float(row[volume_col]) * float(row[close_col])
                except Exception:
                    amt = 0
            # 등락률
            chg = 0.0
            if change_col:
                try:
                    val = float(row[change_col])
                    # FinanceDataReader는 Change를 소수(0.05 = 5%)로 줄 수 있음
                    chg = val * 100 if abs(val) < 1 else val
                except Exception:
                    chg = 0.0

            if amt >= threshold_billion * 1e8 and chg >= change_pct_min:
                filtered.append({'Code': code, 'Name': name})

        print(f"[사전 필터링 완료] 전체 {len(df_all)}개 → 후보 {len(filtered)}개 (거래대금 {threshold_billion}억↑, 등락률 +{change_pct_min}%↑)")

        # 필터 결과가 너무 적으면 (5개 미만) 거래대금만으로 재시도
        if len(filtered) < 5:
            print("[사전 필터링] 결과가 너무 적어 등락률 필터 해제 후 재시도...")
            filtered = []
            for _, row in df_all.iterrows():
                code = str(row.get('Code', ''))
                name = str(row.get('Name', ''))
                amt = 0
                if volume_col and close_col:
                    try:
                        amt = float(row[volume_col]) * float(row[close_col])
                    except Exception:
                        amt = 0
                if amt >= threshold_billion * 1e8:
                    filtered.append({'Code': code, 'Name': name})
            print(f"[재필터링 완료] 후보 {len(filtered)}개")

        return filtered
    except Exception as e:
        print(f"사전 필터링 실패 ({e}), 전체 종목 리스트로 폴백합니다.")
        return get_full_market_list()

def check_standard_candle(df, idx, threshold_billion):
    """
    특정 행(idx)이 150억/500억 기준봉 조건에 맞는지 확인합니다.
    조건:
    1. 거래대금 >= threshold_billion (억원)
    2. 종가 >= 시가 * 1.09
    3. 고가 >= 전일종가 * 1.15
    4. 고가 >= 저가 * 1.15
    """
    if idx <= 0 or idx >= len(df):
        return False
        
    row = df.iloc[idx]
    row_prev = df.iloc[idx - 1]
    
    close_val = row['Close']
    open_val = row['Open']
    high_val = row['High']
    low_val = row['Low']
    volume_val = row['Volume']
    
    # 1. 거래대금 (종가 * 거래량)
    amt = close_val * volume_val
    expected_amt = threshold_billion * 100_000_000
    if amt < expected_amt:
        return False
        
    # 2. 종가 >= 시가 * 1.09 (9% 이상 상승)
    if close_val < open_val * 1.09:
        return False
        
    # 3. 고가 >= 전일종가 * 1.15 (15% 이상 상승)
    if high_val < row_prev['Close'] * 1.15:
        return False
        
    # 4. 고가 >= 저가 * 1.15 (당일 고저 변동성 15% 이상)
    if high_val < low_val * 1.15:
        return False
        
    return True

def analyze_single_stock(stock, target_date, threshold_billion=500):
    """
    개별 종목 데이터를 분석하여 0일차, 1일차, 2일차 조건 충족 여부를 확인하고 팩트 데이터를 연산합니다.
    """
    code = stock['Code']
    name = stock['Name']
    
    # 이평선 및 전고점 계산을 위해 충분한 130거래일치 데이터 수집
    start_date = target_date - datetime.timedelta(days=220)
    
    try:
        df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
        if len(df) < 80: # 최소 80거래일 확보
            return None
            
        # target_date가 데이터프레임의 마지막에 있는지 확인
        target_date_only = target_date.date() if hasattr(target_date, 'date') else target_date
        last_date = df.index[-1].to_pydatetime().date()
        if last_date != target_date_only:
            # 공휴일이나 주말의 경우 target_date 당일 거래가 없을 수 있음
            return None
            
        # 0~15일차 중 기준봉이 존재하는지 역순 탐색
        day_type = None
        ref_idx = None
        
        # 0일차: 당일(오늘)
        if check_standard_candle(df, len(df)-1, threshold_billion):
            day_type = 0
            ref_idx = len(df)-1
        else:
            # 1일차부터 15일차까지 역순 탐색
            for i in range(1, 16):
                idx = len(df) - 1 - i
                if idx >= 0 and check_standard_candle(df, idx, threshold_billion):
                    if i == 1:
                        # 1일차 거래량 감소 필터
                        if df['Volume'].iloc[-1] < df['Volume'].iloc[idx]:
                            day_type = i
                            ref_idx = idx
                            break
                    elif i == 2:
                        # 2일차 거래량 감소 필터
                        if df['Volume'].iloc[-1] < df['Volume'].iloc[idx]:
                            day_type = i
                            ref_idx = idx
                            break
                    else:
                        # 3~15일차 중기 조정 후보 등록 (최종 지지선 필터는 아래에서 수행)
                        day_type = i
                        ref_idx = idx
                        break
            
        if day_type is None:
            return None
            
        # 팩트 데이터 추출
        row_today = df.iloc[-1]
        close_curr = int(row_today['Close'])
        low_curr = int(row_today['Low'])
        
        # 오늘 거래량 증가율 (20일 평균 거래량 대비 오늘 거래량의 백분율)
        vol_ma20 = df['Volume'].rolling(window=20).mean().iloc[-1]
        vol_curr = row_today['Volume']
        vol_ratio = (vol_curr / vol_ma20) * 100 if vol_ma20 > 0 else 100.0
        
        # 기준봉 거래량 대비 오늘 거래량 비율
        vol_ref = df['Volume'].iloc[ref_idx]
        vol_change_ratio = (vol_curr / vol_ref) * 100 if vol_ref > 0 else 100.0
        
        # 오늘 기준 실제 이평선 값들
        actual_ma3 = df['Close'].rolling(window=3).mean().iloc[-1]
        actual_ma5 = df['Close'].rolling(window=5).mean().iloc[-1]
        actual_ma8 = df['Close'].rolling(window=8).mean().iloc[-1]
        actual_ma15 = df['Close'].rolling(window=15).mean().iloc[-1]
        actual_ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
        
        # 내일 예상 이평선 가격 (D+6일 전 종가 탈락 & 오늘 종가 2회 계산 수식)
        # 내일 예상 가격 = (오늘 종가 * 2 + D-1 + ... + D-(N-2)) / N
        ma3_exp = (close_curr * 2 + df['Close'].iloc[-2]) / 3
        ma5_exp = (close_curr * 2 + sum(df['Close'].iloc[-4:-1])) / 5
        ma8_exp = (close_curr * 2 + sum(df['Close'].iloc[-7:-1])) / 8
        ma15_exp = (close_curr * 2 + sum(df['Close'].iloc[-14:-1])) / 15
        ma20_exp = (close_curr * 2 + sum(df['Close'].iloc[-19:-1])) / 20
        
        # 예상 이평선의 우상향/우하향 방향성 (내일 예상가 vs 오늘 실제가 비교)
        ma3_trend = "우상향" if ma3_exp > actual_ma3 else "우하향"
        ma5_trend = "우상향" if ma5_exp > actual_ma5 else "우하향"
        ma8_trend = "우상향" if ma8_exp > actual_ma8 else "우하향"
        ma15_trend = "우상향" if ma15_exp > actual_ma15 else "우하향"
        ma20_trend = "우상향" if ma20_exp > actual_ma20 else "우하향"
        
        # 15일선/20일선 지지 조건 체크
        near_ma15 = False
        near_ma20 = False
        
        if 0.975 * actual_ma15 <= close_curr <= 1.025 * actual_ma15 or 0.975 * actual_ma15 <= low_curr <= 1.025 * actual_ma15:
            near_ma15 = True
        if 0.975 * actual_ma20 <= close_curr <= 1.025 * actual_ma20 or 0.975 * actual_ma20 <= low_curr <= 1.025 * actual_ma20:
            near_ma20 = True
            
        # 3일차 이상 중기 조정은 15일선 또는 20일선 부근에 위치해야 함
        if day_type >= 3:
            if not (near_ma15 or near_ma20):
                return None
        
        # 정배열/역배열 판단 (3일선 > 5일선 > 20일선 정배열 여부)
        is_bullish_alignment = actual_ma3 > actual_ma5 > actual_ma20
        
        # 갭상승 조정 vs 갭하락 조정 판별 (기준봉 다음날 시가가 갭상승 출발했는지)
        is_gap_up = False
        if day_type in [1, 2] and ref_idx + 1 < len(df):
            ref_close = df['Close'].iloc[ref_idx]
            next_open = df['Open'].iloc[ref_idx + 1]
            is_gap_up = next_open > ref_close
            
        # 3일선과 5일선의 이격도
        ma3_ma5_disparity = abs(actual_ma3 - actual_ma5) / actual_ma5 * 100 if actual_ma5 > 0 else 0.0
        
        # 3일선 반등 약세 여부 (2일차 종목의 경우, 1일차에 반등이 약했는지 체크해 8일선 반등 기대도 산정)
        has_weak_ma3_rebound = False
        if day_type == 2 and len(df) >= 3:
            prev_close = df['Close'].iloc[-3]
            yesterday_high = df['High'].iloc[-2]
            yesterday_rebound = ((yesterday_high - prev_close) / prev_close) * 100
            has_weak_ma3_rebound = yesterday_rebound < 3.5
            
        # 직전 전고점 가격대 연산 (기준봉 발생일 이전 20~60거래일 동안의 최고가, 고가 기준)
        start_idx = max(0, ref_idx - 60)
        end_idx = max(0, ref_idx - 1)
        if start_idx < end_idx:
            former_peak = int(df['High'].iloc[start_idx:end_idx].max())
        else:
            former_peak = int(df['High'].iloc[:ref_idx].max()) if ref_idx > 0 else close_curr
            
        ref_date_str = df.index[ref_idx].strftime('%Y-%m-%d')
        rate_today = float(((close_curr - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100) if len(df) >= 2 else 0.0

        # ── 거래량 추세 분석 ──────────────────────────────────────
        vol_ma5_curr = df['Volume'].rolling(window=5).mean().iloc[-1]
        vol_trend_up = bool(vol_ma5_curr > vol_ma20)  # 단기 거래량 평균이 장기보다 높으면 증가추세
        # 기준봉 이후 조정 중 거래량 감소(건전) 여부
        if day_type >= 1 and ref_idx + 1 < len(df):
            post_ref_vols = df['Volume'].iloc[ref_idx + 1:]
            post_ref_avg = post_ref_vols.mean() if len(post_ref_vols) > 0 else vol_curr
            vol_drying_ok = bool(post_ref_avg < vol_ref * 0.6)  # 기준봉의 60% 이하면 건전한 감소
        else:
            vol_drying_ok = False

        # ── 수평지지 레벨 (최근 40거래일 스윙 로우) ────────────────
        recent_40 = df.tail(40)
        swing_lows = []
        for i in range(2, len(recent_40) - 2):
            lows = recent_40['Low'].values
            if lows[i] < lows[i-1] and lows[i] < lows[i+1] and lows[i] < lows[i-2] and lows[i] < lows[i+2]:
                swing_lows.append(float(lows[i]))
        # 현재가 아래 지지선 후보 (가까운 순 최대 3개)
        h_supports = sorted([s for s in swing_lows if s < close_curr * 1.01], reverse=True)[:3]

        # ── 사선지지 (추세선): 최근 스윙 로우 2개를 연결한 직선 ────
        trendline_support = None
        swing_low_indices = []
        for i in range(2, len(recent_40) - 2):
            lows = recent_40['Low'].values
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                swing_low_indices.append((i, float(lows[i])))
        if len(swing_low_indices) >= 2:
            i1, p1 = swing_low_indices[-2]
            i2, p2 = swing_low_indices[-1]
            if i2 > i1 and p2 > p1:  # 우상향 추세선만
                slope = (p2 - p1) / (i2 - i1)
                # 오늘(마지막 봉) 위치에서의 추세선 값
                days_from_i2 = len(recent_40) - 1 - i2
                trendline_today = p2 + slope * days_from_i2
                trendline_support = float(round(trendline_today))

        return {
            'code': code,
            'name': name,
            'day_type': day_type,
            'close': close_curr,
            'rate': rate_today,
            'low': low_curr,
            'vol_ratio': float(vol_ratio),
            'vol_change_ratio': float(vol_change_ratio),
            'vol_trend_up': vol_trend_up,
            'vol_drying_ok': vol_drying_ok,
            'h_supports': h_supports,
            'trendline_support': trendline_support,
            'is_bullish_alignment': bool(is_bullish_alignment),
            'is_gap_up': bool(is_gap_up),
            'ma3_ma5_disparity': float(ma3_ma5_disparity),
            'has_weak_ma3_rebound': bool(has_weak_ma3_rebound),
            'expected_ma': {
                'ma3': float(ma3_exp), 'ma3_trend': ma3_trend,
                'ma5': float(ma5_exp), 'ma5_trend': ma5_trend,
                'ma8': float(ma8_exp), 'ma8_trend': ma8_trend,
                'ma20': float(ma20_exp), 'ma20_trend': ma20_trend
            },
            'former_peak': former_peak,
            'ref_date': ref_date_str
        }

    except Exception as e:
        # 에러 출력 디버깅용 주석 해제 가능
        # print(f"Error analyzing {name} ({code}): {e}")
        pass
    return None

def scan_stocks_parallel(stock_list, target_date, threshold_billion=500, max_workers=40):
    """ThreadPoolExecutor를 사용하여 시장 종목들을 병렬로 고속 스캔합니다."""
    print(f"[{target_date.strftime('%Y-%m-%d')}] {threshold_billion}억 봉 기법 스캔 시작...")
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze_single_stock, s, target_date, threshold_billion): s for s in stock_list}
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if completed % 300 == 0:
                print(f"스캔 진행 중: {completed}/{len(stock_list)} 종목 검사 완료...")
            
            res = future.result()
            if res:
                results.append(res)
                
    # 0, 1, 2일차 순서대로 정렬
    results.sort(key=lambda x: (x['day_type'], -x['vol_ratio']))
    print(f"스캔 최종 포착 완료: {len(results)}개 종목 포착.")
    return results

if __name__ == "__main__":
    # 단순 로컬 테스트용
    target_dt = datetime.datetime(2026, 7, 14)
    stock_list = get_full_market_list()
    res = scan_stocks_parallel(stock_list[:100], target_dt, threshold_billion=150, max_workers=20)
    print(res)
