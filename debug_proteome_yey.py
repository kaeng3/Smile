# -*- coding: utf-8 -*-
import datetime
import FinanceDataReader as fdr

def debug_proteome_yey():
    code = '303360' # 프로티아
    target_date = datetime.datetime(2026, 7, 16)
    long_start = target_date - datetime.timedelta(days=220)
    
    print(f"=== 프로티아 ({code}) 양음양 조건 정밀 디버깅 (기준일: {target_date.strftime('%Y-%m-%d')}) ===")
    
    try:
        df = fdr.DataReader(code, long_start.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
        if len(df) < 140:
            print("실패: 데이터 길이 부족")
            return
            
        df['MA5'] = df['Close'].rolling(5).mean()
        df['MA10'] = df['Close'].rolling(10).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['Vol_MA20'] = df['Volume'].rolling(20).mean()
        
        day0 = df.iloc[-1] # 오늘 (7/16)
        day1 = df.iloc[-2] # 어제 (7/15)
        day2 = df.iloc[-3] # 그저께 (7/14)
        
        rate_1 = ((day1['Close'] - day2['Close']) / day2['Close']) * 100
        rate_0 = ((day0['Close'] - day1['Close']) / day1['Close']) * 100
        
        vol_ma20_1 = df['Vol_MA20'].iloc[-2]
        vol_ma20_0 = df['Vol_MA20'].iloc[-1]
        
        print(f"D-2 (07-14): 종가={day2['Close']:,}원")
        print(f"D-1 (07-15): 시가={day1['Open']:,}원, 종가={day1['Close']:,}원, 고가={day1['High']:,}원, 저가={day1['Low']:,}원, 등락률={rate_1:+.2f}%, 거래량={day1['Volume']:,} (20일평균={vol_ma20_1:.0f} 대비 {day1['Volume']/vol_ma20_1:.2f}배)")
        print(f"D-0 (07-16): 시가={day0['Open']:,}원, 종가={day0['Close']:,}원, 고가={day0['High']:,}원, 저가={day0['Low']:,}원, 등락률={rate_0:+.2f}%, 거래량={day0['Volume']:,} (D-1거래량 대비 {day0['Volume']/day1['Volume']:.2f}배)")
        
        # 1. 어제 조건 체크 (양봉 돌파)
        # 4% ~ 22% 양봉 및 20일 평균 거래량 2.5배 이상
        is_rate_1_valid = 4.0 <= rate_1 <= 22.0
        is_yang_1 = day1['Close'] > day1['Open']
        is_vol_1_valid = day1['Volume'] >= vol_ma20_1 * 2.5
        print(f"\nD-1 (어제) 양봉 조건:")
        print(f" - 등락률 4~22% 범위 여부: {is_rate_1_valid}")
        print(f" - 양봉 여부: {is_yang_1}")
        print(f" - 거래량 2.5배 이상 여부: {is_vol_1_valid}")
        
        # 2. 오늘 조건 체크 (음봉 조정)
        # 음봉 및 거래량 D-1 대비 65% 이하
        is_eum_0 = day0['Close'] < day0['Open']
        is_vol_0_valid = day0['Volume'] <= day1['Volume'] * 0.65
        print(f"\nD-0 (오늘) 음봉 조건:")
        print(f" - 음봉 여부: {is_eum_0}")
        print(f" - 거래량 D-1 대비 65% 이하 여부: {is_vol_0_valid}")
        
    except Exception as e:
        print("디버깅 에러:", e)

if __name__ == '__main__':
    debug_proteome_yey()
