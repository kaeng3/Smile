# tests/test_accumulation.py
from __future__ import annotations
import math
import pandas as pd
from tests.conftest import make_ohlcv_df
from jusmo_scanner.scanner import accumulation


def test_typical_price():
    assert accumulation.compute_typical_price(high=110, low=90, close=100) == 100


def test_estimated_cost_blends_event_price_and_vwap():
    cost = accumulation.compute_estimated_cost(
        event_price=100, anchored_vwap=110, weight_event=0.4, weight_vwap=0.6,
    )
    assert cost == 0.4 * 100 + 0.6 * 110


def test_cost_distance_positive_when_above_cost():
    d = accumulation.compute_cost_distance(close=110, estimated_cost=100)
    assert d == pytest_approx_helper(0.10)


def pytest_approx_helper(x):
    from pytest import approx
    return approx(x)


def test_cost_distance_nan_when_estimated_cost_zero():
    assert math.isnan(accumulation.compute_cost_distance(close=110, estimated_cost=0))


def test_vcr_is_avg_volume_5_over_event_volume():
    assert accumulation.compute_vcr(avg_volume_5=500, event_volume=2000) == 0.25


def test_vcr_nan_when_event_volume_zero():
    assert math.isnan(accumulation.compute_vcr(avg_volume_5=500, event_volume=0))


def test_event_low_limit_and_hold():
    limit = accumulation.compute_event_low_limit(event_low=1000, atr20=20, tolerance=1.0)
    assert limit == 980
    assert accumulation.is_event_low_hold(close=985, event_low_limit=limit) is True
    assert accumulation.is_event_low_hold(close=975, event_low_limit=limit) is False


def test_estimated_cost_hold_true_within_two_atr_below_cost():
    assert accumulation.is_estimated_cost_hold(
        close=960, estimated_cost=1000, atr20=20, invalidation_multiplier=2.0,
    ) is True  # 1000 - 40 = 960, close == boundary -> hold
    assert accumulation.is_estimated_cost_hold(
        close=959, estimated_cost=1000, atr20=20, invalidation_multiplier=2.0,
    ) is False
