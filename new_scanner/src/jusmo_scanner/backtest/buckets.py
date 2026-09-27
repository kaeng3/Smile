"""Pure bucket functions for backtest analyses.

Conventions (identical for every numeric dimension)
--------------------------------------------------
* Buckets are labelled ranges, RIGHT-OPEN: [lo, hi). A value exactly on an edge
  belongs to the UPPER bucket (vcr 0.25 -> "0.25-0.3", not "0.2-0.25").
* Below the first edge there is an explicit "<first" bucket (so a negative VCR is
  "<0", never dropped); at/above the last edge the label is "last+".
* Score dimensions are closed at the top: 100 belongs to "90-100"; only values
  above 100 (impossible for the scanner) are ">100".
* A missing value (None, NaN, +/-inf, pd.NA, non-numeric) is the explicit label
  MISSING. Nothing is ever dropped silently.
* Edges are stored in the NATIVE unit of the value (fractions for pct dimensions,
  computed as e / 100 so that 0.08 == 8 / 100 exactly), labels in display units.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import Any, Callable, Sequence

MISSING = "MISSING"

BN = 1e9  # KRW per "bn" (billion won)


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _g(x: float) -> str:
    return f"{x:g}"


@dataclass(frozen=True)
class Bucketer:
    """`edges` ascending (native unit); `labels` has len(edges) + 1 entries:
    labels[0] for x < edges[0], labels[k] for edges[k-1] <= x < edges[k], and the
    last label for x >= edges[-1]. With `closed_last`, x == edges[-1] belongs to
    the previous bucket."""
    edges: tuple[float, ...]
    labels: tuple[str, ...]
    closed_last: bool = False

    def __post_init__(self) -> None:
        assert len(self.labels) == len(self.edges) + 1
        assert list(self.edges) == sorted(set(self.edges))

    def __call__(self, value: Any) -> str:
        x = _num(value)
        if x is None:
            return MISSING
        k = bisect_right(self.edges, x)
        if self.closed_last and x == self.edges[-1]:
            k -= 1
        return self.labels[k]

    def all_labels(self) -> tuple[str, ...]:
        return self.labels + (MISSING,)


def range_bucketer(display_edges: Sequence[float], *, native_edges: Sequence[float] | None = None,
                   unit: str = "", closed_last: bool = False, sep: str = "-") -> Bucketer:
    """Labels "<e0u", "e0<sep>e1u", ..., "e_last+u" (or, with closed_last, "..-e_lastu"
    for the top closed bucket and ">e_lastu" above it)."""
    d = list(display_edges)
    native = tuple(float(e) for e in (native_edges if native_edges is not None else d))
    labels = [f"<{_g(d[0])}{unit}"]
    labels += [f"{_g(a)}{sep}{_g(b)}{unit}" for a, b in zip(d, d[1:])]
    labels.append(f">{_g(d[-1])}{unit}" if closed_last else f"{_g(d[-1])}+{unit}")
    return Bucketer(native, tuple(labels), closed_last)


def _pct(display_edges: Sequence[float]) -> list[float]:
    return [e / 100 for e in display_edges]


def _bn(display_edges: Sequence[float]) -> list[float]:
    return [e * BN for e in display_edges]


def _int_bucketer(edges: Sequence[int], labels: Sequence[str]) -> Bucketer:
    return Bucketer(tuple(float(e) for e in edges), tuple(labels))


# --- numeric dimensions ------------------------------------------------------------

# event trading value in bn KRW (design: 300/500/700/1000/1500억 == 30/50/70/100/150bn):
# <30, 30-50, 50-70, 70-100, 100-150, 150+
event_value_bucket = range_bucketer((30, 50, 70, 100, 150), native_edges=_bn((30, 50, 70, 100, 150)), unit="bn")
# event trading value / prior-20-bar average
value_ratio_bucket = range_bucketer((1.5, 2, 3, 4, 5))
# volume / free float (or shares outstanding, see share_count_basis)
turnover_bucket = range_bucketer((0.1, 0.2, 0.3, 0.4, 0.5))
# trading value / market cap, in %
_CAP = (0, 1, 3, 5, 10, 20)
capital_impact_bucket = range_bucketer(_CAP, native_edges=_pct(_CAP), unit="%")
# 0.2 steps; close can sit above the 120-bar high, so the top is "1+" (not closed)
location120_bucket = range_bucketer((0, 0.2, 0.4, 0.6, 0.8, 1.0))
# VCR (shared by vcr_anchor / vcr_latest_event / vcr_max_event)
vcr_bucket = range_bucketer((0, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.75))
# 10-bar range, in %
_R10 = (0, 5, 8, 10, 12, 15, 20)
range10_bucket = range_bucketer(_R10, native_edges=_pct(_R10), unit="%")
# (close - cost) / cost, in %
_CD = (-10, -5, -2, 0, 2, 5, 10, 20)
cost_distance_bucket = range_bucketer(_CD, native_edges=_pct(_CD), unit="%", sep="~")
# (close - event low) / event low, in %
_ELD = (0, 3, 5, 10, 20, 30)
event_low_distance_bucket = range_bucketer(_ELD, native_edges=_pct(_ELD), unit="%")
# trading days since the anchor event
event_age_bucket = _int_bucketer(
    (0, 4, 8, 15, 31, 61), ("<0", "0-3", "4-7", "8-14", "15-30", "31-60", "60+"))
event_count_bucket = _int_bucketer((1, 2, 3, 4), ("<1", "1", "2", "3", "4+"))
# cumulative event trading value of the episode. Design §7 gives the edges in 억 (1e8 KRW):
# <500억, 500-1000억, 1000-2000억, 2000-5000억, 5000억+ == <50bn, 50-100bn, 100-200bn,
# 200-500bn, 500+bn (bn = 1e9 KRW; 1억 = 0.1bn). Native edges 5e10 / 1e11 / 2e11 / 5e11.
cluster_value_bucket = range_bucketer(
    (50, 100, 200, 500), native_edges=_bn((50, 100, 200, 500)), unit="bn")
events_in_last_20d_bucket = _int_bucketer((1, 2, 3, 4), ("0", "1", "2", "3", "4+"))
# structure / trigger scores 0..100, closed at the top
_SCORE = (0, 50, 60, 70, 80, 90, 100)
structure_score_bucket = range_bucketer(_SCORE, closed_last=True)
trigger_score_bucket = range_bucketer(_SCORE, closed_last=True)
# (close - breakout high) / breakout high, in %; the scanner's PULLBACK band is -12%..-3%
_PD = (-15, -12, -10, -8, -5, -3, 0)
pullback_depth_bucket = range_bucketer(_PD, native_edges=_pct(_PD), unit="%", sep="~")
# pullback volume / breakout-bar volume
pullback_volume_ratio_bucket = range_bucketer((0.25, 0.5, 0.75, 1.0, 1.5))
# trading days since the breakout bar
days_since_breakout_bucket = _int_bucketer(
    (0, 1, 3, 6, 11, 21), ("<0", "0", "1-2", "3-5", "6-10", "11-20", "21+"))


def bool_bucket(value: Any) -> str:
    """"True"/"False"; None (unknown) is MISSING - a missing flag is not False."""
    if value is None:
        return MISSING
    return "True" if bool(value) else "False"


def identity_bucket(value: Any) -> str:
    """Categorical passthrough (state / transition / signal_type)."""
    return MISSING if value is None or value == "" else str(value)


def transition_label(previous_state: Any, state: Any) -> str:
    if not previous_state or not state:
        return MISSING
    return f"{previous_state}->{state}"


# --- dimension registry ---------------------------------------------------------------

@dataclass(frozen=True)
class Dimension:
    """A bucketed dimension: `name` -> label of one signal row.
    `getter` reads the raw value from a row mapping (a `SignalSnapshot.to_dict()`
    augmented with `signal_type`); `bucket` maps it to a label."""
    name: str
    getter: Callable[[Any], Any]
    bucket: Callable[[Any], str]

    def label(self, row: Any) -> str:
        return self.bucket(self.getter(row))


def _field(name: str) -> Callable[[Any], Any]:
    return lambda row: row.get(name)


def _dim(name: str, bucket: Callable[[Any], str], field: str | None = None) -> tuple[str, Dimension]:
    return name, Dimension(name, _field(field or name), bucket)


DIMENSIONS: dict[str, Dimension] = dict([
    _dim("strategy_family", identity_bucket),
    _dim("anchor_event_location", identity_bucket),
    _dim("event_location", identity_bucket),
    _dim("current_location", identity_bucket),
    _dim("cost_status", identity_bucket),
    ("state", Dimension("state", _field("state"), identity_bucket)),
    ("transition", Dimension("transition",
                             lambda r: (r.get("previous_state"), r.get("state")),
                             lambda v: transition_label(*v))),
    ("signal_type", Dimension("signal_type", _field("signal_type"), identity_bucket)),
    _dim("event_value", event_value_bucket, "event_trading_value"),
    _dim("value_ratio", value_ratio_bucket, "event_value_ratio"),
    _dim("turnover", turnover_bucket, "event_turnover"),
    # capital_impact / location120: values on the SIGNAL bar (what scoring uses);
    # event_capital_impact / event_location120: anchor-bar values (event strength research)
    _dim("capital_impact", capital_impact_bucket),
    _dim("event_capital_impact", capital_impact_bucket),
    _dim("location120", location120_bucket),
    _dim("event_location120", location120_bucket),
    _dim("vcr_anchor", vcr_bucket),
    _dim("vcr_latest_event", vcr_bucket),
    _dim("vcr_max_event", vcr_bucket),
    _dim("range10", range10_bucket),
    _dim("cost_distance", cost_distance_bucket),
    _dim("event_low_distance", event_low_distance_bucket),
    _dim("event_age", event_age_bucket, "days_since_event_trading"),
    _dim("event_count", event_count_bucket, "event_count_so_far"),
    _dim("cluster_value", cluster_value_bucket, "cluster_trading_value_so_far"),
    _dim("events_in_last_20d", events_in_last_20d_bucket),
    _dim("structure_score", structure_score_bucket),
    _dim("trigger_score", trigger_score_bucket),
    _dim("pullback_depth", pullback_depth_bucket),
    _dim("pullback_volume_ratio", pullback_volume_ratio_bucket),
    _dim("days_since_breakout", days_since_breakout_bucket),
    _dim("accumulation_confirmed", bool_bucket),
    _dim("above_ma240", bool_bucket),
    _dim("previous_high_break", bool_bucket),
])
