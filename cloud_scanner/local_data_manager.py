# -*- coding: utf-8 -*-
import os
import sys
import datetime
import sqlite3
import concurrent.futures
import pandas as pd
import FinanceDataReader as fdr

base_dir = os.path.dirname(os.path.abspath(__file__))
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

def backfill_missing_days(target_date, max_gap_days=10):
    """
    DB의 마지막 저장일과 target_date 사이에 빠진 평일(거래일)이 있으면
    종목별로 개별 히스토리 조회를 병렬로 실행해서 채워 넣는다.
    (이걸 안 하면 등락률이 '어제-오늘'이 아니라 'N일전-오늘'로 계산되어
    실제보다 부풀려진 값이 나옴)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM daily_prices;")
    row = cursor.fetchone()
    conn.close()
    last_date_str = row[0] if row else None

    if not last_date_str:
        return  # DB가 완전히 비어있으면(최초 시드조차 없음) sync_stock_data가 오늘치만 채움

    last_date = datetime.datetime.strptime(last_date_str, '%Y-%m-%d')

    missing_dates = []
    d = last_date + datetime.timedelta(days=1)
    while d.date() < target_date.date():
        if d.weekday() < 5:  # 평일만 (공휴일까지는 걸러내지 못하지만 아래서 빈 결과는 자연스레 무시됨)
            missing_dates.append(d)
        d += datetime.timedelta(days=1)

    if not missing_dates:
        return

    if len(missing_dates) > max_gap_days:
        print(f"[DB 보정] 결측 거래일이 {len(missing_dates)}일로 너무 많아 자동 보정을 건너뜁니다. (수동 확인 필요)")
        return

    date_strs = [d.strftime('%Y-%m-%d') for d in missing_dates]
    print(f"[DB 보정] 결측 거래일 발견: {date_strs} → 종목별 히스토리로 채우는 중...")

    try:
        df_krx = fdr.StockListing('KRX')
        codes = df_krx[df_krx['Market'].isin(['KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL'])]['Code'].astype(str).tolist()
    except Exception as e:
        print("[DB 보정] 종목 리스트 조회 실패, 보정 중단:", e)
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
    try:
        df_krx = fdr.StockListing('KRX')
        df_filtered = df_krx[df_krx['Market'].isin(['KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL'])]
        
        all_records = []
        for _, row in df_filtered.iterrows():
            code = str(row['Code'])
            close = float(row.get('Close', 0) or 0)
            open_p = float(row.get('Open', close) or close)
            high_p = float(row.get('High', close) or close)
            low_p = float(row.get('Low', close) or close)
            vol = float(row.get('Volume', 0) or 0)
            if close > 0:
                all_records.append((code, target_str, open_p, high_p, low_p, close, vol))

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
            print(f"[초고속 DB 캐시] {len(all_records)}개 종목 시세 1초 만에 로컬 DB 반영 완료!")
    except Exception as e:
        print("시세 증분 저장 중 예외 (기존 DB 사용):", e)

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
    sync_stock_data()
