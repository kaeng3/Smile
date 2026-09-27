from __future__ import annotations

import dataclasses
import inspect
import json

import numpy as np
import pandas as pd
import pytest

from jusmo_scanner.backtest import engine as bt
from jusmo_scanner.backtest.engine import (
    SampleMode, annotate_overlap, backtest_ticker, select_samples)
from jusmo_scanner.backtest.metrics import EntryMode, forward_metrics
from jusmo_scanner.backtest.signals import (
    SIGNAL_SEMANTICS, Signal, SignalCategory, SignalType, extract_signals, signal_semantics)
from jusmo_scanner.config import load_config
from jusmo_scanner.scanner import engine as scan_engine, scoring
from tests import synthetic as syn

CFG = load_config("config/scanner.yaml")


def _scan(df, cfg=CFG):
    return scan_engine.scan_ticker(df, "T", cfg, collect_snapshots=True)


def _types(signals):
    return [s.signal_type for s in signals]


def _bars(signals, t):
    return [s.bar_index for s in signals if s.signal_type is t]


# --- signal type model -------------------------------------------------------

def test_signal_types_and_categories():
    by_cat = {c: {t.name for t in SignalType if t.category is c} for c in SignalCategory}
    assert by_cat[SignalCategory.STATE] == {"EVENT", "ACCUMULATION", "DORMANT", "IGNITION", "BREAKOUT", "PULLBACK", "COST_TRACKING"}
    assert by_cat[SignalCategory.TRANSITION] == {
        "EVENT_TO_ACCUMULATION", "ACCUMULATION_TO_DORMANT", "DORMANT_TO_IGNITION",
        "IGNITION_TO_BREAKOUT", "BREAKOUT_TO_PULLBACK"}
    assert by_cat[SignalCategory.FEATURE] == {
        "MA120_CROSS", "MA240_CROSS", "PREVIOUS_HIGH_BREAK", "TREND_BREAK", "STRONG_EVENT",
        "MULTI_EVENT_CLUSTER", "ACCUMULATION_CONFIRMED"}
    assert len(SignalType) == 19
    assert "INVALIDATED" not in {t.name for t in SignalType}


def test_accumulation_semantics_label():
    for t in (SignalType.ACCUMULATION, SignalType.EVENT_TO_ACCUMULATION):
        assert SIGNAL_SEMANTICS[t].startswith("EVENT_BASELINE (unconfirmed")
        assert "not a confirmation of accumulation" in signal_semantics(t)
    assert signal_semantics(SignalType.BREAKOUT) == "STANDARD"
    assert set(SIGNAL_SEMANTICS) == {SignalType.EVENT, SignalType.ACCUMULATION, SignalType.EVENT_TO_ACCUMULATION,
                                     SignalType.ACCUMULATION_CONFIRMED}
    # the engine emits EVENT->ACCUMULATION ON the event bar (not the bar after it)
    for t in (SignalType.ACCUMULATION, SignalType.EVENT_TO_ACCUMULATION):
        assert "fires on the event bar itself" in SIGNAL_SEMANTICS[t]
        assert "same sample as EVENT and EVENT_TO_ACCUMULATION at the anchor bar" in SIGNAL_SEMANTICS[t]
        assert "bar after" not in SIGNAL_SEMANTICS[t]


def test_extract_signals_requires_snapshots():
    scan = scan_engine.scan_ticker(syn.success_frame(), "T", CFG)
    with pytest.raises(ValueError):
        extract_signals(scan)


# --- extraction on fixtures --------------------------------------------------

