"""Forward-performance metrics (pure functions, no look-back into the signal).

Everything after the signal bar `i` is "future" and only used here, never for
building signals. Forward windows always start at bar i+1; the signal bar's own
high/low never enters MFE/MAE.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, NamedTuple, Sequence

import numpy as np

DEFAULT_HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 20, 40)
HIT_UP_THRESHOLDS: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20, 0.30)
HIT_DOWN_THRESHOLDS: tuple[float, ...] = (0.03, 0.05, 0.10, 0.15, 0.20)

_EPS = 1e-12

CLOSE_MODE_WARNING = (
    "optimistic assumption: CLOSE entry assumes a fill at the signal-day close after "
    "the signal is already known (the signal is only knowable after that close)"
)


class EntryMode(Enum):
    """NEXT_OPEN (primary/recommended): entry = open of the bar after the signal.
    CLOSE (research/optimistic): entry = close of the signal bar. See CLOSE_MODE_WARNING."""
    NEXT_OPEN = "NEXT_OPEN"
    CLOSE = "CLOSE"


@dataclass(frozen=True)
class ForwardResult:
    """Outcome for one (signal, horizon). All values are relative to entry_price.
    hit_up_N: MFE >= N%; hit_down_N: MAE <= -N%. They are independent booleans;
    the intrabar order of the high and the low is unknown."""
    entry_price: float
    forward_return: float
    mfe: float
    mae: float
    hit_up_5: bool
    hit_up_10: bool
    hit_up_15: bool
    hit_up_20: bool
    hit_up_30: bool
    hit_down_3: bool
    hit_down_5: bool
    hit_down_10: bool
    hit_down_15: bool
    hit_down_20: bool


def _valid(a: np.ndarray) -> bool:
    return bool(np.all(np.isfinite(a)) and np.all(a > 0))


def forward_metrics(
    open_: Sequence[float], high: Sequence[float], low: Sequence[float], close: Sequence[float],
    signal_index: int, horizon: int, entry_mode: EntryMode = EntryMode.NEXT_OPEN,
) -> ForwardResult | None:
    """Forward return / MFE / MAE for a signal at bar `signal_index` (= i).

    entry: NEXT_OPEN -> open[i+1]; CLOSE -> close[i].
    end bar e = i + horizon must exist (e < n): no partial windows (returns None).
    forward_return = close[e] / entry - 1
    MFE = max(high[i+1..e]) / entry - 1;  MAE = min(low[i+1..e]) / entry - 1
    (the signal bar is excluded in BOTH modes; in CLOSE mode MFE can in principle be
    negative if every later high is below the signal close - values are not clipped).
    Returns None (never raises, never fabricates a number) when data is missing or any
    price used is NaN / inf / non-positive. Raises ValueError only for horizon < 1 or
    signal_index < 0 (programming errors)."""
    if horizon < 1 or signal_index < 0:
        raise ValueError(f"horizon must be >= 1 and signal_index >= 0, got {horizon}, {signal_index}")
    i, e = signal_index, signal_index + horizon
    o = np.asarray(open_, dtype=float)
    h = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    n = len(c)
    if e >= n or not (len(o) == len(h) == len(lo) == n):
        return None
    entry = float(o[i + 1]) if entry_mode is EntryMode.NEXT_OPEN else float(c[i])
    win_h, win_l = h[i + 1: e + 1], lo[i + 1: e + 1]
    if not (np.isfinite(entry) and entry > 0 and _valid(win_h) and _valid(win_l)
            and np.isfinite(c[e]) and c[e] > 0):
        return None
    ret = float(c[e]) / entry - 1.0
    mfe = float(win_h.max()) / entry - 1.0
    mae = float(win_l.min()) / entry - 1.0
    # _EPS: a move of exactly +15% must count even though 1150/1000 - 1 == 0.1499999999999999
    up = {f"hit_up_{round(t * 100)}": mfe >= t - _EPS for t in HIT_UP_THRESHOLDS}
    down = {f"hit_down_{round(t * 100)}": mae <= -t + _EPS for t in HIT_DOWN_THRESHOLDS}
    return ForwardResult(entry_price=entry, forward_return=ret, mfe=mfe, mae=mae, **up, **down)


# --- legacy Stage 1 helpers ---------------------------------------------------

def win_rate(returns: list[float]) -> float | None:
    if not returns:
        return None
    return sum(1 for r in returns if r > 0) / len(returns)


def average_return(returns: list[float]) -> float | None:
    if not returns:
        return None
    return sum(returns) / len(returns)


def max_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        cumulative *= 1 + r
        peak = max(peak, cumulative)
        max_dd = min(max_dd, cumulative / peak - 1)
    return max_dd


# --- group aggregation (Stage 2 commit 2b) -------------------------------------

DEFAULT_QUALITY_THRESHOLDS: tuple[int, int, int] = (30, 100, 300)
DEFAULT_MIN_SAMPLE_SIZE = 100

# Bit position of each hit flag in the compact `hits` integer used by GroupArrays.
HIT_FIELDS: tuple[str, ...] = tuple(
    [f"hit_up_{round(t * 100)}" for t in HIT_UP_THRESHOLDS]
    + [f"hit_down_{round(t * 100)}" for t in HIT_DOWN_THRESHOLDS])

QUALITY_LEVELS = ("VERY_LOW", "LOW", "MEDIUM", "HIGH")


class GroupArrays(NamedTuple):
    """Compact columnar sample: equal-length arrays of forward_return, mfe, mae and
    `hits` (integer bitmask, bit k = HIT_FIELDS[k])."""
    forward_return: np.ndarray
    mfe: np.ndarray
    mae: np.ndarray
    hits: np.ndarray


def pack_hits(fr: "ForwardResult | Mapping[str, object]") -> int:
    get = fr.get if isinstance(fr, Mapping) else (lambda k: getattr(fr, k))
    bits = 0
    for k, name in enumerate(HIT_FIELDS):
        if get(name):
            bits |= 1 << k
    return bits


def sample_quality(n: int, thresholds: Sequence[int] = DEFAULT_QUALITY_THRESHOLDS) -> str:
    """VERY_LOW if n < t0, LOW if n < t1, MEDIUM if n < t2, else HIGH (n == 0 -> VERY_LOW)."""
    t0, t1, t2 = thresholds
    if n < t0:
        return "VERY_LOW"
    if n < t1:
        return "LOW"
    if n < t2:
        return "MEDIUM"
    return "HIGH"


_PCT = {"return": (10, 25, 50, 75, 90), "mfe": (50, 75, 90), "mae": (10, 25, 50)}
_BIT_SHIFTS = np.arange(len(HIT_FIELDS), dtype=np.int64)


def _percentiles(values: np.ndarray, ps: Sequence[int]) -> np.ndarray:
    """Percentiles by linear interpolation between order statistics (position
    p/100 * (n-1)); numerically identical to numpy's default `np.percentile`
    (same lerp formula) but one sort and no per-call dispatch overhead."""
    s = np.sort(values)
    n = len(s)
    pos = np.asarray(ps, dtype=float) / 100.0 * (n - 1)
    lo = np.floor(pos).astype(np.int64)
    hi = np.minimum(lo + 1, n - 1)
    t = pos - lo
    a, b = s[lo], s[hi]
    diff = b - a
    out = a + diff * t
    upper = t >= 0.5
    out[upper] = b[upper] - diff[upper] * (1 - t[upper])
    return out


@dataclass(frozen=True)
class GroupStats:
    """Objective distribution statistics of one group. Every statistic is None
    (never NaN, never a fabricated 0) when it cannot be computed: all of them for
    an empty group, `std_return` for n < 2. win_rate = share of forward_return > 0;
    hit_* = share of the sample whose MFE (up) / MAE (down) crossed the threshold.
    `low_sample` = n < min_sample_size (the values are still shown)."""
    sample_count: int
    sample_quality: str
    low_sample: bool
    mean_return: float | None = None
    median_return: float | None = None
    std_return: float | None = None
    mean_mfe: float | None = None
    median_mfe: float | None = None
    mean_mae: float | None = None
    median_mae: float | None = None
    win_rate: float | None = None
    hit_up_5: float | None = None
    hit_up_10: float | None = None
    hit_up_15: float | None = None
    hit_up_20: float | None = None
    hit_up_30: float | None = None
    hit_down_3: float | None = None
    hit_down_5: float | None = None
    hit_down_10: float | None = None
    hit_down_15: float | None = None
    hit_down_20: float | None = None
    return_p10: float | None = None
    return_p25: float | None = None
    return_p50: float | None = None
    return_p75: float | None = None
    return_p90: float | None = None
    mfe_p50: float | None = None
    mfe_p75: float | None = None
    mfe_p90: float | None = None
    mae_p10: float | None = None
    mae_p25: float | None = None
    mae_p50: float | None = None

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def _f(x) -> float | None:
    v = float(x)
    return v if math.isfinite(v) else None


def _rows_to_arrays(rows: Iterable) -> GroupArrays:
    ret, mfe, mae, hits = [], [], [], []
    for r in rows:
        if isinstance(r, Mapping):
            a, b, c = r["forward_return"], r["mfe"], r["mae"]
        else:
            a, b, c = r.forward_return, r.mfe, r.mae
        ret.append(a if a is not None else math.nan)
        mfe.append(b if b is not None else math.nan)
        mae.append(c if c is not None else math.nan)
        hits.append(pack_hits(r))
    return GroupArrays(np.asarray(ret, float), np.asarray(mfe, float), np.asarray(mae, float),
                       np.asarray(hits, dtype=np.int64))


def aggregate_group(
    data: "GroupArrays | Iterable[ForwardResult | Mapping[str, object]]",
    quality_thresholds: Sequence[int] = DEFAULT_QUALITY_THRESHOLDS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> GroupStats:
    """Pure aggregation of one group. `data` is a `GroupArrays` or an iterable of
    ForwardResult objects / dict rows (forward_return, mfe, mae, hit_*).

    * A row whose forward_return, mfe or mae is None/NaN/inf is EXCLUDED from the
      sample (it is not counted and cannot leak into any statistic).
    * mean/median via numpy; std is the SAMPLE standard deviation (ddof=1), None if n < 2.
    * Percentiles use numpy's default linear interpolation between order statistics
      (position p/100 * (n-1)); a single observation returns that value for every p.
    * An empty group gives sample_count 0, VERY_LOW and all statistics None."""
    arr = data if isinstance(data, GroupArrays) else _rows_to_arrays(data)
    ret = np.asarray(arr.forward_return, dtype=float)
    mfe = np.asarray(arr.mfe, dtype=float)
    mae = np.asarray(arr.mae, dtype=float)
    hits = np.asarray(arr.hits, dtype=np.int64)
    if not (len(ret) == len(mfe) == len(mae) == len(hits)):
        raise ValueError("GroupArrays columns must have equal length")
    ok = np.isfinite(ret) & np.isfinite(mfe) & np.isfinite(mae)
    if not ok.all():
        ret, mfe, mae, hits = ret[ok], mfe[ok], mae[ok], hits[ok]
    n = int(len(ret))
    quality = sample_quality(n, quality_thresholds)
    low = n < min_sample_size
    if n == 0:
        return GroupStats(sample_count=0, sample_quality=quality, low_sample=low)
    vals: dict[str, float | None] = {
        "mean_return": _f(ret.mean()),
        "std_return": _f(ret.std(ddof=1)) if n >= 2 else None,
        "mean_mfe": _f(mfe.mean()), "mean_mae": _f(mae.mean()),
        "win_rate": _f((ret > 0).mean()),
    }
    for name, share in zip(HIT_FIELDS, ((hits[:, None] >> _BIT_SHIFTS) & 1).mean(axis=0)):
        vals[name] = _f(share)
    for label, series in (("return", ret), ("mfe", mfe), ("mae", mae)):
        ps = _PCT[label]
        for p, v in zip(ps, _percentiles(series, ps)):
            vals[f"{label}_p{p}"] = _f(v)
    # the median is the 50th percentile (identical to np.median)
    vals["median_return"] = vals["return_p50"]
    vals["median_mfe"] = vals["mfe_p50"]
    vals["median_mae"] = vals["mae_p50"]
    return GroupStats(sample_count=n, sample_quality=quality, low_sample=low, **vals)
