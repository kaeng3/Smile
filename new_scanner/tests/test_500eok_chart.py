from __future__ import annotations

import pandas as pd
import pytest

import run_daily as daily


def candle() -> pd.Series:
    return pd.Series({
        "open": 105.0,
        "high": 115.0,
        "low": 100.0,
        "close": 114.45,
        "trading_value": 50_000_000_000,
    })


def test_500eok_strong_candle_uses_nomad_price_conditions():
    assert daily._is_500eok_strong_candle(pd.Series({"close": 100.0}), candle()) is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trading_value", 49_999_999_999),
        ("close", 114.44),
        ("high", 114.99),
        ("low", 100.01),
    ],
)
def test_500eok_strong_candle_rejects_each_failed_condition(field, value):
    bar = candle()
    bar[field] = value
    assert daily._is_500eok_strong_candle(pd.Series({"close": 100.0}), bar) is False


def test_chart_marks_only_500eok_strong_candles():
    dates = pd.bdate_range(end="2026-09-25", periods=6)
    df = pd.DataFrame({
        "date": dates,
        "open": [100.0] * 6,
        "high": [101.0] * 6,
        "low": [99.0] * 6,
        "close": [100.0] * 6,
        "volume": [1000] * 6,
        "trading_value": [1e9] * 6,
    })
    df.loc[4, ["open", "high", "low", "close", "trading_value"]] = [105.0, 115.0, 100.0, 114.45, 50e9]
    df.loc[5, "trading_value"] = 80e9

    chart = daily._chart_points(df)

    assert chart[-2]["is_500eok"] is True
    assert chart[-1]["is_500eok"] is False
