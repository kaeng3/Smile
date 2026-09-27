"""Signal window semantics: signal_start / signal_end filter SIGNALS, never the raw data."""
from __future__ import annotations

import dataclasses
import sqlite3
from contextlib import closing

import pytest

from jusmo_scanner.backtest import experiments as ex
from jusmo_scanner.backtest.engine import (
    SampleMode, annotate_sample_overlap, evaluate_signals, scan_signals, select_samples)
from jusmo_scanner.backtest.experiments import ExperimentOptions, run_experiment
from jusmo_scanner.backtest.metrics import EntryMode
from jusmo_scanner.backtest.signals import SignalType
from jusmo_scanner.config import load_config, override_config
from jusmo_scanner.scanner import engine as scan_engine
from tests import synthetic as syn
from tests.core.test_backtest_experiments import DictProvider

CFG = load_config("config/scanner.yaml")
FIRST, ALL = SampleMode.FIRST_SIGNAL_PER_EPISODE, SampleMode.ALL_SIGNALS
EV = syn.SUCCESS_N_BASE                      # event bar of success_frame (270), warm-up = bars 0..269


def outcomes(df, options, cfg=CFG, hz=(1, 5), ticker="T"):
    ((_, outs),) = list(ex.iter_ticker_variants(df, ticker, [("baseline", cfg)], options, hz))
    return outs


def types_of(outs):
    return {o.signal.signal_type for o in outs}


def date_of(df, bar):
    return df.loc[bar, "date"]


# --- the reported bug ------------------------------------------------------------------------

def test_signal_start_does_not_remove_feature_warmup(monkeypatch):
    df = syn.success_frame()
    seen = []
    real = scan_engine.prepare_ticker

    def spy(frame, window):
        seen.append(len(frame))
        return real(frame, window)

    monkeypatch.setattr(ex.scan_engine, "prepare_ticker", spy)
    wanted = {"MA120_CROSS", "MA240_CROSS", "IGNITION"}
    opts = dict(signal_types=wanted, sample_modes=(ALL,))
    full = outcomes(df, ExperimentOptions(**opts))
    windowed = outcomes(df, ExperimentOptions(signal_start=date_of(df, 200), **opts))   # start deep inside the warm-up
    assert seen == [len(df), len(df)]                    # the scanner always gets the FULL frame
    assert {t.value for t in types_of(full)} == wanted   # non-vacuous: the signals exist with full history
    assert {t.value for t in types_of(windowed)} == wanted
    assert len(windowed) == len(full) >= 5


def test_old_truncation_behavior_is_gone():
    assert not hasattr(ex, "_filter_dates")
    df = syn.success_frame()
    res = run_experiment(DictProvider({"SUCC": df}), CFG, ExperimentOptions(
        horizons=(1,), signal_start=date_of(df, 200), signal_end=date_of(df, 289)))
    m = res.metadata
    assert m["source_data_start"] == str(df["date"].iloc[0].date()) and m["source_data_end"] == str(df["date"].iloc[-1].date())
    assert m["signal_start"] == str(date_of(df, 200).date()) and m["signal_end"] == str(date_of(df, 289).date())


def test_reported_bug_shape_ma_cross_and_ignition_survive_start_filter():
    df = syn.success_frame()
    start = date_of(df, EV - 5)                        # 5 bars before the event, long after data start
    outs = outcomes(df, ExperimentOptions(signal_start=start, sample_modes=(FIRST,)))
    tt = {t.value for t in types_of(outs)}
    assert {"MA120_CROSS", "MA240_CROSS", "IGNITION"} <= tt
    ev = next(o.signal for o in outs if o.signal.signal_type is SignalType.EVENT)
    assert ev.snapshot.ma240 is not None and ev.snapshot.ma120 is not None


def test_ma240_same_with_and_without_signal_start():
    df = syn.success_frame()
    opts = dict(signal_types={"EVENT"}, sample_modes=(ALL,))
    full = outcomes(df, ExperimentOptions(**opts))
    cut = outcomes(df, ExperimentOptions(signal_start=date_of(df, EV), **opts))
    (a,), (b,) = [o.signal for o in full], [o.signal for o in cut]
    assert a.bar_index == b.bar_index == EV
    assert a.snapshot.ma240 is not None and a.snapshot.ma240 == b.snapshot.ma240
    assert a.snapshot == b.snapshot                     # every snapshot field, not only MA240


# --- window policy ----------------------------------------------------------------------------------

def test_signal_before_start_is_excluded():
    df = syn.success_frame()
    start = date_of(df, 286)
    full = outcomes(df, ExperimentOptions(sample_modes=(ALL,)))
    win = outcomes(df, ExperimentOptions(signal_start=start, sample_modes=(ALL,)))
    assert any(o.signal.signal_date < start.date() for o in full)          # non-vacuous
    assert win and all(o.signal.signal_date >= start.date() for o in win)
    assert len(win) == sum(o.signal.signal_date >= start.date() for o in full)


