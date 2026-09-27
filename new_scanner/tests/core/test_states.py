# tests/test_states.py
from __future__ import annotations
from jusmo_scanner.scanner import state_machine as sm


def test_state_enum_values_match_spec():
    assert sm.State.INVALIDATED == -1
    assert sm.State.NONE == 0
    assert sm.State.EVENT == 1
    assert sm.State.ACCUMULATION == 2
    assert sm.State.DORMANT == 3
    assert sm.State.IGNITION == 4
    assert sm.State.BREAKOUT == 5
    assert sm.State.PULLBACK == 6


def test_golden_cross_true_when_close_crosses_above_ma():
    assert sm.is_golden_cross(prev_close=95, prev_ma=100, close=105, ma=100) is True


def test_golden_cross_false_when_already_above():
    assert sm.is_golden_cross(prev_close=105, prev_ma=100, close=110, ma=100) is False


def test_golden_cross_false_with_nan_ma_new_listing():
    import math
    assert sm.is_golden_cross(prev_close=95, prev_ma=float("nan"), close=105, ma=float("nan")) is False


def _thresholds():
    return sm.ScannerThresholds(
        dormant_vcr_max=0.40, dormant_range10_max=0.15,
        ignition_rvol20_min=1.5, breakout_rvol20_min=1.3,
        pullback_drawdown_min=-0.12, pullback_drawdown_max=-0.03,
        pullback_volume_ratio_max=0.5, atr_multiplier_invalidated=2.0,
        distribution_location120_min=0.80, distribution_rvol20_min=3.0,
        distribution_upper_wick_min=0.40,
    )


def _base_signals(**overrides):
    base = dict(
        event_low_hold=True, estimated_cost_hold=True, vcr=0.3, range10=0.1,
        ma5_slope=0.5, ma120_cross=False, ma240_cross=False, rvol20=1.0,
        hh60_break=False, resistance_break=False, had_breakout=False,
        breakout_high=None, close=1000, current_volume=1000, breakout_volume=None,
        event_low_limit=900, estimated_cost=950, atr20=20,
    )
    base.update(overrides)
    return sm.StateSignals(**base)


def test_is_dormant_true_when_all_conditions_met():
    assert sm.is_dormant(_base_signals(vcr=0.3, range10=0.1), _thresholds()) is True


def test_is_dormant_false_when_vcr_too_high():
    assert sm.is_dormant(_base_signals(vcr=0.9, range10=0.1), _thresholds()) is False


def test_is_dormant_false_when_event_low_not_held():
    assert sm.is_dormant(_base_signals(event_low_hold=False), _thresholds()) is False


def test_is_ignition_true_via_rvol():
    s = _base_signals(ma5_slope=0.5, ma120_cross=False, ma240_cross=False, rvol20=2.0)
    assert sm.is_ignition(s, _thresholds()) is True


def test_is_ignition_true_via_ma240_cross():
    s = _base_signals(ma5_slope=0.5, ma240_cross=True, rvol20=1.0)
    assert sm.is_ignition(s, _thresholds()) is True


def test_is_ignition_false_when_ma5_slope_not_positive():
    s = _base_signals(ma5_slope=-0.1, rvol20=5.0)
    assert sm.is_ignition(s, _thresholds()) is False


def test_is_ignition_false_when_holds_broken():
    s = _base_signals(estimated_cost_hold=False, rvol20=5.0)
    assert sm.is_ignition(s, _thresholds()) is False


def test_is_breakout_true_via_hh60_break():
    s = _base_signals(rvol20=1.5, hh60_break=True)
    assert sm.is_breakout(s, _thresholds()) is True


def test_is_breakout_true_via_resistance_break():
    s = _base_signals(rvol20=1.5, resistance_break=True)
    assert sm.is_breakout(s, _thresholds()) is True


def test_is_breakout_false_when_rvol_too_low():
    s = _base_signals(rvol20=1.0, hh60_break=True)
    assert sm.is_breakout(s, _thresholds()) is False


def test_is_pullback_true_within_drawdown_band_and_low_volume():
    s = _base_signals(
        had_breakout=True, breakout_high=1000, breakout_volume=10000,
        close=920, current_volume=4000,  # drawdown -8%, volume 40% of breakout
    )
    assert sm.is_pullback(s, _thresholds()) is True


def test_is_pullback_false_when_drawdown_too_deep():
    s = _base_signals(had_breakout=True, breakout_high=1000, breakout_volume=10000,
                       close=850, current_volume=4000)  # -15%, outside band
    assert sm.is_pullback(s, _thresholds()) is False


