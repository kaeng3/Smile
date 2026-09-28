from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .base import DataProvider, PriceAdjustmentMode, ShareCountBasis


class SQLiteMarketProvider(DataProvider):
    """Read the shared cloud scanner OHLCV cache."""

    def __init__(self, db_path: str | Path, target_date: str):
        self._db_path = Path(db_path)
        self._target_date = target_date

    @property
    def price_adjustment_mode(self) -> PriceAdjustmentMode:
        return PriceAdjustmentMode.UNKNOWN

    @property
    def share_count_basis(self) -> ShareCountBasis:
        return ShareCountBasis.UNKNOWN

    def get_tickers(self) -> list[str]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT DISTINCT code FROM daily_prices ORDER BY code").fetchall()
        return [str(row[0]) for row in rows if row[0] is not None]

    def ticker_metadata(self, ticker: str) -> dict[str, str]:
        with sqlite3.connect(self._db_path) as conn:
            try:
                row = conn.execute("SELECT name FROM ticker_metadata WHERE code = ?", (ticker,)).fetchone()
            except sqlite3.OperationalError:
                row = None
        return {"name": row[0] if row and row[0] else ticker}

    def get_ohlcv(self, ticker: str) -> pd.DataFrame:
        with sqlite3.connect(self._db_path) as conn:
            frame = pd.read_sql_query("""
                SELECT date, code AS ticker, open, high, low, close, volume
                FROM daily_prices WHERE code = ? ORDER BY date
                """, conn, params=(ticker,))
        if frame.empty:
            return frame
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["date", "close", "volume"]).copy()
        if frame.empty:
            return frame
        frame["trading_value"] = frame["close"] * frame["volume"]
        frame["market_cap"] = pd.NA
        frame["free_float_shares"] = pd.NA
        return frame

    def close(self) -> None:
        return None