def test_active_episode_before_start_can_emit_signal_after_start():
    df = syn.success_frame()
    start = date_of(df, 280)                            # episode began at bar 270 and is still active
    first = outcomes(df, ExperimentOptions(signal_start=start, sample_modes=(FIRST,)))
    win = [o for o in first if o.is_first]
    assert win, "an episode started before signal_start must still emit later signals"
    assert all(o.signal.snapshot.event_date < start.date() for o in win)   # anchored before the window
    assert SignalType.BREAKOUT in types_of(win) and SignalType.IGNITION in types_of(win)
    # policy: dedup uses the FULL history - types that first fired before the start do not re-qualify
    assert SignalType.ACCUMULATION not in types_of(win) and SignalType.EVENT not in types_of(win)
    assert SignalType.DORMANT not in types_of(win)                            # first DORMANT bar is before the start
    all_mode = outcomes(df, ExperimentOptions(signal_start=start, sample_modes=(ALL,)))
    assert SignalType.DORMANT in types_of(all_mode)                         # ALL-mode repeats after the start are emitted
    # ...and none of the FIRST rows is a "first" merely because the earlier ones were cut
    full_first = {(o.signal.signal_type, o.signal.bar_index) for o in outcomes(
        df, ExperimentOptions(sample_modes=(FIRST,))) if o.is_first}
    assert {(o.signal.signal_type, o.signal.bar_index) for o in win} <= full_first


def test_end_limits_signal_dates_not_feature_history():
    df = syn.success_frame()
    end = date_of(df, 288)
    full = outcomes(df, ExperimentOptions(sample_modes=(ALL,)))
    win = outcomes(df, ExperimentOptions(signal_end=end, sample_modes=(ALL,)))
    assert all(o.signal.signal_date <= end.date() for o in win) and len(win) < len(full)
    want = [o.signal for o in full if o.signal.signal_date <= end.date()]
    assert [o.signal for o in win] == want              # identical snapshots/overlap/sample columns
    res = run_experiment(DictProvider({"SUCC": df}), CFG, ExperimentOptions(horizons=(1,), signal_end=end))
    assert res.metadata["source_data_end"] == str(df["date"].iloc[-1].date())   # raw data not cut
    assert res.metadata["signal_end"] == str(end.date()) and res.metadata["signal_start"] is None


def test_forward_horizon_can_extend_beyond_signal_end():
    df = syn.success_frame()
    end_bar = 292
    opts = dict(sample_modes=(ALL,), signal_types={"PULLBACK"})
    win = outcomes(df, ExperimentOptions(signal_end=date_of(df, end_bar), **opts), hz=(1, 5))
    full = outcomes(df, ExperimentOptions(**opts), hz=(1, 5))
    late = [o for o in win if o.signal.bar_index + 5 > end_bar]
    assert late, "need signals whose 5-bar horizon ends after signal_end"
    by = {(o.signal.bar_index): o for o in full}
    for o in late:
        h5 = [r for r in o.results if r.horizon == 5]
        assert len(h5) == 1                                             # evaluated with post-end bars
        assert h5[0].forward == [r for r in by[o.signal.bar_index].results if r.horizon == 5][0].forward


