# -*- coding: utf-8 -*-
import os
import json
import requests

def get_ai_commentary(stock_info, target_date_str=None):
    """
    Gemini API를 사용하여 종목별 '이동평균선과 500억 봉의 비밀' 기법 분석 코멘트를 생성합니다.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "config.json")
    api_key = None
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                api_key = json.load(f).get('GEMINI_API_KEY')
        except Exception:
            pass

    code = stock_info['code']
    name = stock_info['name']
    day_type = stock_info['day_type']
    close = stock_info['close']
    rate = stock_info['rate']
    low = stock_info['low']
    vol_ratio = stock_info['vol_ratio']
    exp_ma = stock_info['expected_ma']
    former_peak = stock_info['former_peak']
    vol_change_ratio = stock_info.get('vol_change_ratio', 100.0)
    ref_date = stock_info['ref_date']
    
    is_bullish_alignment = stock_info.get('is_bullish_alignment', False)
    is_gap_up = stock_info.get('is_gap_up', False)
    ma3_ma5_disparity = stock_info.get('ma3_ma5_disparity', 0.0)
    has_weak_ma3_rebound = stock_info.get('has_weak_ma3_rebound', False)

    vol_trend_up = stock_info.get('vol_trend_up', False)
    vol_drying_ok = stock_info.get('vol_drying_ok', False)
    h_supports = stock_info.get('h_supports', [])
    trendline_support = stock_info.get('trendline_support', None)

    day_type_korean = {0: "0일차 (기준봉 당일 출현)", 1: "1일차 (기준봉 익일 조정)", 2: "2일차 (기준봉 이틀 후 조정)"}
    day_desc = day_type_korean.get(day_type, f"{day_type}일차")

    def get_fallback_comment():
        if day_type == 0:
            return f"오늘 거래량이 평소 대비 {vol_ratio:.0f}% 수준으로 급증하며 강력한 기준봉을 형성했습니다. 당일 대량 거래 유입으로 관심 종목 등록의 찬스이며, 내일 이후의 3일선({exp_ma['ma3']:.0f}원) 및 5일선 지지 궤적을 확인해야 합니다."
        elif day_type == 1:
            if close < exp_ma['ma3']:
                return f"기준봉 출현 익일인 오늘, 현재 주가({close:,}원)가 예상 3일선({exp_ma['ma3']:.0f}원) 아래로 이탈하며 3일선이 상방 저항으로 작용하고 있습니다. 거래량 감소를 확인하며 보수적으로 대응해야 합니다."
            else:
                return f"기준봉 출현 익일인 오늘, 거래량이 기준봉 대비 {vol_change_ratio:.0f}% 수준으로 감소한 조정을 보이고 있습니다. 내일 예상 3일선({exp_ma['ma3']:.0f}원) 부근을 지지 매수 밴드로 활용하여 분할 대응하기 좋습니다."
        elif day_type == 2:
            if close < exp_ma['ma8']:
                return f"기준봉 출현 2일차로, 현재 주가({close:,}원)가 예상 8일선({exp_ma['ma8']:.0f}원) 아래에 위치하여 8일선이 상방 저항선 역할을 하고 있습니다. 이평선 돌파 및 거래량 재유입 여부를 확인하며 관망하는 전략이 필요합니다."
            else:
                return f"기준봉 출현 2일차로 가격 수렴 중이며, 오늘 거래량이 기준봉 대비 {vol_change_ratio:.0f}% 수준으로 감소했습니다. 예상 8일선({exp_ma['ma8']:.0f}원) 부근을 매수 맥점으로 삼아 반등 파동을 노려보기 좋은 정석적인 타점입니다."
        return "이동평균선 수렴 밴드 부근에서 가격 조정을 성공적으로 마치고, 지지 반등 기류를 보이는 스윙 관심 영역입니다."

    if not api_key:
        return get_fallback_comment()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}

    if h_supports:
        h_support_str = ', '.join([f"{int(p):,}원" for p in h_supports])
    else:
        h_support_str = "명확한 수평지지선 없음"

    trendline_str = f"{int(trendline_support):,}원 (우상향 추세선 지지)" if trendline_support else "사선지지 해당 없음 (추세선 미형성)"

    def get_ma_rel(ma_val):
        if close < ma_val:
            return f"현재 종가({close:,}원)보다 위에 위치함 -> 상방 저항선(저항 역할)"
        else:
            return f"현재 종가({close:,}원)보다 아래/부근에 위치함 -> 하방 지지선(지지 역할)"

    ma3_rel = get_ma_rel(exp_ma['ma3'])
    ma5_rel = get_ma_rel(exp_ma['ma5'])
    ma8_rel = get_ma_rel(exp_ma['ma8'])
    ma20_rel = get_ma_rel(exp_ma['ma20'])

    prompt = f"""안녕하세요, 주식 분석 전문가 청혼가 에이전트 김일청입니다. 다음 종목의 차트 데이터에 대해 차읽남 소장의 실제 실전 매매 강의 바이블을 바탕으로 전문적이고 깊이 있는 투자 코멘트(약 4~5문장)를 작성해 주세요.

