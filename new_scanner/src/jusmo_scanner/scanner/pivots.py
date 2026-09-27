from __future__ import annotations
from bisect import bisect_right

import numpy as np
import pandas as pd


def _peak_mask(high: np.ndarray, window: int) -> np.ndarray:
    """Vectorized swing-high mask over a float array (NaN neighbors are
    skipped, like pandas' max; a NaN peak candidate is never a peak)."""
    n = len(high)
    mask = np.zeros(n, dtype=bool)
    if window < 1 or n < 2 * window + 1:
        return mask
    s = pd.Series(high)
    left_max = s.shift(1).rolling(window, min_periods=1).max().to_numpy()
    right_max = s[::-1].shift(1).rolling(window, min_periods=1).max()[::-1].to_numpy()
    with np.errstate(invalid="ignore"):
        mask = (high > left_max) & (high > right_max)  # NaN compares False
    mask[:window] = False
    mask[n - window:] = False
    return mask


def find_swing_highs(df: pd.DataFrame, window: int = 5) -> pd.Series:
    """Boolean series, True at bar i iff high[i] is strictly greater than
    every high in the `window` bars immediately before AND after it. A bar
    within `window` of either edge of the DataFrame can never be marked
    (there aren't enough neighbors to judge it)."""
    high = df["high"].to_numpy(dtype=float)
    return pd.Series(_peak_mask(high, window), index=df.index)


def swing_high_table(
    df: pd.DataFrame, window: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(peak positions, peak highs, confirmed positions) as numpy arrays.
    A peak at position p (`pivot_date` = df date at p) is only known to be a
    peak once `window` more bars exist, i.e. at `confirmed_position = p +
    window` (`confirmed_date`)."""
    high = df["high"].to_numpy(dtype=float)
    positions = np.flatnonzero(_peak_mask(high, window))
    return positions, high[positions], positions + window


def latest_confirmed_swing_highs(
    positions: np.ndarray, prices: np.ndarray, as_of_position: int, window: int, n: int = 2,
) -> tuple[list[int], list[float]]:
    """The last `n` swing highs usable as of `as_of_position` (peak position
    + window <= as_of_position), oldest first. O(log N) via bisect."""
    end = bisect_right(positions, as_of_position - window)
    start = max(0, end - n)
    return [int(p) for p in positions[start:end]], [float(p) for p in prices[start:end]]


def get_confirmed_swing_highs(
    df: pd.DataFrame, is_peak: pd.Series, as_of_position: int, window: int,
) -> tuple[list[int], list[float]]:
    """All swing highs at position i with i + window <= as_of_position: a
    peak is only usable once all `window` confirming bars after it exist
    (prevents drawing a resistance line through an unconfirmed pivot)."""
    positions = np.flatnonzero(is_peak.to_numpy(dtype=bool))
    positions = positions[positions + window <= as_of_position]
    return [int(p) for p in positions], [float(x) for x in df["high"].to_numpy(dtype=float)[positions]]
