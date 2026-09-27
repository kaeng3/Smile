"""Deterministic synthetic OHLCV builders for backtest/snapshot tests.

Frames have columns: date, ticker, open, high, low, close, volume,
trading_value, market_cap, free_float_shares, name. No randomness except the
explicitly seeded `random_frame`.

Every fixture's claimed state path is asserted in tests/test_snapshot.py
(they were verified empirically against the engine, not derived by hand).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

BASE_TV = 1_000_000_000.0
MARKET_CAP = 100_000_000_000.0  # capital_impact = tv / mcap; harmless for states
FREE_FLOAT = 10_000_000.0


def _bar(close: float, *, open_: float | None = None, high: float | None = None,
         low: float | None = None, volume: float = 100_000.0, tv: float = BASE_TV) -> dict:
    o = close if open_ is None else open_
    h = max(o, close) + 5.0 if high is None else high
    lo = min(o, close) - 5.0 if low is None else low
    return {"open": o, "high": h, "low": lo, "close": close, "volume": volume, "trading_value": tv}


def to_frame(rows: list[dict], ticker: str = "SYN", name: str | None = "Synthetic Co",
             start: str = "2020-01-01") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df.insert(0, "date", pd.bdate_range(start=start, periods=len(rows)))
    df.insert(1, "ticker", ticker)
    df["market_cap"] = MARKET_CAP
    df["free_float_shares"] = FREE_FLOAT
    df["name"] = name
    return df.reset_index(drop=True)


def _drifting_base(n: int, start: float, end: float, tv: float = BASE_TV) -> list[dict]:
    rows = []
    for i in range(n):
        c = start + (end - start) * i / max(n - 1, 1) + 8.0 * math.sin(i * 0.7)
        vol = 100_000.0 * (1 + 0.1 * math.sin(i * 0.37))
        rows.append(_bar(c, volume=vol, tv=tv))
    return rows


# Indices inside success_frame (documented for tests).
SUCCESS_N_BASE = 270


def success_frame() -> pd.DataFrame:
    """Long quiet, gently falling base (>=260 bars so MA240 exists) -> large
    STRONG event -> low-volume dry-up (DORMANT) -> MA240 cross on modest volume
    (IGNITION) -> high-volume prior-high break (BREAKOUT) -> low-volume ~-7%
    pullback (PULLBACK) -> later +20% (state stays PULLBACK: no re-entry)."""
    rows = _drifting_base(SUCCESS_N_BASE, 1100.0, 900.0)
    rows[-100]["high"] = 1200.0  # bottom location, outside ATR20/HH60 windows
    # event bar (index 270)
    rows.append(_bar(940.0, open_=900.0, high=960.0, low=890.0, volume=600_000.0, tv=80e9))
    # dry-up: quiet, low volume, tight
    for k in range(15):
        rows.append(_bar(935.0 + 2.0 * math.sin(k), volume=40_000.0))
    # single jump through MA120 and MA240 (~978) on modest volume (rvol < 1.3, so
    # IGNITION rather than BREAKOUT); a gradual ramp would cross MA120 first
    rows.append(_bar(990.0, volume=60_000.0))
    rows.append(_bar(1000.0, volume=60_000.0))
    rows.append(_bar(1005.0, volume=60_000.0))
    # breakout: close above HH60, big volume
    rows.append(_bar(1100.0, open_=1010.0, high=1120.0, low=1005.0, volume=600_000.0))
    # low-volume pullback (-7.1% vs breakout high 1120)
    rows.append(_bar(1040.0, open_=1090.0, high=1095.0, low=1035.0, volume=100_000.0))
    for k in range(4):
        rows.append(_bar(1045.0 + 3.0 * k, volume=70_000.0))
    # later +20% advance
    for c in (1080.0, 1120.0, 1160.0, 1200.0, 1250.0):
        rows.append(_bar(c, volume=90_000.0))
    return to_frame(rows, ticker="SUCC")


def failure_frame() -> pd.DataFrame:
    """Event -> big bearish bar breaching the event low -> INVALIDATED, then
    quiet bars with no new event (no active episode, so no further results)."""
    rows = [_bar(1000.0 + 3.0 * math.sin(i), volume=100_000.0) for i in range(80)]
    rows.append(_bar(1000.0, open_=1000.0, high=1020.0, low=980.0, volume=500_000.0, tv=60e9))
    rows.append(_bar(1000.0, volume=60_000.0))
    rows.append(_bar(1000.0, volume=60_000.0))
    rows.append(_bar(880.0, open_=990.0, high=995.0, low=870.0, volume=300_000.0))  # bearish, breaches
    for k in range(6):
        rows.append(_bar(870.0 + k, volume=50_000.0))
    return to_frame(rows, ticker="FAIL")


def repeated_events_frame() -> pd.DataFrame:
    """One active episode with three events: a STRONG anchor, a CORE-only
    second event (value ratio < 2, turnover < 0.3) and a STRONG third one.
    Event volumes 500k / 400k / 900k (used by hand-checked VCR tests)."""
    rows = [_bar(1000.0 + 3.0 * math.sin(i), volume=100_000.0, tv=30e9) for i in range(80)]
    rows.append(_bar(1000.0, high=1020.0, low=980.0, volume=500_000.0, tv=100e9))      # idx 80 anchor
    for _ in range(4):
        rows.append(_bar(1000.0, high=1008.0, low=995.0, volume=60_000.0, tv=30e9))     # 81..84
    rows.append(_bar(1000.0, high=1015.0, low=970.0, volume=400_000.0, tv=60e9))       # idx 85 event 2
    for _ in range(19):
        rows.append(_bar(1000.0, high=1008.0, low=995.0, volume=60_000.0, tv=30e9))     # 86..104
    rows.append(_bar(1000.0, high=1030.0, low=960.0, volume=900_000.0, tv=200e9))      # idx 105 event 3
    for _ in range(6):
        rows.append(_bar(1000.0, high=1008.0, low=995.0, volume=60_000.0, tv=30e9))     # 106..111
    return to_frame(rows, ticker="MULTI")


def bottom_repeated_events_frame() -> pd.DataFrame:
    """Same event sequence with 45 extra past bars so LOCATION120 is known."""
    df = repeated_events_frame()
    prior = df.iloc[:45].copy()
    prior['date'] = pd.bdate_range(end=df.date.iloc[0] - pd.Timedelta(days=1), periods=45)
    prior.loc[prior.index[25], 'high'] = 1100.0
    return pd.concat([prior, df], ignore_index=True)


REPEATED_EVENT_BARS = (80, 85, 105)
REPEATED_EVENT_VOLUMES = (500_000.0, 400_000.0, 900_000.0)


def random_frame(seed: int, n: int = 320) -> pd.DataFrame:
    """Seeded random walk with random volume/trading-value spikes."""
    rng = np.random.RandomState(seed)
    close = 1000.0
    rows = []
    for _ in range(n):
        o = close
        close = max(50.0, close * (1 + rng.normal(0, 0.02)))
        hi = max(o, close) * (1 + abs(rng.normal(0, 0.008)))
        lo = min(o, close) * (1 - abs(rng.normal(0, 0.008)))
        spike = rng.rand() < 0.03
        vol = 100_000.0 * (1 + rng.rand()) * (6.0 if spike else 1.0)
        tv = (60e9 + rng.rand() * 40e9) if spike else 1e9 * (1 + rng.rand())
        rows.append({"open": o, "high": hi, "low": lo, "close": close, "volume": vol, "trading_value": tv})
    return to_frame(rows, ticker=f"RND{seed}")
