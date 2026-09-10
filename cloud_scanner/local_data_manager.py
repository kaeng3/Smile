# -*- coding: utf-8 -*-
import os
import sys
import datetime
import time
import sqlite3
import concurrent.futures
import pandas as pd
import FinanceDataReader as fdr

base_dir = os.path.dirname(os.path.abspath(__file__))


def fetch_krx_listing_with_retry(max_attempts=2, wait_seconds=30):
    """
    FinanceDataReader는 KRX 로그인 정책 변경 이후 자체 GitHub 캐시
    (FinanceData/fdr_krx_data_cache)에서 그날 데이터를 읽어오는데,
    이 캐시가 당일 데이터를 늦게 올리거나 며칠씩 누락하는 알려진 문제가 있다
    (FinanceDataReader 이슈 #276 등). 짧게만 재시도하고, 계속 실패하면
    호출부에서 종목별 네이버 조회(fetch_stock_prices_via_naver)로 대체한다.
    """
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fdr.StockListing('KRX')
        except Exception as e:
            last_err = e
            print(f"[fetch_krx_listing_with_retry] 시도 {attempt}/{max_attempts} 실패: {e}")
            if attempt < max_attempts:
                print(f"  -> {wait_seconds}초 후 재시도합니다 (FDR의 KRX 데이터 캐시가 아직 갱신 안 됐을 수 있음)...")
                time.sleep(wait_seconds)
    raise last_err
