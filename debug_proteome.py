# -*- coding: utf-8 -*-
import datetime
import os
import json
import FinanceDataReader as fdr

def debug_proteome():
    code = '303360' # 프로티아
    name = '프로티아'
    target_date = datetime.datetime(2026, 7, 16)
    long_start = target_date - datetime.timedelta(days=220)
    
    print(f"=== 프로티아 ({code}) 디버깅 ===")
    
    try:
        df = fdr.DataReader(code, long_start.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
        if len(df) < 140:
            print("실패: 데이터 길이 부족")
            return
            
        df['MA5'] = df['Close'].rolling(5).mean()
        df['MA10'] = df['Close'].rolling(10).mean()
        df['MA13'] = df['Close'].rolling(13).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        df['MA120'] = df['Close'].rolling(120).mean()
        df['Vol_MA20'] = df['Volume'].rolling(20).mean()
        
        close_curr = df['Close'].iloc[-1]
        open_curr = df['Open'].iloc[-1]
        high_curr = df['High'].iloc[-1]
        low_curr = df['Low'].iloc[-1]
        
        ma5_curr = df['MA5'].iloc[-1]
        ma10_curr = df['MA10'].iloc[-1]
        ma13_curr = df['MA13'].iloc[-1]
        ma20_curr = df['MA20'].iloc[-1]
        ma60_curr = df['MA60'].iloc[-1]
        ma120_curr = df['MA120'].iloc[-1]
        vol_ma20_curr = df['Vol_MA20'].iloc[-1]
        volume_curr = df['Volume'].iloc[-1]
        
        # 1. 20일선 이격 8% 이내 1단계 필터 검사
        diff_ma20 = abs(close_curr - ma20_curr) / ma20_curr
        print(f"1단계 20일선 이격: 종가={close_curr:,}원, 20MA={ma20_curr:.1f}원, 이격률={diff_ma20*100:.2f}% (기준: 8% 이내)")
        
        # 2. 주가 위에 120일선이나 60일선이 존재하는지 검사
        is_overhead = ma120_curr > close_curr or ma60_curr > close_curr
        print(f"2단계 오버헤드 체크: 60MA={ma60_curr:.1f}원, 120MA={ma120_curr:.1f}원, 종가={close_curr:,}원 -> 오버헤드 여부: {is_overhead}")
        
        # 3. 120일선, 60일선 우하향/횡보 흐름
        ma120_trend_val = df['MA120'].iloc[-11]
        ma60_trend_val = df['MA60'].iloc[-11]
        is_ma120_down_or_flat = ma120_curr <= ma120_trend_val * 1.015
        is_ma60_down_or_flat = ma60_curr <= ma60_trend_val * 1.015
        print(f"3단계 이평선 추세 체크:")
        print(f" - 120MA 오늘={ma120_curr:.1f}원, 10일전={ma120_trend_val:.1f}원 -> {is_ma120_down_or_flat}")
        print(f" - 60MA 오늘={ma60_curr:.1f}원, 10일전={ma60_trend_val:.1f}원 -> {is_ma60_down_or_flat}")
        
        # 4. 반등 조건
        is_ma5_up = ma5_curr > df['MA5'].iloc[-2]
        is_ma20_up = ma20_curr > df['MA20'].iloc[-2]
        is_rebound_yang = close_curr > open_curr
        print(f"4단계 반등 조건 체크:")
        print(f" - 5MA 우상향: {is_ma5_up}, 20MA 우상향: {is_ma20_up}, 오늘 양봉: {is_rebound_yang}")
        
        # 5. 전저점 지지 체크
        local_min_20 = df['Low'].iloc[-21:-1].min()
        is_near_prev_low = local_min_20 * 0.98 <= close_curr <= local_min_20 * 1.04
        print(f"5단계 전저점 지지 체크: 20일 전저점={local_min_20:,}원, 범위={local_min_20*0.98:.1f}~{local_min_20*1.04:.1f} -> {is_near_prev_low}")
        
        # 6. 패턴 1 터치 체크 (최근 21일)
        print(f"\n[패턴 1 (120선 저항 터치) 세부 데이터 분석 (최근 21일)]")
        has_touch_120 = False
        for idx in range(2, 23):
            row = df.iloc[-idx]
            high_val = row['High']
            close_val = row['Close']
            open_val = row['Open']
            body = abs(close_val - open_val)
            tail = high_val - max(close_val, open_val)
            ma120_val = df['MA120'].iloc[-idx]
            vol_ma20_val = df['Vol_MA20'].iloc[-idx]
            vol_ratio = row['Volume'] / vol_ma20_val if vol_ma20_val > 0 else 0
            
            is_touch = high_val >= ma120_val * 0.975
            is_vol = row['Volume'] >= vol_ma20_val * 1.5
            is_tail = tail >= body * 0.30
            
            tail_ratio_str = f"{tail/body:.2f}" if body > 0 else "9.9"
            if is_touch or is_vol:
                print(f" - D-{idx-1} ({df.index[-idx].strftime('%m-%d')}): 고가={high_val:,}원, 120MA={ma120_val:.1f}원 (터치: {is_touch}), 거래량={row['Volume']:,} ({vol_ratio:.1f}배) (거래량합격: {is_vol}), 윗꼬리비율={tail_ratio_str} (윗꼬리합격: {is_tail})")
                if is_touch and is_vol and is_tail:
                    has_touch_120 = True
                    print(f"   => ★ D-{idx-1}에 120선 터치 조건 충족!")
                    
        is_supported_p1 = (ma20_curr * 0.97 <= close_curr <= ma20_curr * 1.05) or (ma60_curr * 0.97 <= close_curr <= ma60_curr * 1.05) or (ma10_curr * 0.97 <= close_curr <= ma10_curr * 1.05) or is_near_prev_low
        print(f"패턴 1 결과: 터치={has_touch_120}, 지지={is_supported_p1}")
        
        # 7. 패턴 2 터치 체크 (최근 21일)
        print(f"\n[패턴 2 (60선 저항 터치) 세부 데이터 분석 (최근 21일)]")
        has_touch_60 = False
        for idx in range(2, 23):
            row = df.iloc[-idx]
            high_val = row['High']
            close_val = row['Close']
            open_val = row['Open']
            body = abs(close_val - open_val)
            tail = high_val - max(close_val, open_val)
            ma60_val = df['MA60'].iloc[-idx]
            vol_ma20_val = df['Vol_MA20'].iloc[-idx]
            vol_ratio = row['Volume'] / vol_ma20_val if vol_ma20_val > 0 else 0
            
            is_touch = high_val >= ma60_val * 0.975
            is_vol = row['Volume'] >= vol_ma20_val * 1.5
            is_tail = tail >= body * 0.30
            
            tail_ratio_str = f"{tail/body:.2f}" if body > 0 else "9.9"
            if is_touch or is_vol:
                print(f" - D-{idx-1} ({df.index[-idx].strftime('%m-%d')}): 고가={high_val:,}원, 60MA={ma60_val:.1f}원 (터치: {is_touch}), 거래량={row['Volume']:,} ({vol_ratio:.1f}배) (거래량합격: {is_vol}), 윗꼬리비율={tail_ratio_str} (윗꼬리합격: {is_tail})")
                if is_touch and is_vol and is_tail:
                    has_touch_60 = True
                    print(f"   => ★ D-{idx-1}에 60선 터치 조건 충족!")
                    
        is_supported_p2 = (ma13_curr * 0.97 <= close_curr <= ma13_curr * 1.05) or (ma20_curr * 0.97 <= close_curr <= ma20_curr * 1.05) or (ma10_curr * 0.97 <= close_curr <= ma10_curr * 1.05) or is_near_prev_low
        print(f"패턴 2 결과: 터치={has_touch_60}, 지지={is_supported_p2}")
        
    except Exception as e:
        print("디버그 중 에러 발생:", e)

if __name__ == '__main__':
    debug_proteome()
