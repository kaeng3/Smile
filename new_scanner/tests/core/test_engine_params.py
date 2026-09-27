# tests/test_engine_params.py
"""Parameterizable engine: prepare/scan split, cost tolerance mode, sweep parameters."""
from __future__ import annotations
import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv_df
from jusmo_scanner.config import load_config, override_config
from jusmo_scanner.scanner import engine, state_machine as sm

S = sm.State


def _cfg():
    return load_config("config/scanner.yaml")


def _bars(n: int, c: float = 1000, h: float | None = None, l: float | None = None,
          v: float = 100000, tv: float = 1_000_000_000) -> list[dict]:
    h = c + 10 if h is None else h
    l = c - 10 if l is None else l
    return [{"close": c, "high": h, "low": l, "open": c, "volume": v, "trading_value": tv} for _ in range(n)]


def _event(tv: float = 60_000_000_000) -> list[dict]:
    return [{"close": 1000, "high": 1020, "low": 980, "open": 1000, "volume": 500000, "trading_value": tv}]


def _states(scan: engine.TickerScan) -> list[S]:
    return [r.state for r in scan.results]


def _first(scan: engine.TickerScan, state: S) -> int | None:
    return next((i for i, r in enumerate(scan.results) if r.state == state), None)


def _random_ticker(seed: int, n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 1000 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, n)))
    volume = rng.integers(80_000, 120_000, n).astype(float)
    tv = volume * close
    for b in range(60, n, 45):
        volume[b] *= 6
        tv[b] = 60_000_000_000.0
    rows = [{"close": close[i], "high": high[i], "low": low[i], "open": close[i - 1] if i else close[0],
             "volume": volume[i], "trading_value": tv[i]} for i in range(n)]
    return make_ohlcv_df(rows)


def _same(a: engine.TickerScan, b: engine.TickerScan) -> bool:
    """Full-field equality (dataclass == is NaN-unsafe; repr is exact for floats)."""
    return repr(dataclasses.asdict(a)) == repr(dataclasses.asdict(b))


def _fingerprint(scan: engine.TickerScan) -> list[tuple]:
    return [(r.scan_date, r.state, r.prev_state, r.final_score, r.estimated_cost, r.episode_id)
            for r in scan.results]


# --- config helpers ---------------------------------------------------------

def test_cost_hold_tolerance_defaults_to_none_and_loads(tmp_path):
    assert _cfg().cost_hold_tolerance_pct is None
    text = Path("config/scanner.yaml").read_text(encoding="utf-8")
    p = tmp_path / "s.yaml"
    p.write_text(text.replace("cost_hold_tolerance_pct: null", "cost_hold_tolerance_pct: 0.03"), encoding="utf-8")
    assert load_config(p).cost_hold_tolerance_pct == 0.03
    p.write_text(text.replace("  cost_hold_tolerance_pct: null", ""), encoding="utf-8")  # key absent -> None
    assert load_config(p).cost_hold_tolerance_pct is None


def test_override_config_replaces_and_rejects_unknown_fields():
    cfg = _cfg()
    new = override_config(cfg, dormant_vcr_max=0.2, cost_hold_tolerance_pct=0.05)
    assert (new.dormant_vcr_max, new.cost_hold_tolerance_pct) == (0.2, 0.05)
    assert cfg.dormant_vcr_max == 0.40  # original untouched
    with pytest.raises(ValueError, match="dormant_vcr"):
        override_config(cfg, dormant_vcr=0.2)


@pytest.mark.parametrize("bad", [-0.01, 1.0, 1.5, float("nan"), "0.03", True])
def test_cost_hold_tolerance_validated_in_override_and_load(bad, tmp_path):
    with pytest.raises(ValueError, match="cost_hold_tolerance_pct"):
        override_config(_cfg(), cost_hold_tolerance_pct=bad)
    text = Path("config/scanner.yaml").read_text(encoding="utf-8")
    p = tmp_path / "s.yaml"
    yaml_val = {True: "true", "0.03": "'0.03'"}.get(bad, repr(bad).replace("nan", ".nan"))
    p.write_text(text.replace("cost_hold_tolerance_pct: null", f"cost_hold_tolerance_pct: {yaml_val}"), encoding="utf-8")
    with pytest.raises(ValueError, match="cost_hold_tolerance_pct"):
        load_config(p)