[3일선 매매 법칙 핵심 가이드라인]
1. **개념**: 급등주가 상승 후 처음 맞이하는 1차 눌림(조정)에서 3일선 부근을 공략하는 기법. "급등주는 5일선 조정조차 기다리지 않고 빠르게 첫 눌림을 끝낸다"는 심리 반영.
2. **정배열**: 3일선 > 5일선 > 20일선 정배열일 때 지지 신뢰도가 높으며 수익 극대화 가능. 역배열인 경우 반등세가 약하고 하락 리스크가 큼.
3. **이격**: 3일선과 5일선의 이격이 매우 좁으면 주가가 5일선까지 하락했다가 반등할 수 있으므로, 3일선에만 매수를 고집하지 않고 5일선 근처까지 분할 매수로 대응함.
4. **갭상승**: 기준봉 다음 날 갭상승 출발했다가 눌리는 종목이 기술적 반등 탄력이 강함. 갭하락으로 내려온 종목은 반등 강도가 현저히 떨어짐.
5. **대응**: 단기 청산이 원칙(저가 대비 8~20% 반등 구간). 매수가 대비 -5% 이탈 또는 5일선 종가 이탈 시 즉시 기계적으로 칼손절 적용.

[8일선 매매 법칙 핵심 가이드라인]
1. **개념**: 3일선 조정을 넘어선 '두 번째 조정' 자리. "5일선 이탈 시 개인의 공포 손절 투매(패닉셀) 물량을 세력이 8일선 부근에서 재수급하여 반등시킨다"는 해석 프레임.
2. **거래량**: 5일선 이탈 시 거래량이 급감하며(매물 소진) 눌림을 거치는 것이 필수.
3. **대장주**: 반드시 150억/500억 대형 거래대금을 동반한 주도 테마 대장주에만 적용.
4. **역상관**: 3일선에서의 반등이 매우 약했다면, 8일선에서 강력한 반등이 뿜어져 나올 확률이 높음.
5. **대응**: 반등 시 전고점 돌파를 노리며 목표가를 길게 설정 가능.

[참고용 분석 데이터]
- 종목명: {name} ({code})
- 현재 상태: {day_desc} (기준봉 발생일: {ref_date})
- 오늘 종가: {close:,}원 (등락률: {rate:+.2f}%)
- 오늘 저점: {low:,}원
- 오늘 거래량 비율: 20일 평균 대비 {vol_ratio:.0f}%
- 기준봉 대비 오늘 거래량 비율: {vol_change_ratio:.0f}%
- 거래량 단기(5일) 추세: {'증가 추세 ↑' if vol_trend_up else '감소 추세 ↓'}
- 기준봉 이후 조정 중 거래량 감소(건전 눌림): {'예 (거래 감소로 건전한 조정)' if vol_drying_ok else '아니오 (거래량 유지 중)'}
- 수평지지 레벨 (가까운 순): {h_support_str}
- 사선지지 (추세선 현재가): {trendline_str}
- 3일선 > 5일선 > 20일선 정배열 상태: {'예' if is_bullish_alignment else '아니오'}
- 기준봉 다음날 갭상승 조정 여부: {'예 (갭상승 후 건전 조정)' if is_gap_up else '아니오 (갭하락 조정)'}
- 오늘 기준 3일선과 5일선 이격도: {ma3_ma5_disparity:.2f}%
- 직전 3일선 반등 약세로 인한 8일선 역상관 기대 대상: {'예 (3일선 반등이 약해 8일선에서 강반등 기대 가능)' if has_weak_ma3_rebound else '아니오'}
- 내일 예상 이평선 가격, 주가 대비 상대 위치 및 역할(지지/저항):
  * 예상 3일선: {exp_ma['ma3']:.0f}원 [{ma3_rel}], 방향: {exp_ma['ma3_trend']}
  * 예상 5일선: {exp_ma['ma5']:.0f}원 [{ma5_rel}], 방향: {exp_ma['ma5_trend']}
  * 예상 8일선: {exp_ma['ma8']:.0f}원 [{ma8_rel}], 방향: {exp_ma['ma8_trend']}
  * 예상 20일선: {exp_ma['ma20']:.0f}원 [{ma20_rel}], 방향: {exp_ma['ma20_trend']}
- 직전 전고점 (저항선 및 지지선 기대치): {former_peak:,}원

[작성 지침: 실전 차트 분석 전개]
- 데이터 수치를 단순히 기계적으로 읊지 마세요.
🚨 **[필수 지지 vs 저항 판정 규칙 - 절대 위반 금지]**:
1. 현재 종가보다 **이평선이 위에 있는 경우 (주가 < 이평선)**:
   - 해당 이평선은 주가의 상단을 막는 **'상방 저항선(저항 역할)'**입니다!
   - 절대로 '지지선'이나 '매수하러 내려오는 눌림목 자리'로 설명하지 마세요!
2. 현재 종가보다 **이평선이 아래에 있거나 부근인 경우 (주가 >= 이평선)**:
   - 해당 이평선은 **'하방 지지선(지지 역할)'**입니다.
