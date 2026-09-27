from __future__ import annotations
import pandas as pd

DEFAULT_MA_WINDOWS = [5, 10, 20, 60, 120, 240]
DEFAULT_SLOPE_WINDOWS = [5, 20, 60, 240]


def add_moving_averages(df: pd.DataFrame, windows: list[int] = DEFAULT_MA_WINDOWS) -> pd.DataFrame:
    df = df.copy()
    for w in windows:
        df[f"MA{w}"] = df["close"].rolling(window=w).mean()
    return df


def add_ma_slopes(df: pd.DataFrame, windows: list[int] = DEFAULT_SLOPE_WINDOWS) -> pd.DataFrame:
    df = df.copy()
    for w in windows:
        col = f"MA{w}"
        df[f"MA{w}_SLOPE"] = df[col] - df[col].shift(1)
    return df


def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["AVG_VOLUME_5"] = df["volume"].shift(1).rolling(5).mean()
    df["AVG_VOLUME_20"] = df["volume"].shift(1).rolling(20).mean()
    df["AVG_VOLUME_60"] = df["volume"].shift(1).rolling(60).mean()
    avg20 = df["AVG_VOLUME_20"].where(df["AVG_VOLUME_20"] != 0, pd.NA)
    df["RVOL20"] = df["volume"] / avg20
    return df


def add_trading_value_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    fallback = df["close"] * df["volume"]
    if "trading_value" not in df.columns:
        df["trading_value"] = fallback
    else:
        df["trading_value"] = pd.to_numeric(df["trading_value"], errors="coerce").fillna(fallback)
    df["AVG_TRADING_VALUE_20"] = df["trading_value"].shift(1).rolling(20).mean()
    avg20 = df["AVG_TRADING_VALUE_20"].where(df["AVG_TRADING_VALUE_20"] != 0, pd.NA)
    df["VALUE_RATIO"] = df["trading_value"] / avg20
    return df


def add_turnover(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    free_float = df["free_float_shares"].where(df["free_float_shares"] != 0, pd.NA)
    df["TURNOVER"] = df["volume"] / free_float
    return df


CHANNEL_WINDOWS = [10, 20, 60, 120]


def add_atr(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    df = df.copy()
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["ATR20"] = tr.rolling(window).mean()
    return df


def add_high_low_channels(df: pd.DataFrame, windows: list[int] = CHANNEL_WINDOWS) -> pd.DataFrame:
    """HHw/LLw are the highest-high / lowest-low over the w bars STRICTLY
    BEFORE the current bar (shift(1) before rolling) — the current bar is
    never used to compute its own channel, preventing look-ahead bias."""
    df = df.copy()
    for w in windows:
        df[f"HH{w}"] = df["high"].shift(1).rolling(w).max()
        df[f"LL{w}"] = df["low"].shift(1).rolling(w).min()
    return df


def add_location120(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    raw_span = df["HH120"] - df["LL120"]
    span = raw_span.where(raw_span != 0, pd.NA)
    df["LOCATION120"] = (df["close"] - df["LL120"]) / span
    return df


def add_range10(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    ll10 = df["LL10"].where(df["LL10"] != 0, pd.NA)
    df["RANGE10"] = (df["HH10"] - df["LL10"]) / ll10
    return df


def add_candle_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    full_range = (df["high"] - df["low"]).where((df["high"] - df["low"]) != 0, pd.NA)
    body = (df["close"] - df["open"]).abs()
    df["BODY_RATIO"] = body / full_range
    df["CLOSE_LOCATION"] = (df["close"] - df["low"]) / full_range
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    df["UPPER_WICK_RATIO"] = upper_wick / full_range
    return df


def add_capital_impact(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    market_cap = df["market_cap"].where(df["market_cap"] != 0, pd.NA)
    df["CAPITAL_IMPACT"] = df["trading_value"] / market_cap
    return df


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    df = add_moving_averages(df)
    df = add_ma_slopes(df)
    df = add_volume_features(df)
    df = add_trading_value_features(df)
    df = add_turnover(df)
    df = add_atr(df)
    df = add_high_low_channels(df)
    df = add_location120(df)
    df = add_range10(df)
    df = add_candle_features(df)
    df = add_capital_impact(df)
    return df