def test_success_fixture_extraction():
    scan = _scan(syn.success_frame())
    sigs = extract_signals(scan)
    types = set(_types(sigs))
    assert {SignalType.DORMANT_TO_IGNITION, SignalType.IGNITION_TO_BREAKOUT,
            SignalType.BREAKOUT_TO_PULLBACK, SignalType.EVENT_TO_ACCUMULATION,
            SignalType.ACCUMULATION_TO_DORMANT} <= types
    # all three categories are represented
    assert {s.category for s in sigs} == set(SignalCategory)
    # PULLBACK -> BREAKOUT was removed: BREAKOUT is entered exactly once
    assert len(_bars(sigs, SignalType.BREAKOUT)) == 1
    assert len(_bars(sigs, SignalType.IGNITION_TO_BREAKOUT)) == 1
    assert len(_bars(sigs, SignalType.BREAKOUT_TO_PULLBACK)) == 1
    assert len(_bars(sigs, SignalType.PULLBACK)) > 5  # PULLBACK state persists, incl. the later +20%
    # EVENT signal exists on the event bar although the engine never shows EVENT as a state
    assert _bars(sigs, SignalType.EVENT) == [syn.SUCCESS_N_BASE]
    assert _bars(sigs, SignalType.STRONG_EVENT) == [syn.SUCCESS_N_BASE]
    # the single jump through the MAs on the IGNITION bar
    ign = _bars(sigs, SignalType.DORMANT_TO_IGNITION)[0]
    assert ign in _bars(sigs, SignalType.MA240_CROSS) and ign in _bars(sigs, SignalType.MA120_CROSS)
    assert ign in _bars(sigs, SignalType.PREVIOUS_HIGH_BREAK)
    # bar order, and several signals may share a bar
    assert [s.bar_index for s in sigs] == sorted(s.bar_index for s in sigs)
    assert len([s for s in sigs if s.bar_index == syn.SUCCESS_N_BASE]) >= 3


def test_failure_fixture_yields_no_signal_after_or_at_invalidation():
    scan = _scan(syn.failure_frame())
    sigs = extract_signals(scan)
    inv = [s.bar_index for s in scan.snapshots if s.state == "INVALIDATED"]
    assert len(inv) == 1
    assert all(s.bar_index < inv[0] for s in sigs) and sigs
    assert all(s.snapshot.state != "INVALIDATED" for s in sigs)
    assert scan.snapshots[-1].bar_index == inv[0]  # nothing after: episode over, no new event


def test_repeated_events_fixture_extraction():
    sigs = extract_signals(_scan(syn.repeated_events_frame()))
    assert _bars(sigs, SignalType.EVENT) == list(syn.REPEATED_EVENT_BARS)
    assert _bars(sigs, SignalType.STRONG_EVENT) == [80, 105]          # the 85 event is CORE only
    assert _bars(sigs, SignalType.MULTI_EVENT_CLUSTER) == [85, 105]  # not the anchor event


# --- sample selection / overlap ---------------------------------------------

def _mk(base: Signal, *, ticker="A", bar=0, ep="A:e1", t=SignalType.PULLBACK) -> Signal:
    snap = dataclasses.replace(base.snapshot, ticker=ticker, bar_index=bar, episode_id=ep)
    return Signal(t, snap)


@pytest.fixture(scope="module")
def base_signal():
    return extract_signals(_scan(syn.success_frame()))[0]


def test_first_signal_per_episode_deduplicates(base_signal):
    sigs = [_mk(base_signal, bar=b, ep="A:e1") for b in (5, 6, 7)] + \
           [_mk(base_signal, bar=b, ep="A:e2") for b in (20, 21)] + \
           [_mk(base_signal, bar=6, ep="A:e1", t=SignalType.BREAKOUT), _mk(base_signal, ticker="B", bar=5, ep="A:e1")]
    first = select_samples(sigs, SampleMode.FIRST_SIGNAL_PER_EPISODE)
    keys = {(s.ticker, s.episode_id, s.signal_type, s.bar_index) for s in first}
    assert keys == {("A", "A:e1", SignalType.PULLBACK, 5), ("A", "A:e2", SignalType.PULLBACK, 20),
                    ("A", "A:e1", SignalType.BREAKOUT, 6), ("B", "A:e1", SignalType.PULLBACK, 5)}
    assert select_samples(sigs) == first  # default mode
    # earliest bar wins even when input is unordered
    assert [s.bar_index for s in select_samples(list(reversed(sigs))) if s.ticker == "A"
            and s.signal_type is SignalType.PULLBACK] == [5, 20]


def test_first_signal_per_episode_on_fixture():
    sigs = extract_signals(_scan(syn.success_frame()))
    first = select_samples(sigs, SampleMode.FIRST_SIGNAL_PER_EPISODE)
    assert len(_bars(first, SignalType.PULLBACK)) == 1
    assert _bars(first, SignalType.PULLBACK) == [_bars(sigs, SignalType.PULLBACK)[0]]
    assert len(first) == len({(s.episode_id, s.signal_type) for s in sigs})