def test_signals_up_to_end_do_not_depend_on_post_end_bars():
    """The scanner is causal: removing all bars after `end` cannot change a signal <= end."""
    for name, df in (("succ", syn.success_frame()), ("multi", syn.repeated_events_frame()),
                     ("rnd", syn.random_frame(4, 320))):
        for cut in (len(df) // 2, len(df) - 20):
            end = date_of(df, cut)
            opts = dict(sample_modes=(ALL,), signal_end=end)
            with_post = outcomes(df, ExperimentOptions(**opts))
            without = outcomes(df.iloc[:cut + 1].reset_index(drop=True), ExperimentOptions(**opts))
            assert [o.signal for o in with_post] == [o.signal for o in without], (name, cut)


# --- equivalence with "full history, then filter by signal date" ---------------------------------------

def _reference(df, cfg, start, end, entry_mode, hz, ticker="T"):
    """Independent pipeline: full scan -> dedup on full history -> filter by signal_date -> evaluate."""
    prepared = scan_engine.prepare_ticker(df, cfg.breakout_swing_window)
    max_h = max(hz)
    sigs = scan_signals(prepared, ticker, cfg, max_h)
    first = annotate_sample_overlap(select_samples(sigs, FIRST), max_h)

    def keep(s):
        return (start is None or s.signal_date >= start.date()) and (end is None or s.signal_date <= end.date())

    a_first = [s for s in first if keep(s)]
    a_all = [s for s in sigs if keep(s)]
    return (a_first, evaluate_signals(prepared, a_first, entry_mode, hz),
            a_all, evaluate_signals(prepared, a_all, entry_mode, hz))


def _strip_sample_cols(s):
    return dataclasses.replace(s, days_since_previous_same_sample=None, days_since_previous_sample=None,
                               is_overlapping_sample=None)


def _res_key(r):
    return (r.signal.signal_type, r.signal.bar_index, r.horizon, r.entry_mode, r.forward)


def test_start_end_results_match_full_scan_filtered_by_signal_date():
    frames = [("succ", syn.success_frame()), ("multi", syn.repeated_events_frame()),
              ("rnd1", syn.random_frame(1, 320)), ("rnd2", syn.random_frame(2, 320))]
    variants = [("baseline", CFG), ("cost5", override_config(CFG, cost_hold_tolerance_pct=0.05))]
    windows = [(0.55, 0.9), (0.4, None), (None, 0.7)]
    compared = {"signals": 0, "results": 0, "mismatch": 0}
    for name, df in frames:
        n = len(df)
        for lo, hi in windows:
            start = date_of(df, int(n * lo)) if lo is not None else None
            end = date_of(df, int(n * hi)) if hi is not None else None
            for entry in (EntryMode.NEXT_OPEN, EntryMode.CLOSE):
                hz = (1, 5)
                opts = ExperimentOptions(signal_start=start, signal_end=end, entry_mode=entry, horizons=hz)
                got = dict(ex.iter_ticker_variants(df, "T", variants, opts, hz))
                for vid, cfg in variants:
                    a_first, r_first, a_all, r_all = _reference(df, cfg, start, end, entry, hz)
                    outs = got[vid]
                    b_first = [o for o in outs if o.is_first]
                    # FIRST samples: identical Signal objects (ALL snapshot, overlap and sample columns)
                    assert [o.signal for o in b_first] == a_first, (name, vid, lo, hi, entry)
                    # ALL samples: identical snapshots + all-signals overlap columns, same order
                    assert [_strip_sample_cols(o.signal) for o in outs] == [_strip_sample_cols(s) for s in a_all]
                    # results: identical rows (forward metrics included)
                    b_first_res = [r for o in b_first for r in o.results]
                    b_all_res = [r for o in outs for r in o.results]
                    assert sorted(map(repr, map(_res_key, b_first_res))) == sorted(map(repr, map(_res_key, r_first)))
                    assert sorted(map(repr, map(_res_key, b_all_res))) == sorted(map(repr, map(_res_key, r_all)))
                    compared["signals"] += len(outs)
                    compared["results"] += len(b_all_res)
    assert compared["signals"] > 300 and compared["results"] > 300 and compared["mismatch"] == 0


def test_start_end_db_rows_match_full_run_filtered_by_signal_date(tmp_path):
    """DB level: rows stored by ExperimentOptions(signal_start, signal_end) == the full-history
    run's rows whose signal_date is inside the window (all columns, baseline + swept variants),
    and the result rows match too."""
    opts = dict(horizons=(1, 5), sweeps=True, sweep_parameters=("cost_tolerance",), store_variant_rows=True,
                sample_modes=(FIRST, ALL))
    checked = 0
    for name, df in (("SUCC", syn.success_frame()), ("MULTI", syn.repeated_events_frame()),
                     ("R3", syn.random_frame(3, 320))):
        n = len(df)
        start, end = date_of(df, int(n * 0.5)), date_of(df, int(n * 0.9))
        full_db, win_db = tmp_path / f"{name}_f.db", tmp_path / f"{name}_w.db"
        run_experiment(DictProvider({name: df}), CFG, ExperimentOptions(db_path=full_db, **opts))
        run_experiment(DictProvider({name: df}), CFG, ExperimentOptions(
            db_path=win_db, signal_start=start, signal_end=end, **opts))
        for table, order in (("backtest_signals", "variant, signal_uid"),
                             ("backtest_results", "variant, signal_uid, entry_mode, horizon")):
            def rows(db, where):
                with closing(sqlite3.connect(db)) as c:
                    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})") if r[1] not in ("id", "experiment_id")]
                    return cols, c.execute(f"SELECT {', '.join(cols)} FROM {table} {where} ORDER BY {order}").fetchall()
            if table == "backtest_signals":
                cols, want = rows(full_db, f"WHERE signal_date >= '{start.date()}' AND signal_date <= '{end.date()}'")
            else:
                cols, want = rows(full_db, "WHERE signal_uid IN (SELECT signal_uid FROM backtest_signals WHERE "
                                           f"signal_date >= '{start.date()}' AND signal_date <= '{end.date()}')")
            _, got = rows(win_db, "")
            assert got == want, (name, table)
            checked += len(got)
    assert checked > 200
    with closing(sqlite3.connect(win_db)) as c:
        assert c.execute("SELECT signal_start, signal_end, source_data_start, source_data_end "
                         "FROM backtest_experiments").fetchone() == (
            str(start.date()), str(end.date()), str(df["date"].iloc[0].date()), str(df["date"].iloc[-1].date()))
