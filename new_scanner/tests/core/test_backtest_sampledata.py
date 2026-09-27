from __future__ import annotations

import pandas as pd
import pytest

from jusmo_scanner.backtest import sampledata
from jusmo_scanner.backtest.sampledata import generate_universe, write_csv_universe
from jusmo_scanner.data.csv_provider import CSVProvider
from jusmo_scanner.data.base import REQUIRED_COLUMNS
from jusmo_scanner.config import load_config
from jusmo_scanner.scanner import engine

CFG = load_config("config/scanner.yaml")


def test_universe_is_deterministic_and_seed_dependent():
    a, b, c = generate_universe(6, 400, 1), generate_universe(6, 400, 1), generate_universe(6, 400, 2)
    assert list(a) == list(b) == [f"SYN{i:03d}" for i in range(6)]
    for k in a:
        pd.testing.assert_frame_equal(a[k], b[k])
    assert not a["SYN000"].equals(c["SYN000"])


def test_frames_are_valid_scanner_input():
    for t, df in generate_universe(6, 400, 3).items():
        assert len(df) == 400 and set(REQUIRED_COLUMNS) <= set(df.columns)
        assert df["date"].is_monotonic_increasing and df["date"].is_unique
        assert (df[["open", "high", "low", "close"]] > 0).all().all()
        assert (df["high"] >= df[["open", "close"]].max(axis=1) - 1e-9).all()
        engine.prepare_ticker(df, CFG.breakout_swing_window)


def test_patterns_reach_their_states():
    u = generate_universe(6, 400, 1)
    states = {t: {s.state for s in engine.scan_ticker(df, t, CFG, collect_snapshots=True).snapshots}
              for t, df in u.items()}
    assert {"BREAKOUT", "PULLBACK"} <= states["SYN001"]          # success pattern
    assert "INVALIDATED" in states["SYN003"]                     # failure pattern
    scan = engine.scan_ticker(u["SYN005"], "SYN005", CFG, collect_snapshots=True)
    assert max(s.event_count_so_far for s in scan.snapshots) >= 3  # repeated events


def test_short_universe_falls_back_to_random_walks():
    u = generate_universe(6, 100, 0)
    assert all(len(df) == 100 for df in u.values())
    with pytest.raises(ValueError):
        generate_universe(0, 400)
    with pytest.raises(ValueError):
        generate_universe(3, 10)


def test_write_csv_universe_round_trips_and_marks_synthetic(tmp_path):
    paths = write_csv_universe(tmp_path, 3, 330, 5)
    assert len(paths) == 3
    p = CSVProvider(tmp_path)
    assert p.is_synthetic is True and p.get_tickers() == ["SYN000", "SYN001", "SYN002"]
    df = p.get_ohlcv("SYN001")
    ref = generate_universe(3, 330, 5)["SYN001"]
    assert len(df) == 330
    pd.testing.assert_series_equal(df["close"], ref["close"], check_names=False, rtol=1e-12)
    assert sampledata.MIN_PATTERN_BARS == 320
    assert CSVProvider("tests/fixtures").is_synthetic is False
