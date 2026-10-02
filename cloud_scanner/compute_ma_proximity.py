# -*- coding: utf-8 -*-
"""
compute_ma_proximity.py
베타실험실3: 최근(scan_history.json에 남아있는 최대 5영업일) 양음양 v2에 잡힌 종목 중,
최신 종가가 5/10/15/20일 이동평균선 근처(±NEAR_THRESHOLD)에 온 종목을 골라
ma_proximity.json으로 저장한다.

시세는 매일 스캔이 이미 채워둔 로컬 캐시 DB(stock_ohlcv_cache.db)를 그대로 읽으므로
외부 요청이 없다.
"""
import os
import sys
import json
import sqlite3
import datetime

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

SCANNER_DIR = os.path.dirname(os.path.abspath(__file__))
GIT_DIR = os.path.dirname(SCANNER_DIR)
SCAN_HISTORY_PATH = os.path.join(GIT_DIR, 'scan_history.json')
DB_PATH = os.path.join(SCANNER_DIR, 'stock_ohlcv_cache.db')
OUTPUT_PATH = os.path.join(GIT_DIR, 'ma_proximity.json')

MA_PERIODS = (5, 10, 15, 20)
NEAR_THRESHOLD = 0.02  # 종가가 이평선 대비 ±2% 이내면 '근처'


def collect_v2_stocks(scan_history):
    """scan_history.json의 각 날짜 'v2' 목록을 종목코드 기준으로 합친다."""
    stocks = {}
    for date in sorted(scan_history.keys()):
        for s in scan_history[date].get('v2', []):
            code = s.get('code')
            if not code:
                continue
            entry = stocks.setdefault(code, {'name': s.get('name', ''), 'captured_dates': []})
            if date not in entry['captured_dates']:
                entry['captured_dates'].append(date)
            if s.get('name'):
                entry['name'] = s['name']
    return stocks


CHART_BARS = 60  # 카드에 그릴 최근 거래일 수


def recent_rows(cursor, code, limit=CHART_BARS + max(MA_PERIODS) - 1):
    """최근 limit개 (date, open, high, low, close, volume) 행을 오래된 것 -> 최신 순으로.
    차트 첫 봉부터 20일선을 그릴 수 있도록 CHART_BARS보다 19개 더 가져온다."""
    cursor.execute(
        "SELECT date, open, high, low, close, volume FROM daily_prices "
        "WHERE code = ? AND close > 0 ORDER BY date DESC LIMIT ?;",
        (code, limit),
    )
    rows = cursor.fetchall()
    rows.reverse()
    return rows


def build_chart(rows):
    """renderMaChart(index.html)가 그리는 형식: 봉마다 OHLCV + ma5/10/15/20."""
    closes = [float(r[4]) for r in rows]
    chart = []
    for i in range(max(0, len(rows) - CHART_BARS), len(rows)):
        date, o, h, l, c, v = rows[i]
        c = float(c)
        point = {
            'date': str(date).replace('-', ''),
            'open': float(o or c), 'high': float(h or c), 'low': float(l or c), 'close': c,
            'volume': int(v or 0),
        }
        for p in MA_PERIODS:
            point[f'ma{p}'] = round(sum(closes[i - p + 1:i + 1]) / p, 2) if i + 1 >= p else None
        chart.append(point)
    return chart


def analyze(code, info, rows):
    if len(rows) < min(MA_PERIODS):
        return None
    closes = [float(r[4]) for r in rows]
    close = closes[-1]
    mas, distances, near = {}, {}, []
    for period in MA_PERIODS:
        if len(closes) < period:
            continue
        ma = sum(closes[-period:]) / period
        dist = (close - ma) / ma
        mas[str(period)] = round(ma, 2)
        distances[str(period)] = round(dist * 100, 2)
        if abs(dist) <= NEAR_THRESHOLD:
            near.append(period)
    if not near:
        return None
    prev_close = closes[-2] if len(closes) >= 2 else close
    return {
        'code': code,
        'name': info['name'],
        'captured_dates': info['captured_dates'],
        'price_date': rows[-1][0],
        'close': close,
        'rate': round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0,
        'mas': mas,
        'distances': distances,
        'near': near,
        'chart': build_chart(rows),
    }


def main():
    if not os.path.exists(SCAN_HISTORY_PATH):
        print("[MA근접] scan_history.json이 없어 건너뜁니다.")
        return
    if not os.path.exists(DB_PATH):
        print("[MA근접] 시세 캐시 DB가 없어 건너뜁니다.")
        return

    with open(SCAN_HISTORY_PATH, 'r', encoding='utf-8') as f:
        scan_history = json.load(f)

    stocks = collect_v2_stocks(scan_history)
    print(f"[MA근접] 최근 v2 포착 종목: {len(stocks)}개 ({len(scan_history)}일치)")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    items = []
    for code, info in stocks.items():
        result = analyze(code, info, recent_rows(cursor, code))
        if result:
            items.append(result)
    conn.close()

    # 걸친 이평선이 많은 순 -> 가장 가까운 이평선과의 거리가 작은 순
    items.sort(key=lambda it: (-len(it['near']), min(abs(it['distances'][str(p)]) for p in it['near'])))

    kst_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)
    payload = {
        'generated_at': kst_now.strftime('%Y-%m-%d %H:%M'),
        'source_dates': sorted(scan_history.keys()),
        'threshold_pct': NEAR_THRESHOLD * 100,
        'ma_periods': list(MA_PERIODS),
        'total_v2_stocks': len(stocks),
        'items': items,
    }
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[MA근접] {len(items)}개 종목이 이평선 근처 -> ma_proximity.json 저장")


if __name__ == '__main__':
    main()
