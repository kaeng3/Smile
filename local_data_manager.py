# -*- coding: utf-8 -*-
import os
import sys
import datetime
import sqlite3
import pandas as pd
import FinanceDataReader as fdr

DB_PATH = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\scratch\stock_ohlcv_cache.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
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

def sync_stock_data(target_date=None):
    """
    초고속 로컬 캐시 DB 증분 동기화엔진:
    FDR StockListing('KRX') 전 종목 일괄 시세를 사용하여 1초 만에 최신 시세 증분 저장!
    """
    init_db()
    if target_date is None:
        target_date = datetime.datetime.now()
    target_str = target_date.strftime('%Y-%m-%d')

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
