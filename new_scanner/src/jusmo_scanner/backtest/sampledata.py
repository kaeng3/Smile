"""Deterministic SYNTHETIC OHLCV universe generator (for smoke tests / demos).

Nothing here is market data. The universe mixes seeded random walks with occasional
volume/trading-value spikes and a few hand-shaped patterns (event -> dormant ->
ignition -> breakout -> pullback; event -> invalidation; repeated events). CSVs are
written with a sidecar `meta.json` carrying `synthetic: true`, which makes the backtest
report state that the results are not market evidence.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BASE_TV = 1_000_000_000.0
MARKET_CAP = 100_000_000_000.0
FREE_FLOAT = 10_000_000.0
MIN_PATTERN_BARS = 320          # patterned tickers need >= 260 quiet bars for MA240 plus the pattern
PATTERNS = ("random", "success", "random", "failure", "random", "repeated")


def _bar(close: float, *, open_: float | None = None, high: float | None = None,
         low: float | None = None, volume: float = 100_000.0, tv: float = BASE_TV) -> dict:
    o = close if open_ is None else open_
    h = max(o, close) + 5.0 if high is None else high
    lo = min(o, close) - 5.0 if low is None else low
    return {"open": o, "high": h, "low": lo, "close": close, "volume": volume, "trading_value": tv}


def _frame(rows: list[dict], ticker: str, start: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df.insert(0, "date", pd.bdate_range(start=start, periods=len(rows)))
    df.insert(1, "ticker", ticker)
    df["market_cap"] = MARKET_CAP
    df["free_float_shares"] = FREE_FLOAT
    return df.reset_index(drop=True)


def _quiet_base(rng: np.random.RandomState, n: int, start: float, end: float) -> list[dict]:
    rows = []
    for i in range(n):
        c = start + (end - start) * i / max(n - 1, 1) + 8.0 * math.sin(i * 0.7) + rng.normal(0, 1.0)
        rows.append(_bar(c, volume=100_000.0 * (1 + 0.1 * math.sin(i * 0.37)), tv=BASE_TV))
    return rows


def random_walk(rng: np.random.RandomState, n: int, ticker: str, start: str) -> pd.DataFrame:
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
    return _frame(rows, ticker, start)


def success_pattern(rng: np.random.RandomState, n: int, ticker: str, start: str) -> pd.DataFrame:
    """Quiet base -> STRONG event -> dry-up -> MA jump (IGNITION) -> BREAKOUT -> PULLBACK -> advance."""
    tail = 29
    rows = _quiet_base(rng, n - tail - 1, 1100.0, 900.0)
    # A prior high inside LOCATION120 but outside HH60 makes the event a bottom setup.
    rows[-100]["high"] = 1200.0
    rows.append(_bar(940.0, open_=900.0, high=960.0, low=890.0, volume=600_000.0, tv=80e9))
    for k in range(15):
        rows.append(_bar(935.0 + 2.0 * math.sin(k), volume=40_000.0))
    rows += [_bar(990.0, volume=60_000.0), _bar(1000.0, volume=60_000.0), _bar(1005.0, volume=60_000.0)]
    rows.append(_bar(1100.0, open_=1010.0, high=1120.0, low=1005.0, volume=600_000.0))
    rows.append(_bar(1040.0, open_=1090.0, high=1095.0, low=1035.0, volume=100_000.0))
    for k in range(4):
        rows.append(_bar(1045.0 + 3.0 * k, volume=70_000.0))
    for c in (1080.0, 1120.0, 1160.0, 1200.0, 1250.0):
        rows.append(_bar(c, volume=90_000.0))
    rows = rows[-n:] if len(rows) > n else rows
    return _frame(rows, ticker, start)


def failure_pattern(rng: np.random.RandomState, n: int, ticker: str, start: str) -> pd.DataFrame:
    """Event -> bearish bar breaching the event low -> INVALIDATED, quiet afterwards."""
    tail = 10
    rows = [_bar(1000.0 + 3.0 * math.sin(i) + rng.normal(0, 1.0), volume=100_000.0) for i in range(n - tail)]
    rows.append(_bar(1000.0, open_=1000.0, high=1020.0, low=980.0, volume=500_000.0, tv=60e9))
    rows += [_bar(1000.0, volume=60_000.0), _bar(1000.0, volume=60_000.0)]
    rows.append(_bar(880.0, open_=990.0, high=995.0, low=870.0, volume=300_000.0))
    for k in range(6):
        rows.append(_bar(870.0 + k, volume=50_000.0))
    return _frame(rows[-n:], ticker, start)


def repeated_pattern(rng: np.random.RandomState, n: int, ticker: str, start: str) -> pd.DataFrame:
    """One episode with three events (STRONG / CORE / STRONG)."""
    quiet = lambda: _bar(1000.0, high=1008.0, low=995.0, volume=60_000.0, tv=30e9)  # noqa: E731
    rows = [_bar(1000.0 + 3.0 * math.sin(i) + rng.normal(0, 1.0), volume=100_000.0, tv=30e9)
            for i in range(n - 32)]
    rows.append(_bar(1000.0, high=1020.0, low=980.0, volume=500_000.0, tv=100e9))
    rows += [quiet() for _ in range(4)]
    rows.append(_bar(1000.0, high=1015.0, low=970.0, volume=400_000.0, tv=60e9))
    rows += [quiet() for _ in range(19)]
    rows.append(_bar(1000.0, high=1030.0, low=960.0, volume=900_000.0, tv=200e9))
    rows += [quiet() for _ in range(6)]
    return _frame(rows[-n:], ticker, start)


_BUILDERS = {"random": random_walk, "success": success_pattern, "failure": failure_pattern,
             "repeated": repeated_pattern}


def generate_universe(n_tickers: int = 30, n_bars: int = 1250, seed: int = 0,
                      start: str = "2018-01-01") -> dict[str, pd.DataFrame]:
    """`n_tickers` frames of `n_bars` bars, deterministic in (n_tickers, n_bars, seed).
    Ticker i uses pattern PATTERNS[i % 6] (random walk when n_bars is too short for a pattern)."""
    if n_tickers < 1 or n_bars < 30:
        raise ValueError("need at least 1 ticker and 30 bars")
    out: dict[str, pd.DataFrame] = {}
    for i in range(n_tickers):
        kind = PATTERNS[i % len(PATTERNS)]
        if kind != "random" and n_bars < MIN_PATTERN_BARS:
            kind = "random"
        rng = np.random.RandomState(seed * 100_003 + i)
        ticker = f"SYN{i:03d}"
        df = _BUILDERS[kind](rng, n_bars, ticker, start)
        assert len(df) == n_bars, (kind, len(df))
        out[ticker] = df
    return out


def write_csv_universe(out_dir: str | Path, n_tickers: int = 30, n_bars: int = 1250, seed: int = 0) -> list[Path]:
    """Writes the universe as `<ticker>.csv` plus `meta.json` ({"synthetic": true, ...})."""
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    written = []
    for ticker, df in generate_universe(n_tickers, n_bars, seed).items():
        p = path / f"{ticker}.csv"
        df.to_csv(p, index=False, date_format="%Y-%m-%d")
        written.append(p)
    (path / "meta.json").write_text(json.dumps({
        "synthetic": True, "generator": "jusmo_scanner.backtest.sampledata",
        "seed": seed, "tickers": n_tickers, "bars": n_bars,
        "note": "synthetic data: results are not market evidence"}, indent=2), encoding="utf-8")
    logger.info("wrote %d synthetic CSV files to %s", len(written), path)
    return written
