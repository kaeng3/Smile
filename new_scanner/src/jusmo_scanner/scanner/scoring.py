from __future__ import annotations
from abc import ABC, abstractmethod
import math

from . import state_machine as sm


class ThemeEngine(ABC):
    """External interface for a future theme/sector scorer. Not implemented
    in Stage 1 — `NullThemeEngine` always returns None, which callers treat
    as "no theme score available"."""

    @abstractmethod
    def get_score(self, ticker: str) -> int | None:
        raise NotImplementedError


class NullThemeEngine(ThemeEngine):
    def get_score(self, ticker: str) -> int | None:
        return None


def _safe(x: float) -> bool:
    """True if x is a usable finite number (not NaN, not +/-inf)."""
    return x == x and not math.isinf(x)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    if value != value:
        return low
    if math.isinf(value):
        return high if value > 0 else low
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Structure Score component functions (pure). All the numeric parameters
# below are read by the caller from cfg.structure_scoring.* — never hard-code
# a threshold inside these functions.
# ---------------------------------------------------------------------------

def score_event(event_score: float, event_score_weight: float) -> float:
    if not _safe(event_score):
        return 0.0
    return event_score * event_score_weight


def score_hold(held: bool, points: float) -> float:
    return points if held else 0.0


def score_cost_distance(
    cost_distance: float, ideal_min: float, ideal_max: float,
    max_points: float, penalty_scale: float,
) -> float:
    """Being slightly above the accumulation cost is normal and good; being
    far below it (cost breached) or far above it (over-extended, poor
    entry) is penalized proportionally, not treated as equally bad."""
    if not _safe(cost_distance):
        return 0.0
    if ideal_min <= cost_distance <= ideal_max:
        return max_points
    deficit = (ideal_min - cost_distance) if cost_distance < ideal_min else (cost_distance - ideal_max)
    return max(0.0, max_points - deficit * penalty_scale)


def score_vcr(
    vcr: float, strong_threshold: float, normal_threshold: float, weak_threshold: float,
    strong_points: float, normal_points: float, weak_points: float,
) -> float:
    if not _safe(vcr) or vcr < 0:
        return 0.0
    if vcr <= strong_threshold:
        return strong_points
    if vcr <= normal_threshold:
        return normal_points
    if vcr <= weak_threshold:
        return weak_points
    return 0.0


def score_compression(range10: float, best: float, worst: float, max_points: float) -> float:
    if not _safe(range10) or range10 < 0:
        return 0.0
    if range10 <= best:
        return max_points
    if range10 >= worst:
        return 0.0
    denom = max(worst - best, 1e-9)
    ratio = (worst - range10) / denom
    return ratio * max_points


def score_capital_impact(capital_impact: float, reference: float, max_points: float) -> float:
    if not _safe(capital_impact) or capital_impact <= 0:
        return 0.0
    denom = max(reference, 1e-9)
    normalized = min(1.0, capital_impact / denom)
    return normalized * max_points


def score_distribution_penalty(distribution_warning: bool, penalty: float) -> float:
    return -penalty if distribution_warning else 0.0


# ---------------------------------------------------------------------------
# Trigger Score component functions (pure)
# ---------------------------------------------------------------------------

def score_rvol(rvol20: float, reference: float, max_points: float) -> float:
    # +inf/-inf are treated as invalid (same as NaN) via _safe(), not saturated —
    # consistent with every other scoring component below. In practice RVOL20
    # is never +inf: features.py turns zero-denominator cases into NaN upstream.
    if not _safe(rvol20) or rvol20 <= 1.0:
        return 0.0
    denom = max(reference - 1.0, 1e-9)
    normalized = (rvol20 - 1.0) / denom
    normalized = max(0.0, min(1.0, normalized))
    return normalized * max_points


def score_flag(flag: bool, points: float) -> float:
    return points if flag else 0.0


