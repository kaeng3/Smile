from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

from jusmo_scanner.config import ScannerConfig


@dataclass
class Event:
    ticker: str
    event_date: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    trading_value: float
    turnover: float
    value_ratio: float
    capital_impact: float
    location120: float
    event_score: float
    event_price: float


def compute_event_price(high: float, low: float, close: float) -> float:
    return (high + low + close) / 3


def is_core_event(trading_value: float, core_threshold: float) -> bool:
    return trading_value >= core_threshold


def is_strong_event(
    trading_value: float,
    avg_trading_value_20: float,
    turnover: float,
    core_threshold: float,
    value_ratio_min: float,
    turnover_min: float,
) -> bool:
    if not is_core_event(trading_value, core_threshold):
        return False
    value_ratio_ok = (
        pd.notna(avg_trading_value_20)
        and avg_trading_value_20 > 0
        and (trading_value / avg_trading_value_20) >= value_ratio_min
    )
    turnover_ok = pd.notna(turnover) and turnover >= turnover_min
    return bool(value_ratio_ok or turnover_ok)


def detect_events(df: pd.DataFrame, ticker: str, cfg: ScannerConfig) -> list[Event]:
    found: list[Event] = []
    # Pure speed-up (identical output): rows below the core threshold (or NaN) can never
    # be events, so skip building a Series for each of them.
    candidates = df[pd.to_numeric(df["trading_value"], errors="coerce") >= cfg.core_event_trading_value]
    for _, row in candidates.iterrows():
        if not is_core_event(row["trading_value"], cfg.core_event_trading_value):
            continue
        strong = is_strong_event(
            row["trading_value"], row["AVG_TRADING_VALUE_20"], row["TURNOVER"],
            cfg.core_event_trading_value, cfg.strong_event_value_ratio_min,
            cfg.strong_event_turnover_min,
        )
        found.append(Event(
            ticker=ticker,
            event_date=row["date"],
            open=row["open"], high=row["high"], low=row["low"], close=row["close"],
            volume=row["volume"], trading_value=row["trading_value"],
            turnover=row["TURNOVER"], value_ratio=row["VALUE_RATIO"],
            capital_impact=row["CAPITAL_IMPACT"], location120=row["LOCATION120"],
            event_score=100.0 if strong else 50.0,
            event_price=compute_event_price(row["high"], row["low"], row["close"]),
        ))
    return found