DB_PATH = os.path.join(base_dir, "stock_ohlcv_cache.db")
if not os.path.exists(os.path.dirname(DB_PATH)):
    DB_PATH = os.path.join(base_dir, "stock_ohlcv_cache.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        pass
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            code TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (code, date)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_code_date ON daily_prices(code, date);")
    conn.commit()
    conn.close()

def get_stock_codes_fallback():
    """
    fetch_krx_listing_with_retry()가 실패했을 때(예: FDR의 GitHub 캐시 저장소가
    며칠째 갱신 안 됨) 쓰는 대체 종목 코드 목록. 로컬 DB에 이미 쌓여있는
    종목 코드를 그대로 쓴다(상장 종목 구성은 거의 매일 바뀌지 않으므로 충분히 안전).
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT code FROM daily_prices;")
        codes = [row[0] for row in cursor.fetchall()]
        conn.close()
        if codes:
            print(f"[대체 종목목록] 로컬 DB 기준 {len(codes)}개 종목 코드 사용")
        return codes
    except Exception as e:
        print("[대체 종목목록] 로컬 DB 조회도 실패:", e)
        return []


def fetch_stock_prices_via_naver(codes, target_date_str, max_workers=20):
    """
    fdr.DataReader(code, ...)는 KRX 종목코드일 때 네이버 시세를 소스로 쓰기 때문에,
    FDR의 GitHub 캐시 저장소 문제(전종목 일괄조회 fdr.StockListing('KRX')가 참조)와
    무관하게 항상 동작한다. 전종목 일괄조회가 막혔을 때 이걸로 종목별 병렬 조회해서
    같은 결과(오늘자 OHLCV)를 얻는다. 개별 호출이라 일괄조회보다는 느리다.
    """
    records = []

    def fetch_one(code):
        try:
            df = fdr.DataReader(code, target_date_str, target_date_str)
            if df.empty:
                return None
            row = df.iloc[-1]
            close = float(row.get('Close', 0) or 0)
            if close <= 0:
                return None
            return (
                code, target_date_str,
                float(row.get('Open', close) or close),
                float(row.get('High', close) or close),
                float(row.get('Low', close) or close),
                close,
                float(row.get('Volume', 0) or 0),
            )
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for rec in ex.map(fetch_one, codes):
            if rec:
                records.append(rec)

    return records


def backfill_missing_days(target_date, max_gap_days=10, lookback_days=20):
    """
    최근 lookback_days 범위의 평일들을 하나씩 체크해서, 종목 수 기준
    (1000개 미만) '사실상 비어있는' 날짜가 있으면 종목별 히스토리로 채운다.
    (기존에는 MAX(date) 기준으로만 봐서 중간에 낀 결측일을 못 찾는 버그가 있었음:
     예) ...8/4, [8/5 결측], 8/6 이 이미 있으면 MAX(date)=8/6이라 8/5를 못 찾음)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    missing_dates = []
    d = target_date - datetime.timedelta(days=lookback_days)
    while d.date() < target_date.date():
        if d.weekday() < 5:  # 평일만
            date_str = d.strftime('%Y-%m-%d')
            cursor.execute("SELECT COUNT(*) FROM daily_prices WHERE date = ?;", (date_str,))
            count = cursor.fetchone()[0]
            if count < 1000:
                missing_dates.append(d)
        d += datetime.timedelta(days=1)
    conn.close()

    if not missing_dates:
        return

    if len(missing_dates) > max_gap_days:
        print(f"[DB 보정] 결측 거래일이 {len(missing_dates)}일로 너무 많아 자동 보정을 건너뜁니다. (수동 확인 필요)")
        return

    date_strs = [d.strftime('%Y-%m-%d') for d in missing_dates]
    print(f"[DB 보정] 결측 거래일 발견: {date_strs} → 종목별 히스토리로 채우는 중...")

    try:
        df_krx = fetch_krx_listing_with_retry(max_attempts=2, wait_seconds=30)
        codes = df_krx[df_krx['Market'].isin(['KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL'])]['Code'].astype(str).tolist()
    except Exception as e:
        print("[DB 보정] 전종목 일괄조회 실패, 로컬 DB 종목목록으로 대체:", e)
        codes = get_stock_codes_fallback()
        if not codes:
            print("[DB 보정] 대체 종목목록도 없어 보정 중단")
            return

    start_str = missing_dates[0].strftime('%Y-%m-%d')
    end_str = missing_dates[-1].strftime('%Y-%m-%d')

    def fetch_one(code):
        recs = []
        try:
            df = fdr.DataReader(code, start_str, end_str)
            for idx, r in df.iterrows():
                close = float(r.get('Close', 0) or 0)
                if close > 0:
                    recs.append((
                        code, idx.strftime('%Y-%m-%d'),
                        float(r.get('Open', close) or close),
                        float(r.get('High', close) or close),
                        float(r.get('Low', close) or close),
                        close,
                        float(r.get('Volume', 0) or 0),
                    ))
        except Exception:
            pass
        return recs

    all_records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        for recs in ex.map(fetch_one, codes):
            all_records.extend(recs)

    if all_records:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("BEGIN TRANSACTION;")
        cursor.executemany("""
            INSERT OR REPLACE INTO daily_prices (code, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, all_records)
        conn.commit()
        conn.close()
        print(f"[DB 보정] {len(all_records)}건 보정 완료 ({len(codes)}개 종목 x {len(missing_dates)}일)")
    else:
        print("[DB 보정] 보정할 데이터를 찾지 못했습니다 (공휴일이었을 수 있음).")


def prune_old_data(target_date, days_to_keep=430):
    """
    오래된 시세 데이터 정리:
    load_cached_stock_dfs()가 실제로 읽는 구간은 target_date 기준 최근 400일뿐이라
    그보다 오래된 행은 어떤 스캔 로직에서도 쓰이지 않음. 여유 30일을 더해
    430일 이전 데이터는 삭제해서 DB 용량이 무한정 커지는 것을 방지한다.
    (양음양/v2/포도시가 요구하는 최대 500거래일치 ≈ 달력일 400일보다 넉넉함)
    """
    cutoff_str = (target_date - datetime.timedelta(days=days_to_keep)).strftime('%Y-%m-%d')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM daily_prices WHERE date < ?;", (cutoff_str,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    if deleted:
        print(f"[DB 정리] {cutoff_str} 이전 데이터 {deleted}건 삭제 완료 (용량 관리)")

def sync_stock_data(target_date=None):
    """
    초고속 로컬 캐시 DB 증분 동기화엔진:
    FDR StockListing('KRX') 전 종목 일괄 시세를 사용하여 1초 만에 최신 시세 증분 저장!
    """
    init_db()
    if target_date is None:
        target_date = datetime.datetime.now()
    target_str = target_date.strftime('%Y-%m-%d')

    prune_old_data(target_date)
    backfill_missing_days(target_date)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM daily_prices WHERE date = ?;", (target_str,))
    count = cursor.fetchone()[0]
    conn.close()

    if count >= 1000:
        print(f"[초고속 DB 캐시] 오늘({target_str}) 전 종목 시세가 이미 로컬 DB에 완벽히 저장되어 있습니다. (0초 통과)")
        return

    print(f"[초고속 DB 캐시] {target_str} 전 종목 최신 시세 1초 일괄 증분 획득 중...")
    all_records = []
    try:
        df_krx = fetch_krx_listing_with_retry()
        df_filtered = df_krx[df_krx['Market'].isin(['KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL'])]

        for _, row in df_filtered.iterrows():
            code = str(row['Code'])
            close = float(row.get('Close', 0) or 0)
            open_p = float(row.get('Open', close) or close)
            high_p = float(row.get('High', close) or close)
            low_p = float(row.get('Low', close) or close)
            vol = float(row.get('Volume', 0) or 0)
            if close > 0:
                all_records.append((code, target_str, open_p, high_p, low_p, close, vol))
    except Exception as e:
        print("[초고속 DB 캐시] 전종목 일괄조회 실패, 종목별 네이버 조회로 대체:", e)
        codes = get_stock_codes_fallback()
        if codes:
            all_records = fetch_stock_prices_via_naver(codes, target_str)
            print(f"[대체 경로] 종목별 네이버 조회로 {len(all_records)}건 확보")
        else:
            print("[대체 경로] 대체 종목목록도 없어 오늘자 증분 실패 (기존 DB 사용)")

    if all_records:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("BEGIN TRANSACTION;")
        cursor.executemany("""
            INSERT OR REPLACE INTO daily_prices (code, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, all_records)
        conn.commit()
        conn.close()
        print(f"[초고속 DB 캐시] {len(all_records)}개 종목 시세 로컬 DB 반영 완료!")

def load_cached_stock_dfs(target_date):
    target_str = target_date.strftime('%Y-%m-%d')
    start_str = (target_date - datetime.timedelta(days=400)).strftime('%Y-%m-%d')

    conn = get_db_connection()
    query = """
        SELECT code, date, open, high, low, close, volume
        FROM daily_prices
        WHERE date >= ? AND date <= ?
        ORDER BY code, date ASC;
    """
    df_all = pd.read_sql_query(query, conn, params=(start_str, target_str))
    conn.close()

    stock_dfs = {}
    if not df_all.empty:
        df_all['date'] = pd.to_datetime(df_all['date'])
        for code, group in df_all.groupby('code'):
            group = group.set_index('date').sort_index()
            group.columns = ['Code', 'Open', 'High', 'Low', 'Close', 'Volume']
            stock_dfs[code] = group

    return stock_dfs

if __name__ == '__main__':
    if os.environ.get('PRICE_DEBUG') == '1':
        import json as _json
        conn = get_db_connection()
        cur = conn.cursor()
        out = {}
        for code in ['214680', '006490', '005930']:
            cur.execute("SELECT date, close, volume FROM daily_prices WHERE code=? ORDER BY date DESC LIMIT 15;", (code,))
            out[code] = cur.fetchall()
        cur.execute("SELECT MAX(date), MIN(date), COUNT(DISTINCT date) FROM daily_prices;")
        out['_db_summary'] = cur.fetchone()
        cur.execute("SELECT date, COUNT(*) FROM daily_prices GROUP BY date ORDER BY date DESC LIMIT 15;")
        out['_date_counts'] = cur.fetchall()
        conn.close()
        with open(os.path.join(base_dir, '..', 'price_debug.json'), 'w', encoding='utf-8') as f:
            _json.dump(out, f, ensure_ascii=False, indent=2)
        print("[PRICE_DEBUG] 저장 완료")
    else:
        sync_stock_data()
