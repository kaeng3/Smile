from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from tests.conftest import make_ohlcv_df
from jusmo_scanner.scanner import pivots


def _peak_series(highs: list[float], window: int = 2):
    df = make_ohlcv_df([{"high": h} for h in highs])
    return df, pivots.find_swing_highs(df, window=window)


def test_find_swing_highs_marks_local_max():
    df, is_peak = _peak_series([10, 10, 50, 10, 10])
    assert bool(is_peak.iloc[2]) is True
    assert bool(is_peak.iloc[0]) is False
    assert bool(is_peak.iloc[4]) is False


def test_find_swing_highs_no_peak_without_enough_bars_on_both_sides():
    df, is_peak = _peak_series([50, 10, 10])  # peak at position 0 has no left window
    assert bool(is_peak.iloc[0]) is False


def test_confirmed_swing_highs_excludes_unconfirmed_peak_bug4():
    # window=2: the peak at position 2 needs bars up to position 4 to confirm.
    df, is_peak = _peak_series([10, 10, 50, 10, 10, 10, 10], window=2)
    assert bool(is_peak.iloc[2]) is True
    # As of position 3 (only 1 bar after the peak) it is NOT yet confirmed.
    positions, prices = pivots.get_confirmed_swing_highs(df, is_peak, as_of_position=3, window=2)
    assert positions == []
    # As of position 4 (2 bars after the peak) it IS confirmed.
    positions, prices = pivots.get_confirmed_swing_highs(df, is_peak, as_of_position=4, window=2)
    assert positions == [2]
    assert prices == [50]


def _reference_swing_highs(highs: list[float], window: int) -> list[bool]:
    """Simple O(N*window) loop with the original semantics."""
    out = [False] * len(highs)
    for i in range(window, len(highs) - window):
        left = [h for h in highs[i - window:i] if not np.isnan(h)]
        right = [h for h in highs[i + 1:i + window + 1] if not np.isnan(h)]
        if np.isnan(highs[i]) or not left or not right:
            continue
        out[i] = highs[i] > max(left) and highs[i] > max(right)
    return out


@pytest.mark.parametrize("window", [1, 2, 3, 5, 8])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_vectorized_swing_highs_match_reference_loop(window, seed):
    rng = np.random.default_rng(seed)
    # integer-valued highs make ties frequent, exercising the strict '>' rule
    highs = rng.integers(90, 110, 300).astype(float).tolist()
    df = make_ohlcv_df([{"high": h} for h in highs])
    got = pivots.find_swing_highs(df, window=window).tolist()
    assert got == _reference_swing_highs(highs, window)
    assert any(got)


def test_swing_highs_nan_neighbors_match_reference():
    rng = np.random.default_rng(7)
    highs = rng.integers(90, 110, 200).astype(float)
    highs[rng.integers(0, 200, 15)] = np.nan
    df = make_ohlcv_df([{"high": h} for h in highs])
    for window in (2, 4):
        assert pivots.find_swing_highs(df, window=window).tolist() == _reference_swing_highs(highs.tolist(), window)


def test_swing_highs_flat_and_ties_are_not_peaks():
    df, is_peak = _peak_series([10] * 20, window=3)
    assert not is_peak.any()
    df, is_peak = _peak_series([10, 10, 50, 50, 10, 10, 10], window=2)  # tie with neighbor
    assert not is_peak.any()


def test_swing_highs_short_df_and_edges():
    for n in (0, 1, 4, 5):
        df = pd.DataFrame({"high": [1.0, 2, 3, 9, 1][:n]})
        is_peak = pivots.find_swing_highs(df, window=2)
        assert len(is_peak) == n and not is_peak.any()
    # exactly 2*window+1 bars: only the center can be a peak
    df, is_peak = _peak_series([1, 2, 9, 2, 1], window=2)
    assert is_peak.tolist() == [False, False, True, False, False]


def test_swing_high_table_separates_pivot_and_confirmed_positions():
    df = make_ohlcv_df([{"high": h} for h in [10, 10, 50, 10, 10, 10, 10]])
    positions, prices, confirmed = pivots.swing_high_table(df, window=2)
    assert positions.tolist() == [2] and prices.tolist() == [50.0] and confirmed.tolist() == [4]


def test_pivot_confirmation_has_no_lookahead():
    rng = np.random.default_rng(3)
    window = 3
    highs = rng.integers(90, 130, 200).astype(float)
    df = make_ohlcv_df([{"high": h} for h in highs])
    positions, prices, _ = pivots.swing_high_table(df, window)
    assert len(positions) > 3
    for p in positions:
        for as_of in range(0, len(df)):
            got_pos, _ = pivots.latest_confirmed_swing_highs(positions, prices, as_of, window, n=len(positions))
            if as_of < p + window:
                assert int(p) not in got_pos
            else:
                assert int(p) in got_pos


def test_latest_confirmed_matches_full_scan_and_truncation_invariance():
    rng = np.random.default_rng(4)
    window = 4
    highs = rng.integers(90, 130, 250).astype(float)
    df = make_ohlcv_df([{"high": h} for h in highs])
    full_pos, full_prices, _ = pivots.swing_high_table(df, window)
    is_peak = pivots.find_swing_highs(df, window)
    for as_of in range(0, len(df), 7):
        expected = pivots.get_confirmed_swing_highs(df, is_peak, as_of, window)
        latest = pivots.latest_confirmed_swing_highs(full_pos, full_prices, as_of, window, n=2)
        assert latest == (expected[0][-2:], expected[1][-2:])
        # a df that only exists up to as_of must give the very same answer
        trunc = df.iloc[:as_of + 1].reset_index(drop=True)
        t_pos, t_prices, _ = pivots.swing_high_table(trunc, window)
        assert pivots.latest_confirmed_swing_highs(t_pos, t_prices, as_of, window, n=2) == latest


from jusmo_scanner.scanner import trend


def test_fit_resistance_line_none_with_fewer_than_two_points():
    assert trend.fit_resistance_line([5], [100]) is None
    assert trend.fit_resistance_line([], []) is None


def test_fit_resistance_line_descending_returns_line():
    line = trend.fit_resistance_line([2, 10], [100, 80])  # descending: 100 -> 80
    assert line is not None
    assert line.slope < 0


def test_fit_resistance_line_none_when_ascending():
    line = trend.fit_resistance_line([2, 10], [80, 100])  # ascending, not a resistance
    assert line is None


def test_line_value_matches_known_points():
    line = trend.fit_resistance_line([0, 10], [100, 80])
    assert trend.line_value(line, 0) == 100
    assert trend.line_value(line, 10) == 80
    assert trend.line_value(line, 5) == 90
