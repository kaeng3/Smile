from __future__ import annotations

import dataclasses
import json
from datetime import date

import pandas as pd
import pytest

from jusmo_scanner.config import load_config, override_config
from jusmo_scanner.scanner import engine, state_machine as sm
from jusmo_scanner.scanner.snapshot import SignalSnapshot
from tests import synthetic as syn
from tests.conftest import make_ohlcv_df

CFG = load_config("config/scanner.yaml")
_PLAIN = (float, int, str, bool, date, type(None))


def _scan(df, cfg=CFG, snaps=True, ticker="T"):
    return engine.scan_ticker(df, ticker, cfg, collect_snapshots=snaps)


def _path(scan):
    """[(result index, prev, new)] for state changes."""
    return [(i, r.prev_state.name, r.state.name) for i, r in enumerate(scan.results) if r.state != r.prev_state]


# --- fixtures reach the states they claim (verified empirically) ------------

def test_success_fixture_state_path():
    scan = _scan(syn.success_frame())
    assert len(scan.snapshots) == len(scan.results)
    assert [(p, n) for _, p, n in _path(scan)] == [
        ("EVENT", "ACCUMULATION"), ("ACCUMULATION", "DORMANT"), ("DORMANT", "IGNITION"),
        ("IGNITION", "BREAKOUT"), ("BREAKOUT", "PULLBACK"),
    ]
    assert scan.results[-1].state == sm.State.PULLBACK  # +20% later: no BREAKOUT re-entry
    assert scan.results[-1].close > 1.15 * scan.results[_path(scan)[-1][0]].close


def test_failure_fixture_state_path():
    scan = _scan(syn.failure_frame())
    assert [n for _, _, n in _path(scan)] == ["COST_TRACKING", "INVALIDATED"]  # short history: UNKNOWN
    assert scan.results[-1].state == sm.State.INVALIDATED  # nothing after it


def test_repeated_events_fixture_is_one_episode_with_three_events():
    scan = _scan(syn.repeated_events_frame())
    assert len({r.episode_id for r in scan.results}) == 1
    assert [e.event.event_score for e in scan.events] == [100.0, 50.0, 100.0]
    assert scan.results[-1].event_count == 3
    assert scan.results[-1].state != sm.State.INVALIDATED


# --- API / identity ----------------------------------------------------------

def test_results_identical_with_and_without_snapshots():
    for df in (syn.success_frame(), syn.failure_frame(), syn.repeated_events_frame(), syn.random_frame(3)):
        a = _scan(df, snaps=False)
        b = _scan(df, snaps=True)
        assert a.snapshots is None
        # repr comparison: NaN != NaN under ==
        assert repr(a.results) == repr(b.results) and repr(a.events) == repr(b.events)
        assert a.last_bar_date == b.last_bar_date


def test_backtest_config_does_not_change_scanner_output():
    df = syn.success_frame()
    a = _scan(df, snaps=False)
    b = _scan(df, override_config(CFG, backtest_accumulation_min_days=9, backtest_accumulation_vcr_max=0.01))
    assert repr(a.results) == repr(b.results)


