from __future__ import annotations
import math
from jusmo_scanner.config import load_config
from jusmo_scanner.scanner import scoring, state_machine as sm


def _cfg():
    return load_config("config/scanner.yaml")


def test_null_theme_engine_returns_none():
    assert scoring.NullThemeEngine().get_score("005930") is None


def test_score_event_strong():
    assert scoring.score_event(100.0, 0.20) == 20.0


def test_score_event_core_only():
    assert scoring.score_event(50.0, 0.20) == 10.0


def test_score_event_nan_is_zero():
    assert scoring.score_event(float("nan"), 0.20) == 0.0


def test_score_hold_true():
    assert scoring.score_hold(True, 15) == 15


def test_score_hold_false():
    assert scoring.score_hold(False, 15) == 0


def test_score_cost_distance_within_ideal_band():
    for cd in [-0.02, 0.0, 0.05, 0.10]:
        assert scoring.score_cost_distance(cd, -0.02, 0.10, 15, 200.0) == 15


def test_score_cost_distance_below_ideal_min():
    assert math.isclose(scoring.score_cost_distance(-0.05, -0.02, 0.10, 15, 200.0), 9.0)


def test_score_cost_distance_far_below_clamps_to_zero():
    assert scoring.score_cost_distance(-0.10, -0.02, 0.10, 15, 200.0) == 0.0


def test_score_cost_distance_above_ideal_max():
    assert scoring.score_cost_distance(0.30, -0.02, 0.10, 15, 200.0) == 0.0


def test_score_cost_distance_nan_is_zero():
    assert scoring.score_cost_distance(float("nan"), -0.02, 0.10, 15, 200.0) == 0.0


def test_score_cost_distance_inf_is_zero():
    assert scoring.score_cost_distance(float("inf"), -0.02, 0.10, 15, 200.0) == 0.0
    assert scoring.score_cost_distance(float("-inf"), -0.02, 0.10, 15, 200.0) == 0.0


def test_score_vcr_zero_is_strong():
    assert scoring.score_vcr(0.0, 0.25, 0.40, 0.60, 15, 12, 6) == 15


def test_score_vcr_at_strong_threshold_boundary():
    assert scoring.score_vcr(0.25, 0.25, 0.40, 0.60, 15, 12, 6) == 15
    assert scoring.score_vcr(0.2501, 0.25, 0.40, 0.60, 15, 12, 6) == 12


def test_score_vcr_at_normal_threshold_boundary():
    assert scoring.score_vcr(0.40, 0.25, 0.40, 0.60, 15, 12, 6) == 12
    assert scoring.score_vcr(0.4001, 0.25, 0.40, 0.60, 15, 12, 6) == 6


def test_score_vcr_at_weak_threshold_boundary():
    assert scoring.score_vcr(0.60, 0.25, 0.40, 0.60, 15, 12, 6) == 6
    assert scoring.score_vcr(0.6001, 0.25, 0.40, 0.60, 15, 12, 6) == 0


def test_score_vcr_negative_is_zero():
    assert scoring.score_vcr(-0.1, 0.25, 0.40, 0.60, 15, 12, 6) == 0.0


def test_score_vcr_nan_is_zero():
    assert scoring.score_vcr(float("nan"), 0.25, 0.40, 0.60, 15, 12, 6) == 0.0


def test_score_vcr_inf_is_zero():
    assert scoring.score_vcr(float("inf"), 0.25, 0.40, 0.60, 15, 12, 6) == 0.0


def test_score_compression_best_or_better():
    assert scoring.score_compression(0.05, 0.08, 0.20, 10) == 10


def test_score_compression_worst_or_beyond():
    assert scoring.score_compression(0.30, 0.08, 0.20, 10) == 0


def test_score_compression_values_between_best_and_worst():
    assert math.isclose(scoring.score_compression(0.10, 0.08, 0.20, 10), (0.20 - 0.10) / (0.20 - 0.08) * 10)
    assert math.isclose(scoring.score_compression(0.15, 0.08, 0.20, 10), (0.20 - 0.15) / (0.20 - 0.08) * 10)


