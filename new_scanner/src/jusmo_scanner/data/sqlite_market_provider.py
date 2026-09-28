from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from .base import DataProvider, PriceAdjustmentMode, ShareCountBasis


class SQLiteMarketProvider(DataProvider):
    """Read the shared cloud scanner OHLCV cache."""

    def __init__(
        self,
        db_path: str | Path,
        target_date: str,
        name_map_path: str | Path | None = None,
    ):
        self._db_path = Path(db_path)
        self._target_date = target_date
        self._name_map = self._load_name_map(name_map_path)

    @staticmethod
    def _load_name_map(path: str | Path | None) -> dict[str, str]:
        if path is None:
            return {}
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        names: dict[str, str] = {}
        for code, value in raw.items():
            name = value.get("name") if isinstance(value, dict) else value
            if isinstance(name, str) and name.strip():
                names[str(code)] = name.strip()
        return names

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
        db_name = str(row[0]).strip() if row and row[0] else ""
        if db_name and db_name != ticker:
            return {"name": db_name}
        return {"name": self._name_map.get(ticker, ticker)}

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
        frame = frame.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
        if frame.empty:
            return frame
        frame["trading_value"] = frame["close"] * frame["volume"]
        # Keep missing optional market data numeric. pd.NA creates an object-dtype value
        # that fails inside numeric scoring when an event is present.
        frame["market_cap"] = float("nan")
        frame["free_float_shares"] = float("nan")
        return frame

    def close(self) -> None:
        return None