def test_cost_hold_tolerance_boundaries_and_field_position():
    cfg = _cfg()
    assert override_config(cfg, cost_hold_tolerance_pct=0).cost_hold_tolerance_pct == 0
    assert override_config(cfg, cost_hold_tolerance_pct=0.999).cost_hold_tolerance_pct == 0.999
    assert override_config(cfg, cost_hold_tolerance_pct=None).cost_hold_tolerance_pct is None
    # Optional (defaulted) fields sit at the end: cost_hold_tolerance_pct is the first
    # of them and every field after it (Stage 2 backtest settings) has a default too.
    flds = dataclasses.fields(type(cfg))
    names = [f.name for f in flds]
    k = names.index("cost_hold_tolerance_pct")
    assert all(f.default is dataclasses.MISSING for f in flds[:k])
    assert all(f.default is not dataclasses.MISSING for f in flds[k:])


def test_sweep_axes_have_a_single_source_of_truth():
    import jusmo_scanner.config as config_module
    from jusmo_scanner.backtest import parameter_grid
    assert not hasattr(config_module, "SWEEP_PARAMETER_FIELDS")   # no second (stale) table
    fields = {f.name for f in dataclasses.fields(type(_cfg()))}
    cfg = _cfg()
    assert len(parameter_grid.PARAMETER_VARIANTS) == 8
    for axis, variants in parameter_grid.PARAMETER_VARIANTS.items():
        assert variants, axis
        for v in variants:
            assert set(v.overrides) <= fields, (axis, v.id, set(v.overrides) - fields)
            override_config(cfg, **v.overrides)                    # accepted (validated) by the config


# --- prepare / scan_prepared ------------------------------------------------

def test_scan_prepared_reuse_across_configs_equals_fresh_scan_ticker():
    df = _random_ticker(1)
    cfg = _cfg()
    cfgs = [
        cfg,
        override_config(cfg, core_event_trading_value=30_000_000_000, dormant_vcr_max=0.9),
        override_config(cfg, cost_hold_tolerance_pct=0.03),
        override_config(cfg, atr_tolerance_event_low=0.0, dormant_range10_max=0.5),
        override_config(cfg, pullback_drawdown_min=-0.08, pullback_drawdown_max=-0.03),
    ]
    prepared = engine.prepare_ticker(df, cfg.breakout_swing_window)
    for c in cfgs + cfgs[::-1]:  # two orders: no state may leak between calls
        assert _same(engine.scan_prepared(prepared, "T", c), engine.scan_ticker(df, "T", c))


def test_prepared_reuse_across_event_thresholds_does_not_cache_events():
    """One PreparedTicker reused across thresholds on a frame whose events have
    mixed sizes: config-dependent events cached in prepare would leak between calls."""
    df = make_ohlcv_df(_bars(30) + _event(35e9) + _bars(8) + _event(55e9) + _bars(8) + _event(80e9) + _bars(8))
    cfg = _cfg()
    thresholds = (30e9, 50e9, 70e9)
    cfgs = {t: override_config(cfg, core_event_trading_value=t) for t in thresholds}
    fresh = {t: engine.scan_ticker(df, "T", c) for t, c in cfgs.items()}
    assert [len(fresh[t].events) for t in thresholds] == [3, 2, 1]  # counts differ across thresholds
    prepared = engine.prepare_ticker(df, cfg.breakout_swing_window)
    for order in (thresholds, thresholds[::-1], (50e9, 30e9, 70e9, 30e9)):
        for t in order:
            assert _same(engine.scan_prepared(prepared, "T", cfgs[t]), fresh[t]), (order, t)


