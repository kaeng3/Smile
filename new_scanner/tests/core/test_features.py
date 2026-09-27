from __future__ import annotations
import pandas as pd
from pytest import approx as pytest_approx
from tests.conftest import make_ohlcv_df
from jusmo_scanner.scanner import features


def test_moving_averages_match_pandas_rolling_mean():
    df = make_ohlcv_df([{"close": c} for c in range(1, 31)])
    out = features.add_moving_averages(df, windows=[5])
    expected = df["close"].rolling(5).mean()
    pd.testing.assert_series_equal(out["MA5"], expected, check_names=False)


def test_add_moving_averages_does_not_mutate_input():
    df = make_ohlcv_df([{"close": c} for c in range(1, 10)])
    original_columns = list(df.columns)
    features.add_moving_averages(df, windows=[5])
    assert list(df.columns) == original_columns


def test_ma_slope_is_difference_from_prior_bar():
    df = make_ohlcv_df([{"close": c} for c in [10] * 9 + [20]])
    out = features.add_moving_averages(df, windows=[5])
    out = features.add_ma_slopes(out, windows=[5])
    assert out["MA5_SLOPE"].iloc[8] == 0
    assert out["MA5_SLOPE"].iloc[9] > 0


def test_rvol20_is_volume_over_avg_volume_20():
    rows = [{"volume": 1000} for _ in range(20)] + [{"volume": 4000}]
    df = make_ohlcv_df(rows)
    out = features.add_volume_features(df)
    assert out["RVOL20"].iloc[-1] == 4.0


def test_value_ratio_uses_close_times_volume_fallback():
    rows = [{"close": 100, "volume": 1000, "trading_value": None} for _ in range(20)]
    rows.append({"close": 100, "volume": 5000, "trading_value": None})
    df = make_ohlcv_df(rows)
    df["trading_value"] = pd.NA
    out = features.add_trading_value_features(df)
    assert out["trading_value"].iloc[-1] == 100 * 5000
    assert out["VALUE_RATIO"].iloc[-1] == 5.0


def test_turnover_is_volume_over_free_float():
    df = make_ohlcv_df([{"volume": 300000, "free_float_shares": 1000000}])
    out = features.add_turnover(df)
    assert out["TURNOVER"].iloc[0] == 0.3


def test_turnover_is_nan_when_free_float_is_zero():
    df = make_ohlcv_df([{"volume": 300000, "free_float_shares": 0}])
    out = features.add_turnover(df)
    assert pd.isna(out["TURNOVER"].iloc[0])


def test_hh_ll_channel_excludes_current_bar_look_ahead():
    # A huge spike on the LAST bar must not appear in that same bar's HH10 —
    # HH10 reflects only the 10 bars BEFORE it (shift(1) applied).
    rows = [{"high": 100, "low": 90} for _ in range(10)]
    rows.append({"high": 99999, "low": 90})
    df = make_ohlcv_df(rows)
    out = features.add_high_low_channels(df)
    assert out["HH10"].iloc[-1] == 100
    assert out["HH10"].iloc[-1] != 99999


def test_hh_ll_channel_includes_bar_on_next_day():
    rows = [{"high": 100, "low": 90} for _ in range(10)]
    rows.append({"high": 99999, "low": 90})
    rows.append({"high": 100, "low": 90})
    df = make_ohlcv_df(rows)
    out = features.add_high_low_channels(df)
    assert out["HH10"].iloc[-1] == 99999


def test_atr20_is_nan_for_insufficient_history_new_listing():
    # bug #14: newly listed ticker with only 5 days of history
    rows = [{"high": 105, "low": 95, "close": 100} for _ in range(5)]
    df = make_ohlcv_df(rows)
    out = features.add_atr(df, window=20)
    assert out["ATR20"].isna().all()


def test_location120_between_zero_and_one_at_channel_extremes():
    rows = [{"high": 100, "low": 90, "close": 95} for _ in range(120)]
    rows.append({"high": 100, "low": 90, "close": 100})
    df = make_ohlcv_df(rows)
    out = features.add_high_low_channels(df)
    out = features.add_location120(out)
    assert 0 <= out["LOCATION120"].iloc[-1] <= 1.01


def test_range10_is_nan_not_crash_when_ll10_is_zero():
    rows = [{"high": 0, "low": 0, "close": 0} for _ in range(11)]
    df = make_ohlcv_df(rows)
    out = features.add_high_low_channels(df)
    out = features.add_range10(out)
    assert pd.isna(out["RANGE10"].iloc[-1])


def test_candle_features_on_normal_bar():
    df = make_ohlcv_df([{"open": 100, "high": 120, "low": 90, "close": 110}])
    out = features.add_candle_features(df)
    assert out["BODY_RATIO"].iloc[0] == pytest_approx(10 / 30)
    assert out["CLOSE_LOCATION"].iloc[0] == pytest_approx(20 / 30)
    assert out["UPPER_WICK_RATIO"].iloc[0] == pytest_approx(10 / 30)


def test_candle_features_halted_stock_zero_range_no_crash():
    # bug #13: trading-halted bar has open==high==low==close, high-low == 0
    df = make_ohlcv_df([{"open": 100, "high": 100, "low": 100, "close": 100}])
    out = features.add_candle_features(df)
    assert pd.isna(out["BODY_RATIO"].iloc[0])
    assert pd.isna(out["CLOSE_LOCATION"].iloc[0])
    assert pd.isna(out["UPPER_WICK_RATIO"].iloc[0])


def test_capital_impact_is_trading_value_over_market_cap():
    df = make_ohlcv_df([{"trading_value": 5_000_000_000, "market_cap": 100_000_000_000}])
    out = features.add_capital_impact(df)
    assert out["CAPITAL_IMPACT"].iloc[0] == pytest_approx(0.05)


def test_capital_impact_is_nan_when_market_cap_zero():
    df = make_ohlcv_df([{"trading_value": 5_000_000_000, "market_cap": 0}])
    out = features.add_capital_impact(df)
    assert pd.isna(out["CAPITAL_IMPACT"].iloc[0])


def test_compute_all_features_runs_full_pipeline_without_crashing():
    rows = [{"close": 1000 + i, "high": 1010 + i, "low": 990 + i, "open": 1000 + i,
             "volume": 100000} for i in range(150)]
    df = make_ohlcv_df(rows)
    out = features.compute_all_features(df)
    for col in ["MA5", "MA240", "RVOL20", "VALUE_RATIO", "TURNOVER", "ATR20",
                "HH60", "LOCATION120", "RANGE10", "BODY_RATIO", "CAPITAL_IMPACT"]:
        assert col in out.columns
