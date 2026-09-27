# src/jusmo_scanner/scanner/state_machine.py
from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum


class State(IntEnum):
    INVALIDATED = -1
    NONE = 0
    EVENT = 1
    ACCUMULATION = 2
    DORMANT = 3
    IGNITION = 4
    BREAKOUT = 5
    PULLBACK = 6
    COST_TRACKING = 7


# Monotonic progression only: every transition other than ->INVALIDATED goes
# to a strictly higher State value. A ticker can always fall through to
# INVALIDATED, but never regresses on its own (e.g. BREAKOUT never reverts to
# DORMANT, and PULLBACK never returns to BREAKOUT; it stays PULLBACK until
# INVALIDATED). See design doc bug #7. Distinguishing a later re-up would
# need a separate, later REACCELERATION state (not part of this table).
ALLOWED_TRANSITIONS: dict[State, set[State]] = {
    State.NONE: {State.EVENT},
    State.EVENT: {State.ACCUMULATION, State.COST_TRACKING, State.INVALIDATED},
    State.ACCUMULATION: {State.DORMANT, State.IGNITION, State.BREAKOUT, State.INVALIDATED},
    State.DORMANT: {State.IGNITION, State.BREAKOUT, State.INVALIDATED},
    State.IGNITION: {State.BREAKOUT, State.INVALIDATED},
    State.BREAKOUT: {State.PULLBACK, State.INVALIDATED},
    State.PULLBACK: {State.INVALIDATED},
    State.INVALIDATED: set(),
    State.COST_TRACKING: {State.INVALIDATED},
}


@dataclass
class StateSignals:
    event_low_hold: bool
    estimated_cost_hold: bool
    vcr: float
    range10: float
    ma5_slope: float
    ma120_cross: bool
    ma240_cross: bool
    rvol20: float
    hh60_break: bool
    resistance_break: bool
    had_breakout: bool
    breakout_high: float | None
    close: float
    current_volume: float
    breakout_volume: float | None
    event_low_limit: float
    estimated_cost: float
    atr20: float


@dataclass
class ScannerThresholds:
    dormant_vcr_max: float
    dormant_range10_max: float
    ignition_rvol20_min: float
    breakout_rvol20_min: float
    pullback_drawdown_min: float
    pullback_drawdown_max: float
    pullback_volume_ratio_max: float
    atr_multiplier_invalidated: float
    distribution_location120_min: float
    distribution_rvol20_min: float
    distribution_upper_wick_min: float


def is_golden_cross(prev_close: float, prev_ma: float, close: float, ma: float) -> bool:
    """NaN-safe: if prev_ma/ma are NaN (e.g. a newly listed ticker without
    enough history for MA120/MA240), every comparison is False, so this
    correctly reports "no cross" instead of raising."""
    return prev_close < prev_ma and close > ma


def is_dormant(s: StateSignals, cfg: ScannerThresholds) -> bool:
    return (
        s.event_low_hold and s.estimated_cost_hold
        and s.vcr <= cfg.dormant_vcr_max
        and s.range10 <= cfg.dormant_range10_max
    )


def is_ignition(s: StateSignals, cfg: ScannerThresholds) -> bool:
    if not (s.event_low_hold and s.estimated_cost_hold and s.ma5_slope > 0):
        return False
    return s.ma120_cross or s.ma240_cross or s.rvol20 >= cfg.ignition_rvol20_min


def is_breakout(s: StateSignals, cfg: ScannerThresholds) -> bool:
    if not (s.event_low_hold and s.estimated_cost_hold and s.rvol20 >= cfg.breakout_rvol20_min):
        return False
    return s.ma240_cross or s.hh60_break or s.resistance_break


def is_pullback(s: StateSignals, cfg: ScannerThresholds) -> bool:
    if not (s.had_breakout and s.event_low_hold and s.estimated_cost_hold):
        return False
    if s.breakout_high is None or s.breakout_volume is None or not s.breakout_high:
        return False
    drawdown = (s.close - s.breakout_high) / s.breakout_high
    volume_ok = s.current_volume <= s.breakout_volume * cfg.pullback_volume_ratio_max
    return cfg.pullback_drawdown_min <= drawdown <= cfg.pullback_drawdown_max and volume_ok


def is_invalidated(close: float, event_low_limit: float, estimated_cost: float, atr20: float, atr_multiplier: float) -> bool:
    breached_event_low = close < event_low_limit
    breached_cost = close < estimated_cost - atr20 * atr_multiplier
    return bool(breached_event_low or breached_cost)


def is_distribution_warning(
    location120: float, rvol20: float, upper_wick_ratio: float, close: float, open_: float,
    cfg: ScannerThresholds,
) -> bool:
    return bool(
        location120 >= cfg.distribution_location120_min
        and rvol20 >= cfg.distribution_rvol20_min
        and upper_wick_ratio >= cfg.distribution_upper_wick_min
        and close <= open_
    )


def next_state(current: State, s: StateSignals, cfg: ScannerThresholds,
               bottom_accumulation: bool = True) -> State:
    """Advances at most one step through ALLOWED_TRANSITIONS, which is
    monotone: only strictly-forward moves or INVALIDATED. Never regresses
    (including PULLBACK -> BREAKOUT, which is not allowed): if no allowed
    transition's entry condition holds, `current` is returned unchanged
    (bug #7). Because a state that is not in its own
    ALLOWED_TRANSITIONS value can never be "re-entered", a ticker sitting in
    BREAKOUT with persistently-true breakout conditions simply stays
    BREAKOUT rather than generating a fresh transition every day (bug #8) —
    the caller is responsible for only logging state_history when the
    returned state differs from `current`."""
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if State.INVALIDATED in allowed and is_invalidated(
        s.close, s.event_low_limit, s.estimated_cost, s.atr20, cfg.atr_multiplier_invalidated
    ):
        return State.INVALIDATED
    if not bottom_accumulation and current != State.INVALIDATED:
        return State.COST_TRACKING
    if current == State.EVENT and State.ACCUMULATION in allowed:
        return State.ACCUMULATION
    if State.BREAKOUT in allowed and is_breakout(s, cfg):
        return State.BREAKOUT
    if State.IGNITION in allowed and is_ignition(s, cfg):
        return State.IGNITION
    if State.DORMANT in allowed and is_dormant(s, cfg):
        return State.DORMANT
    if State.PULLBACK in allowed and is_pullback(s, cfg):
        return State.PULLBACK
    return current
