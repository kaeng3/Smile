"""Causal per-bar signal snapshots emitted by the scan engine (opt-in).

A `SignalSnapshot` records everything the scanner knew at the close of one bar
of an active episode. Every field uses only data at bars <= `bar_index`; no
field may ever depend on a later bar, later event or unconfirmed pivot. It is
separate from production `ScanResult`; both carry strategy location and cost status.

Conventions
-----------
* Plain Python types only (float/int/str/bool/date), never numpy scalars.
* A value that cannot be computed is None (NaN/inf -> None); never a fake 0.
* `to_dict()` is flat and JSON-safe (dates -> ISO strings).
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from datetime import date
from typing import Any


def to_plain_float(x: Any) -> float | None:
    """float(x) for finite numbers; None for None/NaN/inf/pd.NA/non-numeric."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


@dataclass(frozen=True)
class SignalSnapshot:
    """Snapshot at bar `bar_index` (the signal bar; information is known at its close).

    Identity / state
      ticker, name (frame column `name` if present), signal_date, bar_index (0-based
      position in the input frame), episode_id, state / previous_state (State names;
      `state` is the state AFTER this bar, `previous_state` the state before it).

    Anchor event (the episode's first event; the episode is keyed on it)
      event_date; days_since_event_trading = bar_index - anchor bar index;
      event_trading_value; event_score = `event_score_v1` of the anchor event, a
      TWO-CLASS label (50 = CORE, 100 = STRONG), NOT a continuous score;
      event_strength_class ("CORE"|"STRONG"); event_value_ratio (trading value /
      prior-20-bar average); event_turnover (volume / free float); event_close_location
      ((close-low)/(high-low) of the anchor bar); event_capital_impact and
      event_location120 (anchor-bar values). The last four are raw inputs for future
      continuous Event Strength experiments.

    Episode-so-far (only events at bars <= bar_index)
      event_count_so_far; cluster_trading_value_so_far (sum of the trading values of
      the episode's events so far); events_in_last_20d (number of RAW detected events
      at bars bar_index-19..bar_index, regardless of episode); event_added_this_bar;
      strong_event_this_bar (an event at this bar with event_score == 100).

    Structure
      capital_impact / location120: values on the SIGNAL bar (these are the
      inputs the scanner's scoring uses). estimated_cost (engine's cost model, not the
      tolerance floor); cost_distance = (close-cost)/cost; event_low = lowest low of the
      episode's events so far; event_low_distance = (close-event_low)/event_low;
      vcr_anchor = AVG_VOLUME_5 / anchor event volume (the engine's VCR);
      vcr_latest_event = AVG_VOLUME_5 / volume of the most recent event so far;
      vcr_max_event = AVG_VOLUME_5 / largest event volume so far; rvol20; range10.
      accumulation_confirmed = research-only flag (state machine untouched):
      days_since_event_trading >= backtest_accumulation_min_days AND the engine's
      event_low_hold AND estimated_cost_hold AND vcr_anchor <= backtest_accumulation_vcr_max.

    Trend / trigger
      ma5..ma240 and ma5_slope / ma20_slope (1-bar MA differences); above_ma120/240
      (close > MA); cross_ma120/240 (the engine's golden-cross flags);
      prior_high = HH60 (highest high of the 60 bars strictly before this bar);
      prior_high_distance = (close-HH60)/HH60; previous_high_break = close > HH60;
      trend_break = engine's confirmed-pivot resistance-line break flag.
      structure_score, trigger_score, final_score (theme-free unless the engine was
      given a theme engine), theme_score, distribution_warning, market_cap,
      free_float_shares, close.

    Breakout context (all None while the episode has had no breakout; the engine
    only enters BREAKOUT once per episode, so this is the "most recent breakout entry")
      breakout_date; days_since_breakout (trading days); breakout_price (close of the
      breakout bar); breakout_high (high of the breakout bar); pullback_depth =
      (close-breakout_high)/breakout_high; pullback_volume_ratio = volume / breakout-bar
      volume; distance_to_ma20/60/120/240 = (close-MA)/MA; previous_high_hold = close >=
      the HH60 level in force at the breakout bar (None if that level is unknown).
    """
    # identity
    ticker: str
    signal_date: date
    bar_index: int
    episode_id: str
    state: str
    previous_state: str
    event_date: date
    days_since_event_trading: int
    event_count_so_far: int
    cluster_trading_value_so_far: float
    events_in_last_20d: int
    event_added_this_bar: bool
    strong_event_this_bar: bool
    accumulation_confirmed: bool
    cross_ma120: bool
    cross_ma240: bool
    previous_high_break: bool
    trend_break: bool
    distribution_warning: bool
    close: float
    # nullable
    name: str | None = None
    # event_location = most recent event in this episode; anchor is immutable.
    event_location: str = "UNKNOWN"
    anchor_event_location: str = "UNKNOWN"
    current_location: str = "UNKNOWN"
    strategy_family: str = "UNKNOWN_COST_TRACKING"
    cost_status: str | None = None  # HOLD / BREACHED, using the configured ATR/% floor
    event_trading_value: float | None = None
    event_score: float | None = None
    event_strength_class: str | None = None
    event_value_ratio: float | None = None
    event_turnover: float | None = None
    event_close_location: float | None = None
    event_capital_impact: float | None = None
    event_location120: float | None = None
    capital_impact: float | None = None
    location120: float | None = None
    estimated_cost: float | None = None
    cost_distance: float | None = None
    event_low: float | None = None
    event_low_distance: float | None = None
    vcr_anchor: float | None = None
    vcr_latest_event: float | None = None
    vcr_max_event: float | None = None
    rvol20: float | None = None
    range10: float | None = None
    ma5: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    ma120: float | None = None
    ma240: float | None = None
    ma5_slope: float | None = None
    ma20_slope: float | None = None
    above_ma120: bool | None = None
    above_ma240: bool | None = None
    prior_high: float | None = None
    prior_high_distance: float | None = None
    structure_score: float | None = None
    trigger_score: float | None = None
    final_score: float | None = None
    theme_score: float | None = None
    market_cap: float | None = None
    free_float_shares: float | None = None
    breakout_date: date | None = None
    days_since_breakout: int | None = None
    breakout_price: float | None = None
    breakout_high: float | None = None
    pullback_depth: float | None = None
    pullback_volume_ratio: float | None = None
    distance_to_ma20: float | None = None
    distance_to_ma60: float | None = None
    distance_to_ma120: float | None = None
    distance_to_ma240: float | None = None
    previous_high_hold: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Flat, JSON-safe dict (dates as ISO strings, None kept as None)."""
        out: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            out[f.name] = v.isoformat() if isinstance(v, date) else v
        return out