def score_above_ma(close: float, ma: float, points: float) -> float:
    if not _safe(close) or not _safe(ma):
        return 0.0
    return points if close > ma else 0.0


def score_state_bonus(state: sm.State, use_state_bonus: bool, state_bonus: dict) -> float:
    if not use_state_bonus:
        return 0.0
    return state_bonus.get(state.name, 0)


# ---------------------------------------------------------------------------
# Aggregate scores. Each returns {"total": float, "components": {name: float}}
# so the breakdown can be persisted for debugging/backtesting, not just the
# final number.
# ---------------------------------------------------------------------------

def compute_structure_score(
    event_score: float,
    event_low_hold: bool,
    estimated_cost_hold: bool,
    cost_distance: float,
    vcr: float,
    range10: float,
    capital_impact: float,
    distribution_warning: bool,
    cfg,
) -> dict:
    sc = cfg.structure_scoring
    components = {
        "event": score_event(event_score, sc.event_score_weight),
        "low_hold": score_hold(event_low_hold, sc.low_hold_points),
        "cost_hold": score_hold(estimated_cost_hold, sc.cost_hold_points),
        "cost_distance": score_cost_distance(
            cost_distance, sc.cost_distance.ideal_min, sc.cost_distance.ideal_max,
            sc.cost_distance.max_points, sc.cost_distance.penalty_scale,
        ),
        "vcr": score_vcr(
            vcr, sc.vcr.strong_threshold, sc.vcr.normal_threshold, sc.vcr.weak_threshold,
            sc.vcr.strong_points, sc.vcr.normal_points, sc.vcr.weak_points,
        ),
        "compression": score_compression(range10, sc.compression.best, sc.compression.worst, sc.compression.max_points),
        "capital_impact": score_capital_impact(capital_impact, sc.capital_impact.reference, sc.capital_impact.max_points),
        "distribution_penalty": score_distribution_penalty(distribution_warning, sc.distribution_penalty),
    }
    total = _clamp(sum(components.values()))
    return {"total": total, "components": components}


def compute_trigger_score(
    ma240_cross: bool,
    ma120_cross: bool,
    ma5_slope: float,
    hh60_break: bool,
    resistance_break: bool,
    rvol20: float,
    close: float,
    ma240: float,
    state: sm.State,
    cfg,
) -> dict:
    tc = cfg.trigger_scoring
    components = {
        "ma240_cross": score_flag(ma240_cross, tc.ma240_cross_points),
        "ma120_cross": score_flag(ma120_cross, tc.ma120_cross_points),
        "ma5_slope": score_flag(_safe(ma5_slope) and ma5_slope > 0, tc.ma5_slope_points),
        "previous_high_break": score_flag(hh60_break, tc.previous_high_break_points),
        "trend_break": score_flag(resistance_break, tc.trend_break_points),
        "rvol": score_rvol(rvol20, tc.rvol.reference, tc.rvol.max_points),
        "above_ma240": score_above_ma(close, ma240, tc.above_ma240_points),
        "state_bonus": score_state_bonus(state, tc.use_state_bonus, tc.state_bonus),
    }
    total = _clamp(sum(components.values()))
    return {"total": total, "components": components}


def compute_final_score(structure_total: float, trigger_total: float, theme_score: float | None, cfg) -> float:
    if theme_score is None:
        return _clamp(structure_total * cfg.score_weight_structure_no_theme + trigger_total * cfg.score_weight_trigger_no_theme)
    return _clamp(
        structure_total * cfg.score_weight_structure_with_theme
        + trigger_total * cfg.score_weight_trigger_with_theme
        + theme_score * cfg.score_weight_theme
    )


def is_candidate(state: sm.State) -> bool:
    """INVALIDATED tickers are never alert candidates regardless of score —
    an INVALIDATED transition may still be notified as its own message type,
    but must never appear in a ranked "top candidates" list."""
    return state != sm.State.INVALIDATED
