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
        return [str(row[0]) for row in rows]

    def ticker_metadata(self, ticker: str) -> dict[str, str]:
        return {"name": ticker}

    def get_ohlcv(self, ticker: str) -> pd.DataFrame:
        with sqlite3.connect(self._db_path) as conn:
            frame = pd.read_sql_query(
                "SELECT date, code AS ticker, open, high, low, close, volume FROM daily_prices WHERE code = ? ORDER BY date",
                conn, params=(ticker,),
            )
        if frame.empty:
            return frame
        frame["date"] = pd.to_datetime(frame["date"])
        frame["trading_value"] = frame["close"] * frame["volume"]
        frame["market_cap"] = pd.NA
        frame["free_float_shares"] = pd.NA
        return frame

    def close(self) -> None:
        return None