def test_score_compression_degenerate_config_no_division_by_zero():
    result = scoring.score_compression(0.10, 0.10, 0.10, 10)
    assert result in (0.0, 10.0)


def test_score_compression_nan_is_zero():
    assert scoring.score_compression(float("nan"), 0.08, 0.20, 10) == 0.0


def test_score_compression_inf_is_zero():
    assert scoring.score_compression(float("inf"), 0.08, 0.20, 10) == 0.0


def test_score_capital_impact_at_reference_is_max():
    assert scoring.score_capital_impact(0.30, 0.30, 10) == 10


def test_score_capital_impact_below_reference_is_proportional():
    assert math.isclose(scoring.score_capital_impact(0.15, 0.30, 10), 5.0)


def test_score_capital_impact_above_reference_saturates():
    assert scoring.score_capital_impact(0.60, 0.30, 10) == 10
    assert scoring.score_capital_impact(3.0, 0.30, 10) == 10


def test_score_capital_impact_zero_or_negative_is_zero():
    assert scoring.score_capital_impact(0.0, 0.30, 10) == 0.0
    assert scoring.score_capital_impact(-0.1, 0.30, 10) == 0.0


def test_score_capital_impact_nan_is_zero():
    assert scoring.score_capital_impact(float("nan"), 0.30, 10) == 0.0


def test_score_capital_impact_inf_is_zero():
    assert scoring.score_capital_impact(float("inf"), 0.30, 10) == 0.0


def test_score_rvol_zero_and_one_are_zero():
    assert scoring.score_rvol(0.0, 3.0, 20) == 0.0
    assert scoring.score_rvol(1.0, 3.0, 20) == 0.0


def test_score_rvol_at_reference_is_max():
    assert scoring.score_rvol(3.0, 3.0, 20) == 20.0


def test_score_rvol_saturates_beyond_reference():
    assert scoring.score_rvol(10.0, 3.0, 20) == 20.0


def test_score_rvol_between_one_and_reference():
    assert math.isclose(scoring.score_rvol(2.0, 3.0, 20), (2.0 - 1.0) / (3.0 - 1.0) * 20)


def test_score_rvol_nan_is_zero():
    assert scoring.score_rvol(float("nan"), 3.0, 20) == 0.0


def test_score_rvol_inf_does_not_crash():
    assert scoring.score_rvol(float("inf"), 3.0, 20) == 0.0
    assert scoring.score_rvol(float("-inf"), 3.0, 20) == 0.0


def test_score_flag():
    assert scoring.score_flag(True, 20) == 20
    assert scoring.score_flag(False, 20) == 0


def test_score_above_ma():
    assert scoring.score_above_ma(110, 100, 10) == 10
    assert scoring.score_above_ma(90, 100, 10) == 0


def test_score_above_ma_nan_ma_is_zero():
    assert scoring.score_above_ma(110, float("nan"), 10) == 0.0


def test_score_above_ma_inf_ma_is_zero():
    assert scoring.score_above_ma(110, float("inf"), 10) == 0.0


def test_score_state_bonus_disabled_returns_zero():
    assert scoring.score_state_bonus(sm.State.BREAKOUT, False, {"BREAKOUT": 8}) == 0.0


def test_score_state_bonus_enabled_looks_up_state():
    assert scoring.score_state_bonus(sm.State.BREAKOUT, True, {"BREAKOUT": 8}) == 8


def test_compute_structure_score_returns_breakdown_dict():
    cfg = _cfg()
    result = scoring.compute_structure_score(
        event_score=100.0, event_low_hold=True, estimated_cost_hold=True,
        cost_distance=0.02, vcr=0.20, range10=0.08, capital_impact=0.30,
        distribution_warning=False, cfg=cfg,
    )
    assert "total" in result and "components" in result
    assert 0 <= result["total"] <= 100
    assert set(result["components"]) == {
        "event", "low_hold", "cost_hold", "cost_distance", "vcr",
        "compression", "capital_impact", "distribution_penalty",
    }


