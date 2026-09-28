from __future__ import annotations

import sqlite3

import pandas as pd

from jusmo_scanner.config import load_config
from jusmo_scanner.data.sqlite_market_provider import SQLiteMarketProvider
from jusmo_scanner.scanner.engine import scan_ticker


def test_missing_market_data_does_not_crash_event_scan(tmp_path):
    db_path = tmp_path / "market.db"
    rows = [
        (
            (pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).date().isoformat(),
            "TEST", 1000.0, 1010.0, 990.0, 1000.0, 100_000.0,
        )
        for i in range(35)
    ]
    rows += [
        (
            "2026-02-05", "TEST", 1000.0, 1020.0, 980.0,
            1000.0, 60_000_000.0,
        ),
    ]
    rows += [
        (
            (pd.Timestamp("2026-02-06") + pd.Timedelta(days=i)).date().isoformat(),
            "TEST", 1000.0, 1010.0, 990.0, 1000.0, 100_000.0,
        )
        for i in range(5)
    ]

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE daily_prices (
                date TEXT, code TEXT, open REAL, high REAL, low REAL,
                close REAL, volume REAL
            )
        """)
        conn.execute("CREATE TABLE ticker_metadata (code TEXT, name TEXT)")
        conn.execute("INSERT INTO ticker_metadata VALUES ('TEST', 'Test')")
        conn.executemany("INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?)", rows)

    provider = SQLiteMarketProvider(db_path, "2026-02-10")
    frame = provider.get_ohlcv("TEST")

    assert frame["market_cap"].isna().all()
    result = scan_ticker(frame, "TEST", load_config("config/scanner.yaml"))
    assert result.events