def test_scan_prepared_rejects_mismatched_swing_window():
    df = make_ohlcv_df(_bars(30) + _event())
    cfg = _cfg()
    prepared = engine.prepare_ticker(df, cfg.breakout_swing_window + 1)
    with pytest.raises(ValueError, match="swing_window"):
        engine.scan_prepared(prepared, "T", cfg)


def test_prepare_ticker_holds_no_config_dependent_state():
    df = make_ohlcv_df(_bars(30) + _event())
    prepared = engine.prepare_ticker(df, 5)
    assert not any("event" in f.name for f in dataclasses.fields(prepared))
    assert prepared.last_bar_date == df["date"].iloc[-1]
    assert engine.prepare_ticker(df.iloc[0:0], 5).last_bar_date is None


# --- cost_hold_tolerance_pct -----------------------------------------------

def _tol_df(last_close: float, n_after: int = 3) -> pd.DataFrame:
    return make_ohlcv_df(_bars(30) + _event() + _bars(n_after) + _bars(1, c=last_close))


def test_tolerance_none_equals_atr_rule_and_pct_floor_differs():
    cfg = _cfg()
    df = _tol_df(965)  # cost ~998; ATR floor ~955 < 965 < pct floor 968
    atr_scan = engine.scan_ticker(df, "T", cfg)
    assert atr_scan.results[-1].state != S.INVALIDATED
    assert _same(engine.scan_ticker(df, "T", override_config(cfg, cost_hold_tolerance_pct=None)), atr_scan)
    pct_scan = engine.scan_ticker(df, "T", override_config(cfg, cost_hold_tolerance_pct=0.03))
    assert pct_scan.results[-1].state == S.INVALIDATED
    # Non-final bars and the reported (real) estimated_cost are unaffected by the mode
    assert _states(pct_scan)[:-1] == _states(atr_scan)[:-1]
    assert pct_scan.results[-1].estimated_cost == atr_scan.results[-1].estimated_cost


def test_wide_tolerance_holds_where_atr_rule_invalidates():
    cfg = override_config(_cfg(), atr_tolerance_event_low=10.0)  # isolate the cost rule
    df = _tol_df(940)  # ATR floor ~955 > 940 > 7% floor ~928
    assert engine.scan_ticker(df, "T", cfg).results[-1].state == S.INVALIDATED
    wide = engine.scan_ticker(df, "T", override_config(cfg, cost_hold_tolerance_pct=0.07))
    assert wide.results[-1].state != S.INVALIDATED


def test_close_exactly_at_floor_holds_and_just_below_invalidates():
    # cost = event_price exactly (weights 1/0) so the floor is independent of the closing bar
    tol = 0.05
    floor = 1000.0 * (1 - tol)
    cfg = override_config(_cfg(), cost_weight_event_price=1.0, cost_weight_vwap=0.0,
                          atr_tolerance_event_low=10.0, cost_hold_tolerance_pct=tol)
    at = engine.scan_ticker(make_ohlcv_df(_bars(30) + _event() + _bars(2) + _bars(1, c=floor)), "T", cfg)
    assert at.results[-1].estimated_cost == 1000.0
    assert at.results[-1].close == floor and at.results[-1].state != S.INVALIDATED
    assert at.results[-1].structure_components["cost_hold"] > 0
    below = engine.scan_ticker(
        make_ohlcv_df(_bars(30) + _event() + _bars(2) + _bars(1, c=float(np.nextafter(floor, 0)))), "T", cfg)
    assert below.results[-1].state == S.INVALIDATED


def test_tolerance_mode_is_causal_truncation_invariant():
    cfg = override_config(_cfg(), cost_hold_tolerance_pct=0.03)
    df = _random_ticker(7)
    full = engine.scan_ticker(df, "T", cfg)
    assert S.INVALIDATED in _states(full)  # the fixture must actually exercise the mode
    fp = _fingerprint(full)
    for k in (70, 100, 151, 233, 300, 399):
        part = engine.scan_ticker(df.iloc[:k].reset_index(drop=True), "T", cfg)
        assert _fingerprint(part) == [x for x in fp if x[0] <= df["date"].iloc[k - 1]]


