# -*- coding: utf-8 -*-
import datetime
import json
import FinanceDataReader as fdr

target_date = datetime.datetime(2026, 7, 10)
date_str = target_date.strftime('%Y-%m-%d')
short_start = target_date - datetime.timedelta(days=20)
long_start = target_date - datetime.timedelta(days=220)

codes = {
    '237880': '클리오',
    '214330': '금호에이치티',
    '477850': '마니커에프앤지',
    '214150': '클래시스',
    '006040': '한창산업',
    '049480': '오픈베이스',
    '439090': '마녀공장',
    '001790': '대한제당',
    '008930': '한미사이언스',
    '358570': '지아이이노베이션'
}

def analyze_stock(code, name):
    print(f"\n==========================================")
    print(f"★ [{name} ({code})] 분석 시작")
    
    # 1. 1단계 필터링 (가벼운 필터) 검증
    try:
        df = fdr.DataReader(code, short_start.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
        if len(df) < 5:
            print("1단계 실패: 데이터 행 수가 5 미만입니다.")
            return
            
        last_date = df.index[-1].to_pydatetime().date()
        if last_date != target_date.date():
            print(f"1단계 실패: 마지막 데이터 날짜({last_date})가 타겟일({target_date.date()})과 다릅니다.")
            return
            
        has_breakout = False
        breakout_details = []
        for i in range(-5, 0):
            if i-1 < -len(df): continue
            c_prev = df.iloc[i-1]['Close']
            c_curr = df.iloc[i]['Close']
            o_curr = df.iloc[i]['Open']
            r = ((c_curr - c_prev) / c_prev) * 100
            amt = c_curr * df.iloc[i]['Volume']
            
            # 기준: 등락률 4%~22% 양봉 + 거래대금 15억 이상
            cond_r = 4.0 <= r <= 22.0
            cond_o = c_curr > o_curr
            cond_amt = amt >= 1_500_000_000
            
            detail = f"일자={df.index[i].strftime('%m-%d')} 등락률={r:+.2f}%(조건:{cond_r}) 양봉={cond_o}(조건:{cond_o}) 거래대금={amt/1e9:.2f}억(조건:{cond_amt})"
            breakout_details.append(detail)
            
            if cond_r and cond_o and cond_amt:
                has_breakout = True
                
        print("1단계(최근 5일 내 기준봉 존재 여부):")
        for d in breakout_details:
            print("  -", d)
        print("1단계 결과:", "통과" if has_breakout else "탈락 (최근 5영업일 내 기준봉 수급 조건 미충족)")
        
        if not has_breakout:
            return
            
    except Exception as e:
        print("1단계 오류:", e)
        return
        
    # 2. 2단계 정밀 분석 검증
    try:
        df_long = fdr.DataReader(code, long_start.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
        if len(df_long) < 125:
            print(f"2단계 실패: 전체 데이터 수({len(df_long)})가 125 미만입니다.")
            return
            
        df_long['Vol_MA20'] = df_long['Volume'].rolling(20).mean()
        df_long['MA5'] = df_long['Close'].rolling(5).mean()
        df_long['MA10'] = df_long['Close'].rolling(10).mean()
        df_long['MA60'] = df_long['Close'].rolling(60).mean()
        df_long['MA120'] = df_long['Close'].rolling(120).mean()
        
        day0 = df_long.iloc[-1]
        day1 = df_long.iloc[-2]
        day2 = df_long.iloc[-3]
        
        close_0, open_0, high_0, low_0, vol_0 = day0['Close'], day0['Open'], day0['High'], day0['Low'], day0['Volume']
        close_1, open_1, high_1, low_1, vol_1 = day1['Close'], day1['Open'], day1['High'], day1['Low'], day1['Volume']
        
        rate_1 = ((close_1 - day2['Close']) / day2['Close']) * 100
        rate_0 = ((close_0 - close_1) / close_1) * 100
        
        # Pattern 1 (기본형)
        is_p1_yang = 4.0 <= rate_1 <= 22.0 and close_1 > open_1
        is_p1_pred = is_p1_yang and (close_0 < open_0) and (vol_0 <= vol_1 * 0.7) and (close_0 >= day0['MA10'] * 0.99)
        
        # Pattern 2 (윗꼬리)
        body_1 = abs(close_1 - open_1)
        tail_1 = high_1 - max(close_1, open_1)
        is_p2_yang = tail_1 >= body_1 * 0.75 and close_1 > open_1 and vol_1 >= day1['Vol_MA20'] * 1.5
        is_p2_pred = is_p2_yang and (low_0 <= day0['MA5'] * 1.025) and (close_0 <= open_0 * 1.03) and (vol_0 <= vol_1 * 0.8)
        
        # 60일의 법칙
        near_ma60 = (day0['MA60'] * 0.965 <= close_0 <= day0['MA60'] * 1.05) or (day0['MA60'] * 0.965 <= low_0 <= day0['MA60'] * 1.05)
        near_ma120 = (day0['MA120'] * 0.965 <= close_0 <= day0['MA120'] * 1.05) or (day0['MA120'] * 0.965 <= low_0 <= day0['MA120'] * 1.05)
        is_60ma_law = (near_ma60 or near_ma120) and (close_0 < open_0) and (vol_0 <= day0['Vol_MA20'] * 0.8)
        
        print("\n2단계 정밀 지표:")
        print(f"  - 오늘 종가={close_0:,.0f}원, 시가={open_0:,.0f}원, 고가={high_0:,.0f}원, 저가={low_0:,.0f}원, 거래량={vol_0:,}")
        print(f"  - 어제 종가={close_1:,.0f}원, 시가={open_1:,.0f}원, 고가={high_1:,.0f}원, 저가={low_1:,.0f}원, 거래량={vol_1:,}")
        print(f"  - 이평선: MA5={day0['MA5']:.1f}, MA10={day0['MA10']:.1f}, MA60={day0['MA60']:.1f}, MA120={day0['MA120']:.1f}")
        print(f"  - Vol_MA20={day0['Vol_MA20']:.1f}")
        
        print("\n패턴 부합성 검증:")
        print(f"  [Pattern 1 (양음양 기본형)]")
        print(f"    * 어제 4%~22% 장대양봉 여부: {is_p1_yang} (어제 등락률={rate_1:+.2f}%)")
        print(f"    * 오늘 음봉 여부 (close < open): {close_0 < open_0}")
        print(f"    * 오늘 거래량 <= 어제 거래량 * 70% 여부: {vol_0 <= vol_1 * 0.7} (비율={vol_0/vol_1*100:.1f}%)")
        print(f"    * 오늘 종가 >= 10일선 지지 여부: {close_0 >= day0['MA10']*0.99} (종가={close_0}, 10일선기준={day0['MA10']*0.99:.1f})")
        print(f"    => 최종 Pattern 1 매칭 결과: {is_p1_pred}")
        
        print(f"  [Pattern 2 (윗꼬리 패턴)]")
        print(f"    * 어제 윗꼬리 장대양봉 여부: {is_p2_yang} (윗꼬리={tail_1}, 몸통={body_1})")
        print(f"    * 오늘 저가 <= 5일선*1.025 지지 여부: {low_0 <= day0['MA5']*1.025}")
        print(f"    * 오늘 종가 <= 시가*1.03 여부: {close_0 <= open_0 * 1.03}")
        print(f"    * 오늘 거래량 <= 어제 거래량 * 80% 여부: {vol_0 <= vol_1 * 0.8}")
        print(f"    => 최종 Pattern 2 매칭 결과: {is_p2_pred}")
        
        print(f"  [60일선/120일선의 법칙]")
        print(f"    * 60일선 인근 여부: {near_ma60} (종가대비비율={close_0/day0['MA60']*100:.1f}%)")
        print(f"    * 120일선 인근 여부: {near_ma120}")
        print(f"    * 오늘 음봉 여부: {close_0 < open_0}")
        print(f"    * 오늘 거래량 <= 20일 평균의 80% 여부: {vol_0 <= day0['Vol_MA20'] * 0.8} (오늘={vol_0}, 20일평균80%={day0['Vol_MA20']*0.8:.1f})")
        print(f"    => 최종 60일의법칙 매칭 결과: {is_60ma_law}")
        
    except Exception as e:
        print("2단계 오류:", e)
        
for code, name in codes.items():
    analyze_stock(code, name)