def test_all_signals_keeps_repeated_signals(base_signal):
    sigs = [_mk(base_signal, bar=b) for b in (5, 6, 7)]
    assert len(select_samples(sigs, SampleMode.ALL_SIGNALS)) == 3
    real = extract_signals(_scan(syn.success_frame()))
    assert len(select_samples(real, SampleMode.ALL_SIGNALS)) == len(real)
    assert len(select_samples(real, SampleMode.FIRST_SIGNAL_PER_EPISODE)) < len(real)
    assert SampleMode.FIRST_SIGNAL_PER_EPISODE.name == "FIRST_SIGNAL_PER_EPISODE"  # default mode name


def test_overlap_columns_hand_checked(base_signal):
    P, B = SignalType.PULLBACK, SignalType.BREAKOUT
    sigs = [_mk(base_signal, bar=10, t=P), _mk(base_signal, bar=10, t=B), _mk(base_signal, bar=13, t=P),
            _mk(base_signal, bar=60, t=P), _mk(base_signal, ticker="Z", bar=61, t=P)]
    out = annotate_overlap(sigs, max_horizon=40)
    got = [(s.days_since_previous_same_signal, s.days_since_previous_signal, s.is_overlapping) for s in out]
    assert got == [
        (None, None, False),   # first signal
        (None, None, False),   # same bar as the PULLBACK: not "previous"; no earlier BREAKOUT
        (3, 3, True),          # bar 13: previous PULLBACK/any at bar 10
        (47, 47, False),       # 47 > 40 bars: windows do not overlap
        (None, None, False),   # other ticker starts fresh
    ]
    assert [s.signal_type for s in out] == [s.signal_type for s in sigs]  # input order kept
    # max_horizon boundary is inclusive
    assert annotate_overlap(sigs[:3:2], max_horizon=3)[1].is_overlapping is True
    assert annotate_overlap(sigs[:3:2], max_horizon=2)[1].is_overlapping is False
    # input untouched (frozen) and unannotated signals stay None
    assert sigs[0].is_overlapping is None


def test_overlap_on_fixture_and_across_episodes(base_signal):
    real = annotate_overlap(extract_signals(_scan(syn.success_frame())), max_horizon=40)
    pull = [s for s in real if s.signal_type is SignalType.PULLBACK]
    assert pull[0].days_since_previous_same_signal is None and pull[0].is_overlapping is False
    assert [s.days_since_previous_same_signal for s in pull[1:]] == [1] * (len(pull) - 1)
    assert all(s.is_overlapping for s in pull[1:])
    # "per ticker over ALL signals": a previous signal from a different episode counts
    x = annotate_overlap([_mk(base_signal, bar=5, ep="A:e1"), _mk(base_signal, bar=9, ep="A:e2")], 40)
    assert x[1].days_since_previous_same_signal == 4 and x[1].is_overlapping


# --- evaluation ---------------------------------------------------------------