def test_snapshot_is_frozen_and_scan_result_not_extended():
    snap = _scan(syn.success_frame()).snapshots[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.close = 1.0  # type: ignore[misc]
    assert not hasattr(engine.ScanResult, "snapshots")
    assert "vcr_latest_event" not in {f.name for f in dataclasses.fields(engine.ScanResult)}


def test_snapshot_values_are_plain_python_and_json_safe():
    for df in (syn.success_frame(), syn.random_frame(5)):
        for snap in _scan(df).snapshots:
            for f in dataclasses.fields(SignalSnapshot):
                v = getattr(snap, f.name)
                assert type(v) in _PLAIN, (f.name, type(v))
            d = snap.to_dict()
            json.dumps(d, allow_nan=False)
            assert isinstance(d["signal_date"], str)


def test_short_history_gives_none_not_zero_and_no_crash():
    rows = [{"close": 1000, "high": 1010, "low": 990, "open": 1000,
             "volume": 100000, "trading_value": 1_000_000_000} for _ in range(8)]
    rows.append({"close": 1000, "high": 1020, "low": 980, "open": 1000, "volume": 500000,
                 "trading_value": 60_000_000_000})
    rows += [{"close": 1000, "high": 1010, "low": 990, "open": 1000, "volume": 90000} for _ in range(3)]
    scan = _scan(make_ohlcv_df(rows))
    s = scan.snapshots[-1]
    assert s.ma240 is None and s.ma120 is None and s.ma60 is None
    assert s.above_ma240 is None and s.prior_high is None and s.prior_high_distance is None
    assert s.cross_ma240 is False and s.previous_high_break is False
    assert s.name is None  # no `name` column
    assert s.breakout_date is None and s.pullback_depth is None and s.previous_high_hold is None
    assert s.ma5 is not None


def test_zero_free_float_gives_none_turnover():
    rows = [{"close": 1000, "high": 1010, "low": 990, "open": 1000,
             "volume": 100000, "trading_value": 1_000_000_000} for _ in range(30)]
    rows.append({"close": 1000, "high": 1020, "low": 980, "open": 1000, "volume": 500000,
                 "trading_value": 60_000_000_000, "free_float_shares": 0})
    snap = _scan(make_ohlcv_df(rows)).snapshots[0]
    assert snap.event_turnover is None
    assert snap.event_value_ratio is not None
    assert snap.event_strength_class == "STRONG" and snap.event_score == 100.0


def test_name_column_is_carried():
    assert _scan(syn.success_frame()).snapshots[0].name == "Synthetic Co"


# --- field definitions -------------------------------------------------------

def test_vcr_anchor_equals_result_vcr():
    for df in (syn.success_frame(), syn.repeated_events_frame(), syn.random_frame(1)):
        scan = _scan(df)
        for r, s in zip(scan.results, scan.snapshots):
            assert s.vcr_anchor == (None if r.vcr != r.vcr else r.vcr)
            assert (s.bar_index, s.signal_date, s.state, s.previous_state, s.episode_id) == (
                s.bar_index, r.scan_date.date(), r.state.name, r.prev_state.name, r.episode_id)
            assert s.final_score == r.final_score and s.structure_score == r.structure_score
            assert s.estimated_cost == r.estimated_cost and s.close == r.close


def test_multi_event_vcr_cluster_and_density_hand_checked():
    df = syn.repeated_events_frame()
    scan = _scan(df)
    by_idx = {s.bar_index: s for s in scan.snapshots}
    # bar 85 = second event (vol 400k); AVG_VOLUME_5 = mean(vol[80..84]) = (500k + 4*60k)/5 = 148k
    s = by_idx[85]
    assert s.event_added_this_bar and not s.strong_event_this_bar and s.event_count_so_far == 2
    assert s.vcr_anchor == pytest.approx(148_000 / 500_000)
    assert s.vcr_latest_event == pytest.approx(148_000 / 400_000)
    assert s.vcr_max_event == pytest.approx(148_000 / 500_000)
    assert s.cluster_trading_value_so_far == pytest.approx(160e9)
    assert s.event_low == 970.0 and s.event_low_distance == pytest.approx((1000 - 970) / 970)
    assert s.events_in_last_20d == 2
    # bar 90: AVG_VOLUME_5 = mean(vol[85..89]) = (400k + 4*60k)/5 = 128k
    s = by_idx[90]
    assert not s.event_added_this_bar
    assert s.vcr_latest_event == pytest.approx(128_000 / 400_000)
    assert s.vcr_max_event == pytest.approx(128_000 / 500_000)
    # density window is bars i-19..i: bar 99 still sees bar 80, bar 100 does not
    assert by_idx[99].events_in_last_20d == 2 and by_idx[100].events_in_last_20d == 1
    # bar 105 = third, strong event (vol 900k); AVG_VOLUME_5 = 60k
    s = by_idx[105]
    assert s.strong_event_this_bar and s.event_count_so_far == 3
    assert s.vcr_anchor == pytest.approx(60_000 / 500_000)
    assert s.vcr_latest_event == pytest.approx(60_000 / 900_000)
    assert s.vcr_max_event == pytest.approx(60_000 / 900_000)
    assert s.cluster_trading_value_so_far == pytest.approx(360e9)
    assert s.event_low == 960.0
    assert s.events_in_last_20d == 1
    # anchor fields never change with later events
    assert {x.event_score for x in scan.snapshots} == {100.0}
    assert {x.event_trading_value for x in scan.snapshots} == {100e9}
    assert by_idx[80].days_since_event_trading == 0 and by_idx[105].days_since_event_trading == 25


def test_anchor_close_location_and_strength_class():
    s = _scan(syn.success_frame()).snapshots[0]
    # event bar: high 960, low 890, close 940
    assert s.event_close_location == pytest.approx((940 - 890) / (960 - 890))
    assert s.event_strength_class == "STRONG"
    core = _scan(syn.repeated_events_frame())
    assert core.snapshots[0].event_strength_class == "STRONG"


def test_success_fixture_breakout_context():
    scan = _scan(syn.success_frame())
    path = {n: i for i, _, n in _path(scan)}
    snaps = scan.snapshots
    assert all(s.breakout_date is None and s.days_since_breakout is None for s in snaps[: path["BREAKOUT"]])
    b = snaps[path["BREAKOUT"]]
    assert b.days_since_breakout == 0 and b.breakout_price == 1100.0 and b.breakout_high == 1120.0
    p = snaps[path["PULLBACK"]]
    assert p.days_since_breakout == 1
    assert p.pullback_depth == pytest.approx((1040 - 1120) / 1120)
    assert p.pullback_volume_ratio == pytest.approx(100_000 / 600_000)
    assert p.distance_to_ma240 == pytest.approx((1040 - p.ma240) / p.ma240)
    assert p.previous_high_hold is True  # 1040 >= HH60 in force at the breakout bar (~1010)
    assert p.breakout_date == snaps[path["BREAKOUT"]].signal_date
    # cross features on the IGNITION bar (single jump through MA120 and MA240)
    ig = snaps[path["IGNITION"]]
    assert ig.cross_ma240 and ig.cross_ma120 and ig.above_ma240 and ig.previous_high_break


def test_previous_high_hold_false_when_close_below_breakout_level():
    scan = _scan(syn.success_frame())
    bo_idx = [i for i, _, n in _path(scan) if n == "BREAKOUT"][0]
    level = scan.snapshots[bo_idx].prior_high
    assert level is not None
    assert scan.snapshots[bo_idx + 1].close >= level  # fixture: holds
    # cut the frame's pullback bar to close just below the breakout-bar HH60
    df = syn.success_frame()
    df.loc[syn.SUCCESS_N_BASE + bo_idx + 1, ["close", "low"]] = [level - 1.0, level - 2.0]
    snap = _scan(df).snapshots[bo_idx + 1]
    assert snap.previous_high_hold is False


# --- accumulation_confirmed boundaries --------------------------------------

def _snap_at(df, cfg, idx):
    return next(s for s in _scan(df, cfg).snapshots if s.bar_index == idx)


def test_accumulation_confirmed_min_days_boundary():
    df = syn.success_frame()
    ev = syn.SUCCESS_N_BASE
    # at days_since_event == 3 everything else holds (vcr ~0.29, holds)
    for min_days, expected in ((3, True), (4, False), (2, True)):
        cfg = override_config(CFG, backtest_accumulation_min_days=min_days)
        assert _snap_at(df, cfg, ev + 3).accumulation_confirmed is expected
    cfg3 = override_config(CFG, backtest_accumulation_min_days=3)
    s2 = _snap_at(df, cfg3, ev + 2)
    assert s2.days_since_event_trading == 2 and s2.accumulation_confirmed is False


def test_accumulation_confirmed_vcr_boundary_is_inclusive():
    df = syn.success_frame()
    idx = syn.SUCCESS_N_BASE + 5
    v = _snap_at(df, CFG, idx).vcr_anchor
    assert v is not None
    assert _snap_at(df, override_config(CFG, backtest_accumulation_vcr_max=v), idx).accumulation_confirmed is True
    assert _snap_at(df, override_config(CFG, backtest_accumulation_vcr_max=v * 0.999), idx).accumulation_confirmed is False


def test_accumulation_confirmed_requires_holds():
    scan = _scan(syn.failure_frame())
    last = scan.snapshots[-1]  # INVALIDATED bar: event low breached
    assert last.state == "INVALIDATED" and last.accumulation_confirmed is False


def test_accumulation_config_validation():
    for bad in ({"backtest_accumulation_min_days": -1}, {"backtest_accumulation_min_days": 1.5},
                {"backtest_accumulation_min_days": True}, {"backtest_accumulation_vcr_max": 0},
                {"backtest_accumulation_vcr_max": "x"}):
        with pytest.raises(ValueError):
            override_config(CFG, **bad)
    assert CFG.backtest_accumulation_min_days == 3 and CFG.backtest_accumulation_vcr_max == 0.50


# --- causality ---------------------------------------------------------------

def _cut_frames():
    yield "succ", syn.success_frame(), (272, 280, 286, 289, 290, 293, 299)
    yield "multi", syn.repeated_events_frame(), (80, 84, 85, 90, 105, 108)
    yield "fail", syn.failure_frame(), (80, 82, 84, 86)
    for seed in range(4):
        yield f"rnd{seed}", syn.random_frame(seed), (150, 200, 250, 300)


def test_snapshots_identical_between_full_and_truncated_frames():
    checked = 0
    for name, df, cuts in _cut_frames():
        full = {s.bar_index: s for s in _scan(df).snapshots}
        for cut in cuts:
            part = _scan(df.iloc[: cut + 1].reset_index(drop=True)).snapshots
            assert {s.bar_index for s in part} == {i for i in full if i <= cut}, (name, cut)
            for s in part:
                assert s == full[s.bar_index], (name, cut, s.bar_index)
                checked += 1
    assert checked > 200