def test_is_pullback_false_when_volume_too_high():
    s = _base_signals(had_breakout=True, breakout_high=1000, breakout_volume=10000,
                       close=920, current_volume=6000)  # 60% of breakout volume
    assert sm.is_pullback(s, _thresholds()) is False


def test_is_pullback_false_without_prior_breakout():
    s = _base_signals(had_breakout=False, close=920)
    assert sm.is_pullback(s, _thresholds()) is False


def test_is_invalidated_true_when_event_low_breached():
    assert sm.is_invalidated(close=880, event_low_limit=900, estimated_cost=950, atr20=20, atr_multiplier=2.0) is True


def test_is_invalidated_true_when_cost_breached_by_two_atr():
    assert sm.is_invalidated(close=900, event_low_limit=800, estimated_cost=950, atr20=20, atr_multiplier=2.0) is True


def test_is_invalidated_false_when_holding():
    assert sm.is_invalidated(close=980, event_low_limit=900, estimated_cost=950, atr20=20, atr_multiplier=2.0) is False


def test_is_distribution_warning_true():
    assert sm.is_distribution_warning(
        location120=0.9, rvol20=4.0, upper_wick_ratio=0.5, close=990, open_=1000, cfg=_thresholds(),
    ) is True


def test_is_distribution_warning_false_when_close_above_open():
    assert sm.is_distribution_warning(
        location120=0.9, rvol20=4.0, upper_wick_ratio=0.5, close=1010, open_=1000, cfg=_thresholds(),
    ) is False


def test_next_state_advances_accumulation_to_breakout_directly():
    s = _base_signals(rvol20=2.0, hh60_break=True)
    result = sm.next_state(sm.State.ACCUMULATION, s, _thresholds())
    assert result == sm.State.BREAKOUT


def test_next_state_never_regresses_breakout_to_dormant_bug7():
    # DORMANT's own conditions happen to be true, but BREAKOUT is not in
    # BREAKOUT's allowed-transitions set, so it must stay BREAKOUT, not fall
    # back to DORMANT.
    s = _base_signals(vcr=0.1, range10=0.05, rvol20=0.5, hh60_break=False, resistance_break=False)
    result = sm.next_state(sm.State.BREAKOUT, s, _thresholds())
    assert result == sm.State.BREAKOUT


def test_next_state_stays_in_breakout_when_conditions_persist_bug8():
    # Repeated calls with the same still-qualifying signals must keep
    # returning BREAKOUT, not attempt to "re-enter" it via a different path.
    s = _base_signals(rvol20=2.0, hh60_break=True)
    result = sm.next_state(sm.State.BREAKOUT, s, _thresholds())
    assert result == sm.State.BREAKOUT


def test_next_state_moves_breakout_to_pullback():
    s = _base_signals(had_breakout=True, breakout_high=1000, breakout_volume=10000,
                       close=920, current_volume=4000)
    result = sm.next_state(sm.State.BREAKOUT, s, _thresholds())
    assert result == sm.State.PULLBACK


def test_next_state_invalidated_from_any_active_state():
    s = _base_signals(close=800, event_low_limit=900)
    for start in [sm.State.EVENT, sm.State.ACCUMULATION, sm.State.DORMANT,
                  sm.State.IGNITION, sm.State.BREAKOUT, sm.State.PULLBACK]:
        assert sm.next_state(start, s, _thresholds()) == sm.State.INVALIDATED


def test_next_state_event_always_advances_to_accumulation():
    s = _base_signals(rvol20=5.0, hh60_break=True)  # even if breakout-qualifying
    result = sm.next_state(sm.State.EVENT, s, _thresholds())
    assert result == sm.State.ACCUMULATION


def test_pullback_does_not_return_to_breakout():
    # signals satisfy both is_breakout and is_pullback (no invalidation)
    s = _base_signals(rvol20=2.0, hh60_break=True, had_breakout=True, breakout_high=1000,
                       breakout_volume=10000, close=920, current_volume=4000)
    assert sm.is_breakout(s, _thresholds()) is True
    assert sm.is_pullback(s, _thresholds()) is True
    assert sm.next_state(sm.State.PULLBACK, s, _thresholds()) == sm.State.PULLBACK
    inv = _base_signals(rvol20=2.0, hh60_break=True, close=800, event_low_limit=900)
    assert sm.next_state(sm.State.PULLBACK, inv, _thresholds()) == sm.State.INVALIDATED


def test_allowed_transitions_are_monotone():
    for a, targets in sm.ALLOWED_TRANSITIONS.items():
        for b in targets:
            if b != sm.State.INVALIDATED:
                assert int(b) > int(a), f"{a.name}->{b.name} regresses"