def _arrays(df):
    return [df[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close")]


def test_next_open_entry_uses_next_trading_day():
    df = syn.success_frame()
    # remove a Friday->Monday style gap: entry must be the NEXT BAR, not next calendar day
    res = backtest_ticker(df, "SUCC", CFG, EntryMode.NEXT_OPEN, horizons=(1, 5)).results
    assert res
    o, h, lo, c = _arrays(df)
    for r in res:
        i = r.signal.bar_index
        assert r.forward.entry_price == o[i + 1]
        assert r.entry_mode is EntryMode.NEXT_OPEN
        expect = forward_metrics(o, h, lo, c, i, r.horizon, EntryMode.NEXT_OPEN)
        assert expect == r.forward
    r = next(r for r in res if r.signal.signal_type is SignalType.BREAKOUT_TO_PULLBACK and r.horizon == 1)
    i = r.signal.bar_index  # hand: entry open[i+1] = 1045-bar open, exit close[i+1]
    assert r.forward.forward_return == pytest.approx(c[i + 1] / o[i + 1] - 1)
    # CLOSE mode enters at the signal close instead
    resc = backtest_ticker(df, "SUCC", CFG, EntryMode.CLOSE, horizons=(1,)).results
    assert all(r.forward.entry_price == c[r.signal.bar_index] for r in resc)


def test_next_open_missing_next_bar_is_excluded():
    df = syn.success_frame()
    tb = backtest_ticker(df, "SUCC", CFG, EntryMode.NEXT_OPEN, horizons=(1, 3), mode=SampleMode.ALL_SIGNALS)
    last = len(df) - 1
    assert last in {s.bar_index for s in tb.signals}  # a signal exists on the last bar
    assert last not in {r.signal.bar_index for r in tb.results}  # but it has no next bar to enter on


def test_missing_future_horizon_is_handled():
    df = syn.success_frame()
    n = len(df)
    tb = backtest_ticker(df, "SUCC", CFG, EntryMode.NEXT_OPEN, horizons=(1, 2, 3, 10), mode=SampleMode.ALL_SIGNALS)
    per_signal: dict[int, set[int]] = {}
    for r in tb.results:
        per_signal.setdefault(r.signal.bar_index, set()).add(r.horizon)
        assert r.signal.bar_index + r.horizon < n  # never a partial window
        assert all(np.isfinite(v) for v in (r.forward.forward_return, r.forward.mfe, r.forward.mae))
    # signal 3 bars before the end has h=1,2 only
    assert per_signal[n - 4] == {1, 2, 3}
    assert per_signal[n - 3] == {1, 2}
    assert per_signal[n - 2] == {1}
    assert (n - 1) not in per_signal
    assert 10 not in per_signal[n - 4] and 10 in per_signal[n - 20]


def test_backtest_ticker_default_horizons_and_row_dict():
    df = syn.success_frame()
    tb = backtest_ticker(df, "SUCC", CFG)
    assert {r.horizon for r in tb.results} <= set(CFG.backtest_horizons)
    assert tb.signals and all(s.is_overlapping is not None for s in tb.signals)
    assert _bars(tb.signals, SignalType.PULLBACK).__len__() == 1  # default mode: first signal per episode
    row = tb.results[0].to_dict()
    json.dumps(row, allow_nan=False)
    assert row["entry_mode"] == "NEXT_OPEN" and row["signal_type"] and row["horizon"] and "mfe" in row
    assert row["ticker"] == "SUCC" and "signal_semantics" in row and "hit_down_20" in row


def test_backtest_ticker_forces_null_theme_engine():
    params = inspect.signature(backtest_ticker).parameters
    assert "theme_engine" not in params
    df = syn.success_frame()
    with pytest.raises(TypeError):
        backtest_ticker(df, "SUCC", CFG, theme_engine=scoring.NullThemeEngine())  # type: ignore[call-arg]

    class Fixed(scoring.ThemeEngine):
        def get_score(self, ticker):
            return 100

    themed = scan_engine.scan_ticker(df, "SUCC", CFG, Fixed(), collect_snapshots=True)
    null = scan_engine.scan_ticker(df, "SUCC", CFG, scoring.NullThemeEngine(), collect_snapshots=True)
    assert themed.snapshots[0].theme_score == 100.0 and themed.snapshots[0].final_score != null.snapshots[0].final_score
    prepared = scan_engine.prepare_ticker(df, CFG.breakout_swing_window)
    tb_scan = scan_engine.scan_prepared(prepared, "SUCC", CFG, scoring.NullThemeEngine(), collect_snapshots=True)
    tb = backtest_ticker(df, "SUCC", CFG, horizons=(1,), mode=SampleMode.ALL_SIGNALS)
    by_bar = {s.bar_index: s for s in tb_scan.snapshots}
    assert tb.signals
    for sig in tb.signals:
        s = sig.snapshot
        assert s.theme_score is None
        n = by_bar[s.bar_index]
        assert (s.structure_score, s.trigger_score, s.final_score) == (
            n.structure_score, n.trigger_score, n.final_score)
        assert s.final_score != themed.snapshots[s.bar_index - syn.SUCCESS_N_BASE].final_score


def test_backtest_ticker_is_pure_and_repeatable():
    df = syn.repeated_events_frame()
    before = df.copy()
    a = backtest_ticker(df, "M", CFG, horizons=(1, 5))
    b = backtest_ticker(df, "M", CFG, horizons=(1, 5))
    pd.testing.assert_frame_equal(df, before)
    assert [r.to_dict() for r in a.results] == [r.to_dict() for r in b.results]


def test_backtest_engine_skeleton_kept():
    assert bt.BacktestEngine().run(state_history=[], events=[]).trades == []


# --- causality (look-ahead regression) ---------------------------------------

def _cut_cases():
    yield "succ", syn.success_frame(), (272, 280, 286, 289, 290, 293, 299)
    yield "multi", syn.repeated_events_frame(), (80, 84, 85, 90, 105, 108)
    for seed in range(5):
        yield f"rnd{seed}", syn.random_frame(seed), (120, 180, 240, 300)


def test_truncated_data_produces_same_past_signals():
    compared = 0
    for name, df, cuts in _cut_cases():
        full = extract_signals(_scan(df))
        for cut in cuts:
            part = extract_signals(_scan(df.iloc[: cut + 1].reset_index(drop=True)))
            want = [s for s in full if s.bar_index <= cut]
            assert [(s.signal_type, s.bar_index) for s in part] == [(s.signal_type, s.bar_index) for s in want], (name, cut)
            for a, b in zip(part, want):
                assert a == b, (name, cut, a.signal_type, a.bar_index)   # ALL snapshot fields identical
                compared += 1
    assert compared > 300


def test_no_future_event_affects_signal_snapshot():
    df = syn.repeated_events_frame()
    base = {(s.signal_type, s.bar_index): s for s in extract_signals(_scan(df))}
    # inject a brand-new huge event at bar 108 (a future bar for everything before it)
    df2 = df.copy()
    df2.loc[108, ["open", "high", "low", "close", "volume", "trading_value"]] = [1000.0, 1050.0, 940.0, 1000.0, 2_000_000.0, 300e9]
    mod = {(s.signal_type, s.bar_index): s for s in extract_signals(_scan(df2))}
    early = {k: v for k, v in base.items() if k[1] < 108}
    assert early and early == {k: v for k, v in mod.items() if k[1] < 108}
    assert any(k[1] == 108 and k[0] is SignalType.EVENT for k in mod)  # the injected event is real


def test_event_cluster_snapshot_is_causal():
    df = syn.repeated_events_frame()
    full = {s.bar_index: s for s in _scan(df).snapshots}
    early = _scan(df.iloc[:105].reset_index(drop=True)).snapshots  # bars 0..104: event 3 not yet seen
    assert early[-1].bar_index == 104
    for s in early:
        assert s == full[s.bar_index]
    last = early[-1]
    assert last.event_count_so_far == 2 and last.cluster_trading_value_so_far == pytest.approx(160e9)
    assert last.event_low == 970.0 and last.events_in_last_20d == 1
    assert full[105].event_count_so_far == 3 and full[105].event_low == 960.0
    # a single bar later the third event is known and counted
    assert full[106].cluster_trading_value_so_far == pytest.approx(360e9)


def test_no_future_pivot_affects_signal():
    """A swing high at bar p is a pivot only once `window` later bars exist and is
    usable from bar p+window on. Spike the high at p, then for bars j in [p, p+window-1]
    (pivot p not yet confirmed) the snapshot from the full frame must equal the one
    from a frame cut at j, on ALL fields (trend_break, scores, ...). A confirmation
    look-ahead (or using the unconfirmed pivot) makes the full-frame value differ."""
    w = CFG.breakout_swing_window
    checked = flag_true = 0
    for seed in range(5):
        df = syn.random_frame(seed, n=300)
        for p in range(100, 290, 17):
            df2 = df.copy()
            df2.loc[p, "high"] = float(df.loc[p, "high"]) * 1.6
            full = {s.bar_index: s for s in _scan(df2).snapshots}
            for j in range(p, min(p + w, 300)):
                if j not in full:
                    continue
                cut = _scan(df2.iloc[: j + 1].reset_index(drop=True)).snapshots
                assert cut[-1] == full[j], (seed, p, j)
                checked += 1
            flag_true += any(full[j].trend_break for j in full if j >= p)
    assert checked > 150
    assert flag_true > 0  # the resistance-line branch is exercised, not vacuous


# --- commit-1 review follow-ups (Stage 2 commit 2a) ---------------------------

def test_event_semantics_label_and_row_refinement():
    from jusmo_scanner.backtest.signals import signal_row_semantics
    assert "anchor-bar EVENT == EVENT_BASELINE sample" in SIGNAL_SEMANTICS[SignalType.EVENT]
    sigs = extract_signals(_scan(syn.repeated_events_frame()))
    ev = {s.bar_index: s for s in sigs if s.signal_type is SignalType.EVENT}
    assert "anchor-bar EVENT == EVENT_BASELINE sample" in signal_row_semantics(ev[80])
    assert signal_row_semantics(ev[85]) == "STANDARD"  # joins an active episode: distinct observation
    rows = backtest_ticker(syn.repeated_events_frame(), "M", CFG, horizons=(1,), mode=SampleMode.ALL_SIGNALS).results
    assert {r.to_dict()["signal_semantics"] for r in rows if r.signal.signal_type is SignalType.EVENT} == {
        signal_row_semantics(ev[80]), "STANDARD"}


def test_identical_sample_groups_flags_first_mode_hazard():
    from jusmo_scanner.backtest.signals import identical_sample_groups
    for df in (syn.success_frame(), syn.bottom_repeated_events_frame()):
        first = backtest_ticker(df, "X", CFG, horizons=(1,), mode=SampleMode.FIRST_SIGNAL_PER_EPISODE).signals
        groups = identical_sample_groups(first)
        assert any({"ACCUMULATION", "EVENT", "EVENT_TO_ACCUMULATION"} <= set(g) for g in groups)
        # dict rows give the same answer as Signal objects
        assert identical_sample_groups([s.snapshot.to_dict() | {"signal_type": s.signal_type.value} for s in first]) == groups
    allm = backtest_ticker(syn.repeated_events_frame(), "X", CFG, horizons=(1,), mode=SampleMode.ALL_SIGNALS).signals
    assert all("EVENT" not in g for g in identical_sample_groups(allm))
    assert identical_sample_groups([]) == []


def test_sample_basis_overlap_columns_differ_from_all_signals_basis(base_signal):
    from jusmo_scanner.backtest.engine import annotate_sample_overlap
    sigs = [_mk(base_signal, bar=b, ep="A:e1") for b in (5, 6, 7)] + \
           [_mk(base_signal, bar=b, ep="A:e2") for b in (20, 21)]
    ann = annotate_overlap(sigs, 14)
    first = annotate_sample_overlap(select_samples(ann, SampleMode.FIRST_SIGNAL_PER_EPISODE), 14)
    assert [s.bar_index for s in first] == [5, 20]
    a20 = first[1]
    # all-signals basis: previous same-type signal is the NON-sampled bar 7
    assert (a20.days_since_previous_same_signal, a20.is_overlapping) == (13, True)
    # sample basis: previous sample is bar 5
    assert (a20.days_since_previous_same_sample, a20.days_since_previous_sample, a20.is_overlapping_sample) == (15, 15, False)
    assert (first[0].days_since_previous_same_sample, first[0].is_overlapping_sample) == (None, False)
    row = backtest_ticker(syn.success_frame(), "S", CFG, horizons=(1,)).results[0].to_dict()
    for k in ("days_since_previous_same_sample", "days_since_previous_sample", "is_overlapping_sample"):
        assert k in row


def test_sample_overlap_on_backtest_ticker_uses_selected_rows():
    tb = backtest_ticker(syn.repeated_events_frame(), "M", CFG, horizons=(3,), mode=SampleMode.ALL_SIGNALS)
    for s in tb.signals:
        same = [p for p in tb.signals if p.signal_type is s.signal_type and p.bar_index < s.bar_index]
        want = s.bar_index - max(p.bar_index for p in same) if same else None
        assert s.days_since_previous_same_sample == want
        assert s.is_overlapping_sample == (want is not None and want <= 3)


def test_invalidating_bar_with_event_and_trend_break_yields_no_signals():
    # engine level: the bearish bar that breaches the event low is ALSO an event bar
    df = syn.failure_frame()
    df.loc[83, "trading_value"] = 60e9
    scan = _scan(df)
    inv = [s for s in scan.snapshots if s.state == "INVALIDATED"]
    assert len(inv) == 1 and inv[0].bar_index == 83 and inv[0].event_added_this_bar
    assert inv[0].event_count_so_far == 2 and inv[0].previous_state != "INVALIDATED"
    sigs = extract_signals(scan)
    assert all(s.bar_index < 83 for s in sigs)
    # snapshot level: every feature flag lit on an INVALIDATED bar still yields nothing
    lit = dataclasses.replace(
        inv[0], trend_break=True, cross_ma120=True, cross_ma240=True, previous_high_break=True,
        strong_event_this_bar=True, event_added_this_bar=True, event_count_so_far=3,
        previous_state="ACCUMULATION")
    from jusmo_scanner.backtest.signals import signal_types_at
    assert signal_types_at(lit) == []
    assert signal_types_at(dataclasses.replace(lit, state="ACCUMULATION")) != []  # the guard is what silenced it


@pytest.mark.parametrize("bad", [(), [], (0,), (-1, 5), (1.5,), ("5",), (True,), 5, "1,3"])
def test_backtest_ticker_validates_explicit_horizons_before_scanning(bad, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("scanned before validating horizons")
    monkeypatch.setattr(scan_engine, "prepare_ticker", boom)
    with pytest.raises(ValueError, match="horizons"):
        backtest_ticker(syn.success_frame(), "S", CFG, horizons=bad)


def test_backtest_ticker_explicit_horizons_sorted_unique():
    tb = backtest_ticker(syn.success_frame(), "S", CFG, horizons=(5, 1, 5))
    assert {r.horizon for r in tb.results} == {1, 5}


def test_multi_event_cluster_fires_on_each_joining_event_first_keeps_one():
    df = syn.repeated_events_frame()
    allm = backtest_ticker(df, "M", CFG, horizons=(1,), mode=SampleMode.ALL_SIGNALS).signals
    first = backtest_ticker(df, "M", CFG, horizons=(1,), mode=SampleMode.FIRST_SIGNAL_PER_EPISODE).signals
    assert _bars(allm, SignalType.MULTI_EVENT_CLUSTER) == [85, 105]   # every joining event, count >= 2
    assert _bars(first, SignalType.MULTI_EVENT_CLUSTER) == [85]       # one per episode
    assert {s.snapshot.event_count_so_far for s in allm if s.signal_type is SignalType.MULTI_EVENT_CLUSTER} == {2, 3}


# --- ACCUMULATION_CONFIRMED (research feature signal) ---------------------------------------------------------------

def _conf(df, cfg=CFG):
    return [s for s in extract_signals(_scan(df, cfg)) if s.signal_type is SignalType.ACCUMULATION_CONFIRMED]


def test_accumulation_confirmed_fires_once_on_first_confirmed_bar():
    for df, bar in ((syn.success_frame(), 273), (syn.bottom_repeated_events_frame(), 128)):
        scan = _scan(df)
        flags = [s for s in scan.snapshots if s.accumulation_confirmed]
        assert len(flags) > 5                                        # the flag stays true for many bars ...
        sigs = _conf(df)
        assert [s.bar_index for s in sigs] == [bar] == [flags[0].bar_index]   # ... but the signal fires once
        snap = sigs[0].snapshot
        assert snap.days_since_event_trading >= CFG.backtest_accumulation_min_days
        assert snap.vcr_anchor <= CFG.backtest_accumulation_vcr_max and snap.accumulation_confirmed
        assert sigs[0].category is SignalCategory.FEATURE
        assert "research feature" in signal_semantics(SignalType.ACCUMULATION_CONFIRMED)


def test_accumulation_confirmed_never_fires_when_never_confirmed():
    scan = _scan(syn.failure_frame())
    assert not any(s.accumulation_confirmed for s in scan.snapshots)
    assert _conf(syn.failure_frame()) == []
    # a stricter confirmation rule that the success fixture cannot meet -> no signal either
    strict = dataclasses.replace(CFG, backtest_accumulation_min_days=500)
    assert _conf(syn.success_frame(), strict) == []


def test_accumulation_confirmed_not_refired_when_flag_flips_back_and_forth():
    df = syn.success_frame()
    scan = _scan(df)
    snaps = list(scan.snapshots)
    ep = snaps[0].episode_id
    flipped = [dataclasses.replace(s, accumulation_confirmed=(i % 3 != 0)) for i, s in enumerate(snaps)]
    assert sum(1 for a, b in zip(flipped, flipped[1:]) if not a.accumulation_confirmed and b.accumulation_confirmed) > 3
    fake = dataclasses.replace(scan, snapshots=flipped)
    got = [s for s in extract_signals(fake) if s.signal_type is SignalType.ACCUMULATION_CONFIRMED]
    assert len(got) == 1 and got[0].bar_index == next(s.bar_index for s in flipped if s.accumulation_confirmed)
    assert all(s.episode_id == ep for s in snaps)
    # a new episode gets its own signal: two episodes -> two signals
    other = [dataclasses.replace(s, episode_id="X:other", bar_index=s.bar_index + 1000) for s in flipped]
    two = extract_signals(dataclasses.replace(scan, snapshots=flipped + other))
    assert len([s for s in two if s.signal_type is SignalType.ACCUMULATION_CONFIRMED]) == 2
    # an INVALIDATED bar never carries it (and does not consume the once-per-episode slot)
    inv = [dataclasses.replace(s, state="INVALIDATED", accumulation_confirmed=True) if i == 0 else s
           for i, s in enumerate(flipped)]
    assert [s.bar_index for s in extract_signals(dataclasses.replace(scan, snapshots=inv))
            if s.signal_type is SignalType.ACCUMULATION_CONFIRMED] == [flipped[1].bar_index]


def test_accumulation_confirmed_first_and_all_modes_give_the_same_sample_set():
    for df in (syn.success_frame(), syn.repeated_events_frame(), syn.random_frame(2, 320), syn.random_frame(5, 320)):
        f = backtest_ticker(df, "T", CFG, horizons=(1,), mode=SampleMode.FIRST_SIGNAL_PER_EPISODE).signals
        a = backtest_ticker(df, "T", CFG, horizons=(1,), mode=SampleMode.ALL_SIGNALS).signals
        keys = lambda sigs: [(s.episode_id, s.bar_index) for s in sigs if s.signal_type is SignalType.ACCUMULATION_CONFIRMED]  # noqa: E731
        assert keys(f) == keys(a)
        assert len(keys(a)) == len({e for e, _ in keys(a)})           # at most one per episode
    assert keys(backtest_ticker(syn.success_frame(), "T", CFG, horizons=(1,)).signals)


def test_accumulation_confirmed_is_prefix_invariant():
    """Causality: extraction on a truncated scan equals the prefix of the full extraction."""
    checked = 0
    for name, df, cuts in _cut_cases():
        full = [(s.bar_index, s.episode_id) for s in extract_signals(_scan(df))
                if s.signal_type is SignalType.ACCUMULATION_CONFIRMED]
        for cut in cuts:
            part = [(s.bar_index, s.episode_id) for s in extract_signals(_scan(df.iloc[: cut + 1].reset_index(drop=True)))
                    if s.signal_type is SignalType.ACCUMULATION_CONFIRMED]
            assert part == [x for x in full if x[0] <= cut], (name, cut)
            checked += 1
    assert checked > 20


def test_accumulation_confirmed_is_separate_from_event_day_entry_in_summaries():
    from jusmo_scanner.backtest.experiments import ExperimentOptions, run_experiment
    from tests.core.test_backtest_experiments import DictProvider
    res = run_experiment(DictProvider({"SUCC": syn.success_frame(), "MULTI": syn.bottom_repeated_events_frame(),
                                       "FAIL": syn.failure_frame()}), CFG, ExperimentOptions(horizons=(5,)))
    rows = {(r["signal_type"], r["sample_mode"]): r for r in res.summary_rows
            if r["analysis_name"] == "by_signal_type" and r["variant"] == "baseline"}
    ev = rows[("EVENT", "FIRST_SIGNAL_PER_EPISODE")]
    conf = rows[("ACCUMULATION_CONFIRMED", "FIRST_SIGNAL_PER_EPISODE")]
    assert conf["sample_count"] == 2 and ev["sample_count"] == 3          # the failure episode never confirms
    assert conf["mean_return"] != ev["mean_return"]                       # different entry bars -> different results
    assert rows[("ACCUMULATION_CONFIRMED", "ALL_SIGNALS")]["sample_count"] == 2   # FIRST == ALL
    assert "IDENTICAL_SAMPLES" not in (conf["note"] or "")
