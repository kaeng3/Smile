# -*- coding: utf-8 -*-
import os
import sys
import datetime
import json
import urllib.request
import requests
import socket
socket.setdefaulttimeout(10.0)

def get_ai_commentary(code, name, pattern, close, rate, match_type, target_date=None, stock_dfs=None):
    # 1. config.json에서 API Key 로드
    config_path = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\config.json"
    api_key = None
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                api_key = json.load(f).get('GEMINI_API_KEY')
        except Exception:
            pass

    # 2. 실시간 이평선 및 지지/저항 정밀 연산
    close_curr = float(close) if close else 0.0
    ma5, ma10, ma20 = 0.0, 0.0, 0.0
    ma60, ma120, ma224 = 0.0, 0.0, 0.0
    ma5_trend, ma10_trend, ma20_trend = "우상향", "우상향", "우상향"
    ma60_trend, ma120_trend, ma224_trend = "우상향", "우상향", "우상향"
    low_today = 0.0
    vol_ratio = 100.0
    vol_comment_hint = "20일 평균 거래량 수준 유지 중"
    is_above_ma5 = False
    is_above_ma10 = False
    is_above_ma20 = False
    is_ma10_too_far = False
    is_full_reverse = False
    
    is_podosi = False
    is_60ma_rule = False
    
    try:
        import FinanceDataReader as fdr
        import datetime
        
        if target_date:
            if isinstance(target_date, str):
                end_dt = datetime.datetime.strptime(target_date, '%Y-%m-%d')
            else:
                end_dt = target_date
        else:
            end_dt = datetime.datetime.now()
            
        df_ma = None
        if stock_dfs and code in stock_dfs:
            df_ma = stock_dfs[code]
        if df_ma is None:
            df_ma = fdr.DataReader(code, start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d'))
        if df_ma is not None and len(df_ma) >= 224:
            df_ma['Vol_MA20'] = df_ma['Volume'].rolling(20).mean()
            df_ma['MA60'] = df_ma['Close'].rolling(60).mean()
            df_ma['MA120'] = df_ma['Close'].rolling(120).mean()
            df_ma['MA224'] = df_ma['Close'].rolling(224).mean()
            
            close_curr = df_ma['Close'].iloc[-1]
            low_today = df_ma['Low'].iloc[-1]
            vol_curr = df_ma['Volume'].iloc[-1]
            vol_ma20 = df_ma['Vol_MA20'].iloc[-1]
            
            # 거래량 20일 평균 대비 비율 계산
            if vol_ma20 > 0:
                vol_ratio = (vol_curr / vol_ma20) * 100
                
            # 최근 30일 이내 발생했던 대량 수급 기준봉 거래량 연산
            base_candle_vol = 0.0
            base_candle_days_ago = -1
            for idx in range(1, min(31, len(df_ma))):
                row = df_ma.iloc[-idx]
                c_val = row['Close']
                p_c_val = df_ma.iloc[-idx-1]['Close'] if idx < len(df_ma)-1 else c_val
                r_val = ((c_val - p_c_val) / p_c_val) * 100 if p_c_val > 0 else 0.0
                v_val = row['Volume']
                v_ma20 = df_ma['Vol_MA20'].iloc[-idx] if 'Vol_MA20' in df_ma else 0.0
                if r_val >= 4.0 and v_val >= v_ma20 * 2.0 and (c_val * v_val >= 1_000_000_000):
                    if v_val > base_candle_vol:
                        base_candle_vol = float(v_val)
                        base_candle_days_ago = idx - 1

            vol_comment_hint = ""
            if base_candle_days_ago == 0 or (rate >= 4.0 and vol_ratio >= 180.0):
                vol_comment_hint = f"오늘 대량 거래 기준봉 출현 (20일 평균 거래량 대비 {vol_ratio:.0f}% 폭증/증가)"
            elif base_candle_vol > 0 and vol_curr < base_candle_vol:
                vol_dec_pct = ((base_candle_vol - vol_curr) / base_candle_vol) * 100
                vol_comment_hint = f"기준봉(거래량 {base_candle_vol:,.0f}주) 출현 이후 현재 거래량이 기준봉 대비 {vol_dec_pct:.0f}% 바짝 감소(축소)한 건조한 눌림목 조정 진행 중"
            else:
                vol_comment_hint = f"20일 평균 거래량 대비 {vol_ratio:.0f}% 수준 유지 중"
                
            # 내일 예상 이평선 연산 (D+6일 전 종가 탈락, 오늘 종가 2회 계산 합산)
            ma5 = (2 * df_ma['Close'].iloc[-1] + df_ma['Close'].iloc[-2] + df_ma['Close'].iloc[-3] + df_ma['Close'].iloc[-4]) / 5
            ma10 = (2 * df_ma['Close'].iloc[-1] + sum(df_ma['Close'].iloc[-9:-1])) / 10
            ma20 = (2 * df_ma['Close'].iloc[-1] + sum(df_ma['Close'].iloc[-19:-1])) / 20
            
            ma60 = df_ma['MA60'].iloc[-1]
            ma120 = df_ma['MA120'].iloc[-1]
            ma224 = df_ma['MA224'].iloc[-1]
            
            # 이평선 기울기(방향성) 연산
            ma5_prev = (2 * df_ma['Close'].iloc[-2] + df_ma['Close'].iloc[-3] + df_ma['Close'].iloc[-4] + df_ma['Close'].iloc[-5]) / 5
            ma5_trend = "우상향" if ma5 > ma5_prev else "우하향"
            
            ma10_prev = (2 * df_ma['Close'].iloc[-2] + sum(df_ma['Close'].iloc[-10:-2])) / 10
            ma10_trend = "우상향" if ma10 > ma10_prev else "우하향"
            
            ma20_prev = (2 * df_ma['Close'].iloc[-2] + sum(df_ma['Close'].iloc[-20:-2])) / 20
            ma20_trend = "우상향" if ma20 > ma20_prev else "우하향"
            
            ma60_trend = "우상향" if ma60 > df_ma['MA60'].iloc[-2] else "우하향"
            ma120_trend = "우상향" if ma120 > df_ma['MA120'].iloc[-2] else "우하향"
            ma224_trend = "우상향" if ma224 > df_ma['MA224'].iloc[-2] else "우하향"
            
            is_above_ma5 = close_curr >= ma5 * 0.995
            is_above_ma10 = close_curr >= ma10 * 0.995
            is_above_ma20 = close_curr >= ma20 * 0.995
            
            # 완전 역배열 상태 체크 (주가 < 5 < 10 < 20 < 60 < 120)
            is_full_reverse = (close_curr < ma5 < ma10 < ma20 < ma60 < ma120)
            
            # 10일선이 종가 대비 8% 이상 아래에 멀리 떨어져 있는지 체크
            if close_curr > 0:
                is_ma10_too_far = (close_curr - ma10) / close_curr > 0.08
                
            # A. 포도시 차트 기법 검증 (중장기 이평선 윗꼬리 저항 후 20일선 지지)
            has_upper_tail_touch = False
            for idx in range(1, 11):
                if idx >= len(df_ma): break
                row = df_ma.iloc[-idx]
                high_val = row['High']
                close_val = row['Close']
                open_val = row['Open']
                body = abs(close_val - open_val)
                tail = high_val - max(close_val, open_val)
                
                ma60_val = df_ma['MA60'].iloc[-idx]
                ma120_val = df_ma['MA120'].iloc[-idx]
                
                # 윗꼬리가 몸통의 0.5배 이상이고 고가가 60선/120선에 2.5% 이내로 접촉/돌파 시도 후 밀림
                if tail >= body * 0.5 and (abs(high_val - ma60_val)/ma60_val <= 0.025 or abs(high_val - ma120_val)/ma120_val <= 0.025):
                    has_upper_tail_touch = True
                    break
            
            # 현재 주가가 20일선 부근(2.5% 이내)에 위치하여 지지를 모색하는 경우
            if has_upper_tail_touch and abs(close_curr - ma20)/ma20 <= 0.025:
                is_podosi = True
                
            # B. 60일의 법칙 검증 (상단 120일선만 있고, 60일선에서 반등 기대)
            if ma120 > close_curr and ma60 < close_curr and abs(close_curr - ma60)/ma60 <= 0.025:
                is_60ma_rule = True
                
    except Exception as e:
        print("Expected MAs and custom patterns calculation failed:", e)

    # 3. 실시간 세부 패턴 분석 (P1, P2, P3 분기용 내부 변수)
    sub_pattern = 'Pattern 1'
    breakout_k = -1
    former_peak = 0.0
    try:
        import FinanceDataReader as fdr
        import datetime
        if target_date:
            if isinstance(target_date, str):
                end_dt = datetime.datetime.strptime(target_date, '%Y-%m-%d')
            else:
                end_dt = target_date
        else:
            end_dt = datetime.datetime.now()
        start_dt = end_dt - datetime.timedelta(days=220)
        df_sub = None
        if stock_dfs and code in stock_dfs:
            df_sub = stock_dfs[code]
        if df_sub is None:
            df_sub = fdr.DataReader(code, start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d'))
        if df_sub is not None and len(df_sub) >= 20:
            df_sub['Vol_MA20'] = df_sub['Volume'].rolling(20).mean()
            df_sub['MA5'] = df_sub['Close'].rolling(5).mean()
            df_sub['MA10'] = df_sub['Close'].rolling(10).mean()
            
            row0 = df_sub.iloc[-1]
            close_0, open_0, high_0, low_0, vol_0 = row0['Close'], row0['Open'], row0['High'], row0['Low'], row0['Volume']
            vol_ma20_0 = row0['Vol_MA20']
            
            # Pattern 2 (Predictive: today is upper tail)
            body_0 = abs(close_0 - open_0)
            tail_0 = high_0 - max(close_0, open_0)
            is_p2_yang_today = 5.0 <= rate <= 25.0 and close_0 > open_0 and vol_0 >= vol_ma20_0 * 2.5 and tail_0 >= body_0 * 0.75
            
            if match_type == 'predictive':
                # Check Pattern 3 (2-4 days ago breakout, high-price play today)
                is_p3 = False
                for k in range(2, 5):
                    if k >= len(df_sub) - 1: continue
                    dk = df_sub.iloc[-k-1]
                    dk_prev = df_sub.iloc[-k-2]
                    rate_k = ((dk['Close'] - dk_prev['Close']) / dk_prev['Close']) * 100
                    dk_vol_ma20 = df_sub['Volume'].rolling(20).mean().iloc[-k-1]
                    
                    is_breakout = 5.0 <= rate_k <= 25.0 and dk['Close'] > dk['Open'] and dk['Volume'] >= dk_vol_ma20 * 2.5
                    if is_breakout:
                        breakout_k = k
                        break
                
                if breakout_k != -1:
                    breakout_close = df_sub.iloc[-breakout_k-1]['Close']
                    valid_p3 = True
                    for idx in range(1, breakout_k):
                        d_j = df_sub.iloc[-breakout_k + idx - 1]
                        d_j_ma10 = df_sub['MA10'].iloc[-breakout_k + idx - 1]
                        if d_j['Close'] < d_j_ma10 * 0.98 or d_j['Close'] < breakout_close * 0.99:
                            valid_p3 = False
                            break
                    if valid_p3 and close_0 >= breakout_close * 0.99:
                        is_p3 = True
                
                if is_p2_yang_today:
                    sub_pattern = 'Pattern 2'
                elif is_p3:
                    sub_pattern = 'Pattern 3'
                else:
                    sub_pattern = 'Pattern 1'
            else: # completed
                # Check Pattern 2 completed
                is_p2_c = False
                if len(df_sub) >= 3:
                    body_2 = abs(df_sub['Close'].iloc[-3] - df_sub['Open'].iloc[-3])
                    tail_2 = df_sub['High'].iloc[-3] - max(df_sub['Close'].iloc[-3], df_sub['Open'].iloc[-3])
                    vol_2 = df_sub['Volume'].iloc[-3]
                    vol_ma20_2 = df_sub['Vol_MA20'].iloc[-3]
                    is_p2_yang_day2 = 5.0 <= rate_1 <= 25.0 and df_sub['Close'].iloc[-3] > df_sub['Open'].iloc[-3] and vol_2 >= vol_ma20_2 * 2.5 and tail_2 >= body_2 * 0.75
                    is_p2_pullback_day1 = df_sub['Low'].iloc[-2] <= df_sub['MA5'].iloc[-2] * 1.025 and df_sub['Close'].iloc[-2] >= df_sub['MA5'].iloc[-2] * 0.995 and df_sub['Low'].iloc[-2] >= df_sub['Low'].iloc[-3]
                    if is_p2_yang_day2 and is_p2_pullback_day1 and close_0 >= open_0 * 1.04:
                        is_p2_c = True
                
                # Check Pattern 3 completed
                is_p3_c = False
                for k in range(2, 5):
                    if k >= len(df_sub) - 1: continue
                    dk = df_sub.iloc[-k-1]
                    dk_prev = df_sub.iloc[-k-2]
                    rate_k = ((dk['Close'] - dk_prev['Close']) / dk_prev['Close']) * 100
                    dk_vol_ma20 = df_sub['Volume'].rolling(20).mean().iloc[-k-1]
                    is_breakout = 5.0 <= rate_k <= 25.0 and dk['Close'] > dk['Open'] and dk['Volume'] >= dk_vol_ma20 * 2.5
                    if is_breakout:
                        breakout_k = k
                        break
                if breakout_k != -1:
                    breakout_close = df_sub.iloc[-breakout_k-1]['Close']
                    valid_p3 = True
                    for idx in range(1, breakout_k):
                        d_j = df_sub.iloc[-breakout_k + idx - 1]
                        d_j_ma10 = df_sub['MA10'].iloc[-breakout_k + idx - 1]
                        if d_j['Close'] < d_j_ma10 * 0.98 or d_j['Close'] < breakout_close * 0.99:
                            valid_p3 = False
                            break
                    if valid_p3 and close_0 >= breakout_close * 0.99 and close_0 >= open_0 * 1.04:
                        is_p3_c = True
                
                if is_p2_c:
                    sub_pattern = 'Pattern 2'
                elif is_p3_c:
                    sub_pattern = 'Pattern 3'
                else:
                    sub_pattern = 'Pattern 1'
            
            if '포도시' in pattern:
                sub_pattern = pattern
            
            # 전고점 연산
            if len(df_sub) >= 25:
                former_peak = float(df_sub['High'].iloc[-22:-2].max())
    except Exception as e:
        print("Dynamic calculation failed:", e)

    # 4. 100% 팩트 수치 기반 다변화 AI 분석 코멘트 (종목별 시드로 표현 다양화)
    def get_fallback_comment():
        seed = sum(ord(c) for c in str(code)) + int(close_curr) % 997

        # ── A. 수급/거래량 문장 (패턴·등락률·거래량 조합) ─────────────────────
        if rate >= 5.0 and vol_ratio >= 150.0:
            s1_pool = [
                f"오늘 {rate:+.2f}% 강세로 {close_curr:,}원에 마감하며 평균 대비 {vol_ratio:.0f}% 수준의 대량 수급이 유입, 세력의 적극적인 매집 의지를 확인했습니다.",
                f"주가가 {rate:+.2f}% 급등한 {close_curr:,}원에 마감했으며, 거래량이 20일 평균의 {vol_ratio:.0f}%에 달해 신규 세력 유입이 본격화되는 신호를 포착했습니다.",
                f"오늘 {close_curr:,}원({rate:+.2f}%) 강한 수급 양봉이 출현하며 평균 대비 {vol_ratio:.0f}% 폭증한 거래량으로 단기 추세 전환의 기준봉 역할을 수행했습니다.",
                f"평균 대비 {vol_ratio:.0f}% 거래량을 동반한 {rate:+.2f}% 상승({close_curr:,}원)으로 마감, 매집 기준봉 형성 후 단기 시세 분출 가능성을 열어두고 있습니다.",
            ]
        elif rate >= 5.0:
            s1_pool = [
                f"오늘 {rate:+.2f}% 상승한 {close_curr:,}원으로 마감했으며, 거래량은 평균 대비 {vol_ratio:.0f}% 수준으로 수급 개선 흐름을 보였습니다.",
                f"{close_curr:,}원({rate:+.2f}%)으로 강세 마감하며, 평균 대비 {vol_ratio:.0f}% 거래량과 함께 단기 눌림목 탈출 신호가 출현했습니다.",
                f"오늘 {rate:+.2f}% 양봉({close_curr:,}원)으로 마감, 거래량은 20일 평균 대비 {vol_ratio:.0f}% 수준으로 상방 탄력 회복을 시사합니다.",
            ]
        elif rate <= -5.0 and vol_ratio >= 150.0:
            s1_pool = [
                f"오늘 {rate:+.2f}% 급락한 {close_curr:,}원으로 마감했으며, 평균 대비 {vol_ratio:.0f}% 대량 거래가 수반되어 상단 매물 출회 및 손바꿈 가능성이 제기됩니다.",
                f"{rate:+.2f}% 하락({close_curr:,}원) 마감 속에 평균 대비 {vol_ratio:.0f}% 거래량이 터지며 세력 이탈보다는 공격적 손바꿈 과정으로 해석할 여지가 있습니다.",
                f"오늘 {close_curr:,}원({rate:+.2f}%) 대량 거래 하락으로 마감, 이평선 대비 위치 및 전저점 지지 여부가 핵심 판단 포인트입니다.",
            ]
        elif rate <= -5.0:
            s1_pool = [
                f"오늘 {rate:+.2f}% 하락한 {close_curr:,}원으로 마감했으며, 거래량은 평균 대비 {vol_ratio:.0f}% 수준으로 가격 조정이 진행됐습니다.",
                f"{close_curr:,}원({rate:+.2f}%) 하락 마감, 거래량 {vol_ratio:.0f}% 수준 속 단기 지지 이평선의 방어 여부가 핵심입니다.",
                f"오늘 {rate:+.2f}% 음봉({close_curr:,}원)을 형성했으며, 평균 대비 {vol_ratio:.0f}% 거래로 숨고르기 조정이 일어났습니다.",
            ]
        elif vol_ratio <= 50.0:
            s1_pool = [
                f"오늘 {rate:+.2f}% 변동된 {close_curr:,}원으로 마감했으며, 거래량이 20일 평균의 {vol_ratio:.0f}%로 바짝 말라붙어 투매 물량이 소진되는 눌림목 완결 신호를 보입니다.",
                f"거래량이 평균 대비 {vol_ratio:.0f}% 수준으로 급감하며 {close_curr:,}원({rate:+.2f}%)에 마감, 매물 공백 구간에서 상방 반등 에너지가 응축되고 있습니다.",
                f"{close_curr:,}원({rate:+.2f}%) 마감 속 거래량 {vol_ratio:.0f}%로 극도 건조한 눌림목이 형성되어 다음 수급 유입 시 빠른 반등이 기대됩니다.",
            ]
        else:
            s1_pool = [
                f"오늘 {rate:+.2f}% 변동된 {close_curr:,}원으로 마감했으며, 거래량은 평균 대비 {vol_ratio:.0f}% 수준으로 숨고르기 횡보 양상을 유지하고 있습니다.",
                f"{close_curr:,}원({rate:+.2f}%) 마감, 거래량 평균 대비 {vol_ratio:.0f}% 수준의 조정 장세 속에서 다음 파동을 위한 에너지를 비축 중입니다.",
                f"오늘 {close_curr:,}원({rate:+.2f}%)으로 마감하며 거래량 {vol_ratio:.0f}% 수준의 차분한 눌림목이 이어지고 있습니다.",
            ]
        s1 = s1_pool[seed % len(s1_pool)]

        # ── B. 이평선·지지·저항 문장 ──────────────────────────────────────────
        # 주가 위에 있는 이평선(저항) / 아래 있는 이평선(지지) 분류
        below_mas = []   # 주가보다 아래 → 지지
        above_mas = []   # 주가보다 위  → 저항
        for label, val in [("5일선", ma5), ("20일선", ma20), ("60일선", ma60), ("120일선", ma120)]:
            if val <= 0: continue
            if close_curr >= val:
                below_mas.append(f"{label}({val:.0f}원)")
            else:
                above_mas.append(f"{label}({val:.0f}원)")

        supp_str = below_mas[-1] if below_mas else f"전저점({low_today:.0f}원)"
        resist_str = above_mas[0] if above_mas else (f"전고점({former_peak:.0f}원)" if former_peak > close_curr else "상단 이격 저항대")

        s2_pool = [
            f"현재 {supp_str} 위에서 지지를 확인했으며, 상단 {resist_str} 돌파 여부가 단기 방향성의 핵심 분기점이 됩니다.",
            f"{supp_str}을 디딤돌로 삼아 반등을 시도 중이며, {resist_str} 구간까지의 공간이 단기 수익 구간으로 설정됩니다.",
            f"하단 {supp_str} 지지 라인이 방어선으로 작동하고 있으며, {resist_str}을 상방 돌파 시 추세 전환 신호로 해석할 수 있습니다.",
            f"주가가 {supp_str}에 안착한 상태에서 {resist_str} 저항선을 향한 단기 반등 시도가 기대됩니다.",
            f"{supp_str} 지지 밴드 유지 여부가 관건이며, 이탈 시 전저점({low_today:.0f}원) 재테스트 가능성을 배제하기 어렵습니다.",
        ]
        s2 = s2_pool[(seed // 3) % len(s2_pool)]

        # ── C. 실전 매매 대응 문장 ────────────────────────────────────────────
        # 매수 타점: 주가 바로 아래 유효 지지선 기준
        if below_mas and ma5 > 0 and close_curr >= ma5:
            buy_zone = f"5일선({ma5:.0f}원) 및 전일 저점({low_today:.0f}원) 부근 2분할"
            stop_zone = f"전일 저점({low_today:.0f}원) 이탈"
        elif below_mas and ma20 > 0 and close_curr >= ma20:
            buy_zone = f"20일선({ma20:.0f}원) 및 전저점({low_today:.0f}원) 부근 2분할"
            stop_zone = f"20일선({ma20:.0f}원) 이탈"
        elif below_mas and ma60 > 0 and close_curr >= ma60:
            buy_zone = f"60일선({ma60:.0f}원) 및 전저점({low_today:.0f}원) 부근 2분할"
            stop_zone = f"전저점({low_today:.0f}원) 훼손"
        else:
            buy_zone = f"전저점({low_today:.0f}원) 부근 신중한 분할"
            stop_zone = f"전저점({low_today:.0f}원) 이탈"

        target_str = f"전고점({former_peak:.0f}원)" if former_peak > close_curr * 1.03 else f"{resist_str}"

        s3_pool = [
            f"실전 매매는 {buy_zone} 매수로 접근하고, {stop_zone} 시 즉시 손절 대응하는 것이 정석입니다. 1차 목표가는 {target_str} 부근으로 설정하십시오.",
            f"{buy_zone} 접근이 유효하며 {stop_zone} 기준으로 손절선을 설정, 리스크를 제한하면서 {target_str}까지의 수익 구간을 노리십시오.",
            f"매수 타점은 {buy_zone}이며, {stop_zone} 장중 확인 시 미련 없이 손절 처리 후 {target_str} 목표로 재진입 기회를 탐색하십시오.",
            f"분할 매수 전략으로 {buy_zone}을 활용하고, {stop_zone} 발생 시 즉시 대응하는 기계적 원칙 매매를 권장합니다. 목표는 {target_str}입니다.",
        ]
        s3 = s3_pool[(seed // 7) % len(s3_pool)]

        return f"{s1} {s2} {s3}"

    if not api_key:
        return get_fallback_comment()

    # 5. 다양한 Gemini 무료 모델 풀 (429 쿼터 초과 시 자동으로 다음 모델 전환)
    all_models = [
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-pro"
    ]
    # 종목 코드 기반으로 시작 모델을 다르게 하여 모델별 쿼터를 균등 분산
    start_idx = sum(ord(c) for c in str(code)) % len(all_models)
    models_to_try = all_models[start_idx:] + all_models[:start_idx]
    
    # 이평선 수치 및 위치 정리
    ma_info_lines = []
    for label, val, trend in [
        ("5일선", ma5, ma5_trend), ("10일선", ma10, ma10_trend),
        ("20일선", ma20, ma20_trend), ("60일선", ma60, ma60_trend),
        ("120일선", ma120, ma120_trend), ("224일선", ma224, ma224_trend)
    ]:
        if val > 0:
            pos = "위(지지)" if close_curr >= val else "아래(저항)"
            ma_info_lines.append(f" - {label}: {val:.0f}원 ({pos}, 추세: {trend})")
    ma_info_str = "\n".join(ma_info_lines)

    prompt = (
        f"당신은 20년 경력의 차트 전문 주식 트레이더입니다. 다음 종목 데이터를 바탕으로 실전 코멘트(2~3문장)를 작성하세요.\n\n"
        f"[종목 데이터]\n"
        f"- 종목명: {name} ({code})\n"
        f"- 포착 패턴: {sub_pattern}\n"
        f"- 오늘 종가: {close_curr:,}원 ({rate:+.2f}%), 오늘 저점: {low_today:.0f}원\n"
        f"- 거래량 분석 핵심 정보: {vol_comment_hint}\n"
        f"- 최근 20일 전고점: {former_peak:.0f}원\n"
        f"[주요 이평선 현황]\n{ma_info_str}\n\n"
        f"[작성 지침]\n"
        f"1. '오늘', '현재', '종가' 같은 정형화된 첫 단어로 시작하지 말고 매 종목마다 다채롭게 시작하세요.\n"
        f"2. 거래량 코멘트 필살 규칙: 오늘이 대량 거래 터진 기준봉 당일이면 20일 평균 대비 몇 % 증가(유입/폭증)했는지를 코멘트하고, 기준봉이 나온 이후 눌림목/조정 구간이면 지난 기준봉 거래량 대비 몇 % 바짝 감소(축소)했는지를 정확히 서술하세요.\n"
        f"3. 종가가 이평선 위에 있으면 '지지', 아래에 있으면 '저항'입니다. 종가가 5일선 위에 있으면 절대로 5일선 저항이라는 표현을 쓰지 마세요.\n"
        f"4. 이평선 가격, 전고점/전저점 지지선, 거래량을 녹여 매수 타점과 명확한 손절 가격을 제시하세요.\n"
        f"5. 인사말, 전문가 소개, 영어 지침 등은 쓰지 마시고 2~3문장, 순수 한국어 텍스트만 반환하세요."
    )

    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 1.1,
            'maxOutputTokens': 300,
        }
    }

    def clean_comment_text(text):
        if not text: return ""
        import re
        text = re.sub(r'Guidelines:.*', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'No cliches.*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\(Support,?\s*Upward\)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\([A-Za-z0-9\s,\->]+\)', '', text)
        text = re.sub(r'^[0-9\s,\->\(\)A-Za-z]+', '', text) # 영문/숫자 서두 조각 제거
        lines = [l.strip() for l in text.split('\n') if l.strip() and not l.strip().startswith('**') and not l.strip().startswith('[')]
        res = ' '.join(lines).strip()
        # 한국어가 포함되어 있지 않거나 너무 짧으면 전면 거부
        if not re.search(r'[가-힣]', res):
            return ""
        return res

    if api_key and len(api_key) > 10:
        for model_name in models_to_try[:2]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                headers = {'Content-Type': 'application/json'}
                response = requests.post(url, headers=headers, json=payload, timeout=1.5)
                if response.status_code == 200:
                    data = response.json()
                    text = data['candidates'][0]['content']['parts'][0]['text']
                    cleaned = clean_comment_text(text)
                    if cleaned and len(cleaned) > 20:
                        return cleaned
            except Exception:
                continue

    fallback = clean_comment_text(get_fallback_comment())
    if not fallback or len(fallback) < 20:
        return f"오늘 종가는 {close_curr:,}원({rate:+.2f}%)이며, 5일선({ma5:.0f}원) 및 20일선({ma20:.0f}원) 지지 여부를 기점으로 분할 매수 타점을 포착하십시오."
    return fallback

def get_ai_review_commentary(code, name, pattern, close_prev, close_curr, low_curr, high_curr, rate, max_prof, prev_comment, target_date=None, stock_dfs=None):
    config_path = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\config.json"
    if not os.path.exists(config_path):
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    api_key = None
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                api_key = json.load(f).get('GEMINI_API_KEY')
        except Exception:
            pass

    # 2. 실시간 이평선 및 지지/저항 정밀 연산
    ma5, ma10, ma13, ma20, ma60, ma120 = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    prev_low_20, prev_high_20 = 0.0, 0.0
    try:
        import FinanceDataReader as fdr
        import datetime
        if target_date:
            if isinstance(target_date, str):
                end_dt = datetime.datetime.strptime(target_date, '%Y-%m-%d')
            else:
                end_dt = target_date
        else:
            end_dt = datetime.datetime.now()
        start_dt = end_dt - datetime.timedelta(days=220)
        
        df_ma = None
        if stock_dfs and code in stock_dfs:
            df_ma = stock_dfs[code]
        if df_ma is not None and len(df_ma) >= 20:
            df_ma['MA5'] = df_ma['Close'].rolling(5).mean()
            df_ma['MA10'] = df_ma['Close'].rolling(10).mean()
            df_ma['MA13'] = df_ma['Close'].rolling(13).mean()
            df_ma['MA20'] = df_ma['Close'].rolling(20).mean()
            df_ma['MA60'] = df_ma['Close'].rolling(60).mean()
            df_ma['MA120'] = df_ma['Close'].rolling(120).mean()
            
            ma5 = df_ma['MA5'].iloc[-1]
            ma10 = df_ma['MA10'].iloc[-1]
            ma13 = df_ma['MA13'].iloc[-1]
            ma20 = df_ma['MA20'].iloc[-1]
            ma60 = df_ma['MA60'].iloc[-1]
            ma120 = df_ma['MA120'].iloc[-1]
            
            prev_low_20 = df_ma['Low'].iloc[-21:-1].min()
            prev_high_20 = df_ma['High'].iloc[-21:-1].max()
    except Exception:
        pass

    # 3. 룰 기반 대체 템플릿 정의 (API 실패 시 롤백용)
    def get_fallback_review():
        touch_ma = []
        ma_lines = [(5, ma5), (10, ma10), (13, ma13), (20, ma20), (60, ma60), (120, ma120)]
        for name_ma, val_ma in ma_lines:
            if not val_ma or val_ma != val_ma: continue
            if abs(low_curr - val_ma) / val_ma <= 0.015:
                touch_ma.append(f"{name_ma}일선")
                
        touch_low_high = []
        if prev_low_20 and abs(low_curr - prev_low_20) / prev_low_20 <= 0.018:
            touch_low_high.append("전저점")
        if prev_high_20 and abs(low_curr - prev_high_20) / prev_high_20 <= 0.018:
            touch_low_high.append("전고점")
            
        support_details = []
        if touch_ma:
            support_details.append(f"{', '.join(touch_ma)} 지지력 확인")
        if touch_low_high:
            support_details.append(f"{'/'.join(touch_low_high)} 부근 지지")
            
        support_str = f" ({', '.join(support_details)})" if support_details else ""
        
        if max_prof >= 3.0:
            return f"장중 최고 {max_prof:+.1f}% 상승하며 진입 후 반등에 성공했습니다.{support_str}"
        elif close_curr < close_prev:
            return f"오늘 {rate:+.1f}% 조정을 거치며 이평선 지지력을 재차 테스트 중입니다.{support_str}"
        else:
            return f"오늘 {rate:+.1f}% 흐름으로 견조하게 지지선을 수호하며 마감했습니다.{support_str}"

    if not api_key:
        return get_fallback_review()

    # 4. Gemini API 호출
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    
    prompt = (
        f"당신은 주식 분석 전문가 '김일청'입니다. 전일 선정했던 관심 종목인 {name} ({code})에 대한 당일 결과와 차트 지지 여부를 바탕으로 '오늘의 실전 결과 및 복기 포인트'에 들어갈 해설 코멘트(약 2문장 내외)를 작성해 주세요.\n\n"
        f"- 전일 제시했던 공략 가이드라인: {prev_comment}\n"
        f"- 어제 종가: {close_prev:,}원\n"
        f"- 오늘 종가: {close_curr:,}원 (등락률: {rate:+.2f}%)\n"
        f"- 오늘 고가: {high_curr:,}원 (장중 최고 상승폭: {max_prof:+.2f}%)\n"
        f"- 오늘 저점: {low_curr:,}원\n"
        f"- 오늘의 이동평균선 가격: 5일선={ma5:.0f}원, 10일선={ma10:.0f}원, 13일선={ma13:.0f}원, 20일선={ma20:.0f}원, 60일선={ma60:.0f}원, 120일선={ma120:.0f}원\n"
        f"- 최근 20거래일 중 전저점: {prev_low_20:.0f}원, 전고점: {prev_high_20:.0f}원\n\n"
        f"작성 가이드라인:\n"
        f"1. 오늘 저점({low_curr:,}원)이 어떤 이동평균선이나 전고점/전저점 부근을 터치하고 지지받았는지를 차트 팩트에 맞게 명확하게 설명해 주세요.\n"
        f"   (예를 들어, 오늘 저점이 5일선이나 20일선에 근접했다면 해당 선 지지력을 확인했다고 짚어주고, 전저점에 닿았다면 전저점 지지력이 단단함을 부각해 주세요.)\n"
        f"2. 오늘 주가 흐름이 반등에 성공했는지(장중 최고 상승률이 +3% 이상이면 성공으로 묘사), 혹은 지지선을 다지며 눌림 조정을 받았는지를 친근하면서도 날카로운 전문가 어조로 2문장 내외로 요약하세요.\n"
        f"3. 존댓말로 작성하되, '오늘의 실전 결과 및 복기 포인트:' 등의 머리말은 제외하고 순수 본문 텍스트만 반환해 주세요."
    )

    payload = {
        'contents': [{
            'parts': [{
                'text': prompt
            }]
        }]
    }

    if not api_key or len(api_key) < 10:
        return get_fallback_review()

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=1.5)
        if response.status_code == 200:
            data = response.json()
            text = data['candidates'][0]['content']['parts'][0]['text']
            return text.strip()
        else:
            return get_fallback_review()
    except Exception:
        return get_fallback_review()
