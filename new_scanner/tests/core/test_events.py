from __future__ import annotations
from tests.conftest import make_ohlcv_df
from jusmo_scanner.config import load_config
from jusmo_scanner.scanner import features, events


def _cfg():
    return load_config("config/scanner.yaml")


def test_compute_event_price_is_typical_price():
    assert events.compute_event_price(high=110, low=90, close=100) == 100


def test_is_core_event_true_at_or_above_threshold():
    assert events.is_core_event(50_000_000_000, core_threshold=50_000_000_000) is True
    assert events.is_core_event(49_999_999_999, core_threshold=50_000_000_000) is False


def test_is_strong_event_requires_core_plus_value_ratio_or_turnover():
    cfg = _cfg()
    # core event, value_ratio 2x -> strong
    assert events.is_strong_event(
        trading_value=60_000_000_000, avg_trading_value_20=20_000_000_000, turnover=0.01,
        core_threshold=cfg.core_event_trading_value,
        value_ratio_min=cfg.strong_event_value_ratio_min,
        turnover_min=cfg.strong_event_turnover_min,
    ) is True
    # core event, neither ratio nor turnover met -> not strong
    assert events.is_strong_event(
        trading_value=60_000_000_000, avg_trading_value_20=100_000_000_000, turnover=0.01,
        core_threshold=cfg.core_event_trading_value,
        value_ratio_min=cfg.strong_event_value_ratio_min,
        turnover_min=cfg.strong_event_turnover_min,
    ) is False
    # not even a core event -> not strong regardless of ratio/turnover
    assert events.is_strong_event(
        trading_value=1_000_000_000, avg_trading_value_20=1_000, turnover=0.99,
        core_threshold=cfg.core_event_trading_value,
        value_ratio_min=cfg.strong_event_value_ratio_min,
        turnover_min=cfg.strong_event_turnover_min,
    ) is False


def test_detect_events_finds_only_bars_over_threshold():
    cfg = _cfg()
    rows = [{"trading_value": 1_000_000_000} for _ in range(25)]
    rows.append({"trading_value": 60_000_000_000})
    df = make_ohlcv_df(rows)
    df = features.compute_all_features(df)
    found = events.detect_events(df, ticker="TEST", cfg=cfg)
    assert len(found) == 1
    assert found[0].ticker == "TEST"
    assert found[0].trading_value == 60_000_000_000


import pandas as pd


def _make_event(ticker: str, date: str, trading_value: float = 60_000_000_000) -> events.Event:
    return events.Event(
        ticker=ticker, event_date=pd.Timestamp(date),
        open=100, high=110, low=90, close=105, volume=1000,
        trading_value=trading_value, turnover=0.1, value_ratio=2.0,
        capital_impact=0.05, location120=0.5, event_score=100.0,
        event_price=events.compute_event_price(110, 90, 105),
    )