def test_compute_structure_score_distribution_warning_is_penalty():
    cfg = _cfg()
    clean = scoring.compute_structure_score(
        event_score=100.0, event_low_hold=True, estimated_cost_hold=True,
        cost_distance=0.02, vcr=0.20, range10=0.08, capital_impact=0.30,
        distribution_warning=False, cfg=cfg,
    )
    warned = scoring.compute_structure_score(
        event_score=100.0, event_low_hold=True, estimated_cost_hold=True,
        cost_distance=0.02, vcr=0.20, range10=0.08, capital_impact=0.30,
        distribution_warning=True, cfg=cfg,
    )
    assert warned["components"]["distribution_penalty"] == -cfg.structure_scoring.distribution_penalty
    assert warned["total"] < clean["total"]


def test_compute_structure_score_clamped_to_100():
    cfg = _cfg()
    result = scoring.compute_structure_score(
        event_score=100.0, event_low_hold=True, estimated_cost_hold=True,
        cost_distance=0.0, vcr=0.0, range10=0.0, capital_impact=10.0,
        distribution_warning=False, cfg=cfg,
    )
    assert result["total"] <= 100.0


def test_compute_trigger_score_returns_breakdown_dict():
    cfg = _cfg()
    result = scoring.compute_trigger_score(
        ma240_cross=True, ma120_cross=False, ma5_slope=0.5,
        hh60_break=True, resistance_break=False, rvol20=2.0,
        close=110, ma240=100, state=sm.State.BREAKOUT, cfg=cfg,
    )
    assert "total" in result and "components" in result
    assert 0 <= result["total"] <= 100
    assert set(result["components"]) == {
        "ma240_cross", "ma120_cross", "ma5_slope", "previous_high_break",
        "trend_break", "rvol", "above_ma240", "state_bonus",
    }


def test_compute_trigger_score_state_bonus_zero_by_default():
    cfg = _cfg()
    assert cfg.trigger_scoring.use_state_bonus is False
    result = scoring.compute_trigger_score(
        ma240_cross=False, ma120_cross=False, ma5_slope=0.0,
        hh60_break=False, resistance_break=False, rvol20=0.0,
        close=100, ma240=100, state=sm.State.BREAKOUT, cfg=cfg,
    )
    assert result["components"]["state_bonus"] == 0.0


def test_final_score_without_theme_uses_no_theme_weights():
    cfg = _cfg()
    final = scoring.compute_final_score(80, 60, None, cfg)
    assert final == 80 * cfg.score_weight_structure_no_theme + 60 * cfg.score_weight_trigger_no_theme


def test_final_score_with_theme_uses_theme_weights():
    cfg = _cfg()
    final = scoring.compute_final_score(80, 60, 50, cfg)
    expected = (
        80 * cfg.score_weight_structure_with_theme
        + 60 * cfg.score_weight_trigger_with_theme
        + 50 * cfg.score_weight_theme
    )
    assert final == expected


def test_final_score_clamped_when_theme_score_out_of_range():
    cfg = _cfg()
    final = scoring.compute_final_score(100, 100, 150, cfg)
    assert final == 100.0


def test_final_score_clamped_when_totals_out_of_range():
    cfg = _cfg()
    final = scoring.compute_final_score(200, 200, None, cfg)
    assert final == 100.0


def test_is_candidate_false_for_invalidated():
    assert scoring.is_candidate(sm.State.INVALIDATED) is False


def test_is_candidate_true_for_other_states():
    for state in [sm.State.EVENT, sm.State.ACCUMULATION, sm.State.DORMANT,
                  sm.State.IGNITION, sm.State.BREAKOUT, sm.State.PULLBACK]:
        assert scoring.is_candidate(state) is True
