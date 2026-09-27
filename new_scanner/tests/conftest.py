from __future__ import annotations
import pandas as pd


def make_ohlcv_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame for tests. Each row dict may omit
    trading_value/market_cap/free_float_shares; sensible defaults are filled in
    so tests only need to specify the fields relevant to what they're checking."""
    defaults = {
        "ticker": "TEST",
        "open": 1000.0,
        "high": 1050.0,
        "low": 950.0,
        "close": 1000.0,
        "volume": 100000.0,
        "trading_value": 100000.0 * 1000.0,
        "market_cap": 100_000_000_000.0,
        "free_float_shares": 10_000_000.0,
    }
    filled = []
    for i, row in enumerate(rows):
        merged = {**defaults, **row}
        if "date" not in merged:
            merged["date"] = pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)
        filled.append(merged)
    df = pd.DataFrame(filled)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)