📊 **[거래량 분석 필수 포함]**:
- 거래량 추세(증가/감소), 조정 중 거래량 감소(건전성) 여부를 반드시 코멘트에 언급하세요.
📐 **[지지선 분석 필수 포함]**:
- 수평지지 레벨 또는 사선지지(추세선) 중 유효한 것을 반드시 언급하고, 해당 구간에서의 매수 전략을 제시하세요.
- 위 지지/저항 원칙 및 거래량·지지선 분석을 포함하여 4~5문장의 프로페셔널한 실전 차트 해설로 작성해 주세요.

코멘트:
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 400
        }
    }

    import time
    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            res_json = response.json()
            commentary = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            if commentary.startswith('"') and commentary.endswith('"'):
                commentary = commentary[1:-1].strip()
            return commentary
        except Exception:
            if attempt < 2:
                time.sleep(4)
            else:
                return get_fallback_comment()

def get_ai_commentary_ma_near(stock_info, target_date_str=None):
    """
    Gemini API를 사용하여 이평선 근접 종목의 실전 차트 분석 코멘트를 생성합니다.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "config.json")
    api_key = None
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                api_key = json.load(f).get('GEMINI_API_KEY')
        except Exception:
            pass

    code = stock_info['code']
    name = stock_info['name']
    close = stock_info['close']
    rate = stock_info.get('rate', 0.0)
    low = stock_info.get('low', 0.0)
    ma15 = stock_info['ma15']
    ma20 = stock_info['ma20']
    near15 = stock_info['near15']
    near20 = stock_info['near20']
    trend15 = stock_info['trend15_up']
    trend20 = stock_info['trend20_up']
    ref_date = stock_info.get('ref_date', '')

    vol_trend_up = stock_info.get('vol_trend_up', False)
    vol_drying_ok = stock_info.get('vol_drying_ok', False)
    h_supports = stock_info.get('h_supports', [])
    trendline_support = stock_info.get('trendline_support', None)

    if h_supports:
        h_support_str = ', '.join([f"{int(p):,}원" for p in h_supports])
    else:
        h_support_str = "명확한 수평지지선 없음"

    trendline_str = f"{int(trendline_support):,}원 (우상향 추세선 지지)" if trendline_support else "사선지지 해당 없음"

    def get_fallback_comment():
        parts = []
        if near15:
            parts.append(f"15일 이평선({ma15:.0f}원) 부근 지지")
            if trend15:
                parts.append("(우상향 추세)")
        if near20:
            parts.append(f"20일 이평선({ma20:.0f}원) 부근 지지")
            if trend20:
                parts.append("(우상향 추세)")
        return f"{name}({code}) 종목은 최근 500억봉({ref_date}) 발생 이후 조정을 받아, 오늘 " + ", ".join(parts) + f" 구역에 도달했습니다. 수평({h_support_str})/사선({trendline_str}) 지지 궤적을 함께 확인하며 대응할 타점입니다."

    if not api_key:
        return get_fallback_comment()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}

    prompt = f"""안녕하세요, 주식 분석 전문가 청혼가 에이전트 김일청입니다. 최근 20거래일 동안 500억봉 기준봉이 발생한 후 조정을 받아, 오늘 15일 이평선 또는 20일 이평선 부근에 지지/반등을 받기 위해 진입한 다음 종목에 대한 실전 매매 기술적 분석 코멘트(약 4~5문장)를 작성해 주세요.

[참고용 분석 데이터]
- 종목명: {name} ({code})
- 500억봉 발생일: {ref_date}
- 오늘 종가: {close:,}원 (등락률: {rate:+.2f}%)
- 오늘 저점: {low:,}원
- 15일 이평선: {ma15:.1f}원 (이평선 근접 여부: {'예' if near15 else '아니오'}, 이평선 우상향 여부: {'예' if trend15 else '아니오'})
- 20일 이평선: {ma20:.1f}원 (이평선 근접 여부: {'예' if near20 else '아니오'}, 이평선 우상향 여부: {'예' if trend20 else '아니오'})
- 거래량 단기(5일) 추세: {'증가 추세 ↑' if vol_trend_up else '감소 추세 ↓'}
- 기준봉 이후 거래량 감소(건전 눌림): {'예 (거래 감소로 건전한 조정)' if vol_drying_ok else '아니오'}
- 수평지지 레벨: {h_support_str}
- 사선지지 (추세선 현재가): {trendline_str}

[작성 지침: 실전 차트 분석 전개]
- 데이터 수치를 단순히 기계적으로 읊지 마세요.
- 500억봉 발생 이후 조정을 받아 15일선 또는 20일선 부근에 도달한 상황입니다.
- 거래량 감소/증가 추세, 수평지지 가격대, 사선지지 추세선 유효 여부를 반드시 기술적으로 엮어서 설명해 주세요.
- 4~5문장의 프로페셔널한 분석으로 작성해주세요.

코멘트:
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 400
        }
    }

    import time
    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            res_json = response.json()
            commentary = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            if commentary.startswith('"') and commentary.endswith('"'):
                commentary = commentary[1:-1].strip()
            return commentary
        except Exception:
            if attempt < 2:
                time.sleep(4)
            else:
                return get_fallback_comment()
