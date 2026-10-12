# -*- coding: utf-8 -*-
"""
trading_day.py — 이번 실행이 '어느 거래일' 데이터를 만드는지 한 곳에서 정한다.

규칙(한국시간 기준)
- 환경변수 SCAN_DATE(YYYYMMDD)가 있으면 그대로 쓴다(수동 지정·하위 단계 공통).
- 00:00~08:59 실행은 전날 장 마감분으로 본다(예약 실행이 자정을 넘겨 늦게 도는 경우).
- 그 날짜가 한국거래소 휴장일(주말·공휴일)이면 None → 스캔을 건너뛴다.

CLI: python trading_day.py  →  'YYYYMMDD' 또는 'SKIP' 출력 (--iso 이면 YYYY-MM-DD)
"""
import os
import sys
import datetime

KST = datetime.timezone(datetime.timedelta(hours=9))
EARLY_MORNING_HOUR = 9


def kst_now():
    return datetime.datetime.now(KST).replace(tzinfo=None)


def is_session(day):
    try:
        import exchange_calendars
        import pandas as pd
        cal = exchange_calendars.get_calendar('XKRX', start=day - datetime.timedelta(days=30),
                                              end=day + datetime.timedelta(days=30))
        return bool(cal.is_session(pd.Timestamp(day)))
    except Exception as e:  # 달력을 못 쓰면 주말만 거른다
        print(f"[거래일] 휴장일 달력 사용 실패, 주말만 판정: {e}", file=sys.stderr)
        return day.weekday() < 5


def resolve_scan_date(now=None):
    """'YYYYMMDD' 또는 None(휴장일이라 건너뜀)."""
    forced = os.environ.get('SCAN_DATE', '').strip()
    if forced:
        return forced
    now = now or kst_now()
    day = now.date()
    if now.hour < EARLY_MORNING_HOUR:
        day -= datetime.timedelta(days=1)
    return day.strftime('%Y%m%d') if is_session(day) else None


def scan_datetime():
    """하위 스크립트용: SCAN_DATE(없으면 한국시간 오늘)를 자정 datetime으로."""
    s = os.environ.get('SCAN_DATE', '').strip()
    if s:
        return datetime.datetime.strptime(s, '%Y%m%d')
    return kst_now().replace(hour=0, minute=0, second=0, microsecond=0)


if __name__ == '__main__':
    d = resolve_scan_date()
    if not d:
        print('SKIP')
    elif '--iso' in sys.argv:
        print(f'{d[:4]}-{d[4:6]}-{d[6:]}')
    else:
        print(d)