# --- each sweep parameter demonstrably changes behavior -----------------------

def test_event_trading_value_changes_event_count():
    df = make_ohlcv_df(_bars(30) + _event(60e9) + _bars(5) + _event(40e9) + _bars(5))
    cfg = _cfg()
    counts = {tv: len(engine.scan_ticker(df, "T", override_config(cfg, core_event_trading_value=tv)).events)
              for tv in (30e9, 50e9, 70e9)}
    assert counts == {30e9: 2, 50e9: 1, 70e9: 0}


def test_dormant_vcr_max_changes_dormant_timing():
    # post-event volume decays, so VCR (5-bar avg volume / event volume) falls through the thresholds
    post = [r for v in (400000, 300000, 250000, 200000, 150000, 120000, 100000) for r in _bars(1, v=v)]
    df = make_ohlcv_df(_bars(125) + _event() + post + _bars(10))
    df.loc[25, 'high'] = 1100
    cfg = _cfg()
    first = {v: _first(engine.scan_ticker(df, "T", override_config(cfg, dormant_vcr_max=v)), S.DORMANT)
             for v in (0.4, 0.3, 0.2)}
    assert None not in first.values()
    assert first[0.4] < first[0.3] < first[0.2]


def test_dormant_range10_max_changes_dormant_timing():
    # wide bars just before the event roll out of the (shifted) 10-bar window progressively
    wide = _bars(5, h=1090, l=925) + _bars(5, h=1050, l=955)
    df = make_ohlcv_df(_bars(125) + wide + _event() + _bars(15))
    df.loc[35, 'high'] = 1250
    cfg = _cfg()
    first = {r: _first(engine.scan_ticker(df, "T", override_config(cfg, dormant_range10_max=r)), S.DORMANT)
             for r in (0.20, 0.15, 0.08)}
    assert None not in first.values()
    assert first[0.20] < first[0.15] < first[0.08]


def test_atr_tolerance_event_low_changes_invalidation():
    # close 970 is below the event low (980) by less than one ATR (~21)
    df = make_ohlcv_df(_bars(30) + _event() + _bars(3) + _bars(1, c=970) + _bars(2))
    cfg = _cfg()
    lenient = engine.scan_ticker(df, "T", override_config(cfg, atr_tolerance_event_low=1.0))
    strict = engine.scan_ticker(df, "T", override_config(cfg, atr_tolerance_event_low=0.0))
    assert S.INVALIDATED not in _states(lenient)
    assert _states(strict)[4] == S.INVALIDATED


def _pullback_df() -> pd.DataFrame:
    rows = _bars(125) + _event() + _bars(5)
    rows[25]['high'] = 1100
    rows.append({"close": 1200, "high": 1250, "low": 1100, "open": 1050,
                 "volume": 5_000_000, "trading_value": 1_000_000_000})
    rows += [{"close": 1125, "high": 1130, "low": 1120, "open": 1125,  # -10% from breakout high 1250
              "volume": 100000, "trading_value": 1_000_000_000} for _ in range(3)]
    return make_ohlcv_df(rows)


def test_pullback_bounds_change_pullback_entry():
    df = _pullback_df()
    cfg = _cfg()
    base = engine.scan_ticker(df, "T", cfg)
    assert _first(base, S.BREAKOUT) is not None and _first(base, S.PULLBACK) is not None
    narrow = engine.scan_ticker(df, "T", override_config(cfg, pullback_drawdown_min=-0.08, pullback_drawdown_max=-0.03))
    assert _first(narrow, S.PULLBACK) is None
    shallow_only = engine.scan_ticker(df, "T", override_config(cfg, pullback_drawdown_min=-0.12, pullback_drawdown_max=-0.11))
    assert _first(shallow_only, S.PULLBACK) is None
