"""Episode-history semantics: a long-lived episode must survive signal_start, and the default
historical fetch must be the provider's FULL history (no fixed lookback)."""
from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
from contextlib import closing
from datetime import date, timedelta

import pandas as pd
import pytest

from jusmo_scanner.backtest import cli_commands as cc
from jusmo_scanner.backtest import experiments as ex
from jusmo_scanner.backtest.engine import SampleMode
from jusmo_scanner.backtest.experiments import ExperimentOptions, run_experiment
from jusmo_scanner.backtest.signals import SignalType
from jusmo_scanner.config import load_config
from tests.pykrx_fake import FakePykrx

CFG = load_config("config/scanner.yaml")
FIRST, ALL = SampleMode.FIRST_SIGNAL_PER_EPISODE, SampleMode.ALL_SIGNALS
N, EV1, EV2, IGN, BRK, PBK = 1500, 300, 1150, 1236, 1238, 1239
SIG_START_BAR, SIG_END_BAR = 1235, 1300


def _bar(close, *, open_=None, high=None, low=None, volume=100_000.0, tv=1e9):
    o = close if open_ is None else open_
    return dict(open=o, high=max(o, close) + 5.0 if high is None else high,
                low=min(o, close) - 5.0 if low is None else low, close=close, volume=volume, trading_value=tv)


def long_episode_frame() -> pd.DataFrame:
    """Anchor event at bar 300 (2019-02-25) that is still alive ~3.5 years later, a second event at
    bar 1150, ignition/breakout/pullback inside the signal window (bars 1235..1300)."""
    rows = [_bar(1000.0 + 4.0 * math.sin(i * 0.31), volume=60_000.0 * (1 + 0.05 * math.sin(i * 0.17)))
            for i in range(N)]
    rows[EV1] = _bar(1000.0, high=1020.0, low=980.0, volume=500_000.0, tv=100e9)
    rows[EV1 - 100]["high"] = 1100.0  # causal bottom anchor, no change to recent indicators
    rows[EV2] = _bar(1000.0, high=1025.0, low=975.0, volume=600_000.0, tv=120e9)
    rows[BRK] = _bar(1120.0, open_=1055.0, high=1140.0, low=1050.0, volume=400_000.0)
    rows[PBK] = _bar(1060.0, open_=1110.0, high=1115.0, low=1055.0, volume=60_000.0)
    for k in range(1, 40):
        rows[PBK + k] = _bar(1065.0 + 2.0 * k, volume=70_000.0)
    df = pd.DataFrame(rows)
    df.insert(0, "date", pd.bdate_range(start="2018-01-01", periods=N))
    df.insert(1, "ticker", "LONG")
    df["market_cap"] = 100_000_000_000.0
    df["free_float_shares"] = 10_000_000.0
    return df


DF = long_episode_frame()
DATES = list(DF["date"])
SIG_START, SIG_END = DATES[SIG_START_BAR].date(), DATES[SIG_END_BAR].date()
ANCHOR_ID = f"LONG:{DATES[EV1].date()}"


def outcomes(df, sample_modes=(ALL,)):
    opts = ExperimentOptions(signal_start=SIG_START, signal_end=SIG_END, sample_modes=sample_modes)
    ((_, outs),) = list(ex.iter_ticker_variants(df, "LONG", [("baseline", CFG)], opts, (1, 5, 20)))
    return outs


def _args(*extra):
    p = argparse.ArgumentParser()
    cc.add_parsers(p.add_subparsers(dest="command"))
    return p.parse_args(["backtest", "--provider", "pykrx", "--start", str(SIG_START), "--end", str(SIG_END),
                         "--horizons", "1,5,20", *extra])


def _provider(monkeypatch, *extra):
    fake = FakePykrx({"LONG": DF}).install(monkeypatch)
    args = _args(*extra)
    fs, fe, reason = cc.resolve_fetch_window(SIG_START, SIG_END, 20, cc.parse_date(args.fetch_start, "--fetch-start"),
                                             cc.parse_date(args.fetch_end, "--fetch-end"))
    return fake, cc._build_provider(args, fs, fe), (fs, fe, reason)


def test_long_lived_episode_survives_signal_start():
    assert (SIG_START - DATES[EV1].date()).days > 600            # anchored > 600 calendar days earlier
    outs = outcomes(DF)
    assert outs
    ids = {o.signal.episode_id for o in outs}
    assert ids <= {ANCHOR_ID, f"LONG:{DATES[EV2].date()}"} and ANCHOR_ID in ids
    anchored = [o.signal for o in outs if o.signal.episode_id == ANCHOR_ID]
    assert anchored and all(s.snapshot.event_date == DATES[EV1].date() for s in anchored)
    assert all(s.snapshot.days_since_event_trading > 900 for s in anchored)
    types = {s.signal_type for s in anchored}
    assert SignalType.PULLBACK in types or SignalType.IGNITION in types
    # ACCUMULATION_CONFIRMED fired long before the window and must NOT be re-emitted inside it
    assert SignalType.ACCUMULATION_CONFIRMED not in {o.signal.signal_type for o in outs}


def test_default_historical_provider_does_not_drop_preexisting_episode(monkeypatch, tmp_path):
    fake, provider, (fs, fe, reason) = _provider(monkeypatch)
    assert reason is None and fs == cc.EARLIEST_FETCH_DATE       # full history: no lookback at all
    assert fs < DATES[0].date() and fe >= SIG_END
    frame = provider.get_ohlcv("LONG")
    assert frame["date"].iloc[0] == DATES[0] and frame["date"].iloc[-1].date() >= SIG_END   # nothing dropped at the start
    # Naver ignores the end date (rows are counted back from today), so the provider asks up to TODAY and
    # trims to the fetch end itself; this is what makes the row cap detectable
    assert fake.ohlcv_calls == [("19900101", date.today().strftime("%Y%m%d"), "LONG", True)]
    assert frame["date"].iloc[-1].date() <= fe
    db = tmp_path / "h.db"
    res = run_experiment(provider, CFG, ExperimentOptions(
        signal_start=SIG_START, signal_end=SIG_END, horizons=(1, 5, 20), db_path=db, tickers=("LONG",)))
    with closing(sqlite3.connect(db)) as c:
        eps = {r[0] for r in c.execute("SELECT DISTINCT episode_id FROM backtest_signals")}
        row = c.execute("SELECT history_truncated, history_truncation_reason, source_data_start "
                        "FROM backtest_experiments").fetchone()
    assert ANCHOR_ID in eps and eps <= {ANCHOR_ID, f"LONG:{DATES[EV2].date()}"}
    assert row == (0, None, str(DATES[0].date())) and res.metadata["history_truncated"] is False
    assert not any("history truncated" in w for w in res.warnings)


def test_default_provider_history_equals_full_history_scan():
    """A = full-history scan + signal-window filter; B = production-default provider history +
    the same signal window: episode_id, state, event_count, cost, cluster fields, PULLBACK,
    ACCUMULATION_CONFIRMED, every feature signal and ALL snapshot columns are equal."""
    import sys
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    try:
        _, provider, _ = _provider(mp)
        B_frame = provider.get_ohlcv("LONG")
    finally:
        mp.undo()
    A, B = outcomes(DF, (FIRST, ALL)), outcomes(B_frame, (FIRST, ALL))
    assert A and len(A) == len(B)
    fields = ("episode_id", "state", "event_count_so_far", "estimated_cost", "cluster_trading_value_so_far",
              "event_low", "vcr_anchor", "accumulation_confirmed", "days_since_event_trading",
              "pullback_depth", "breakout_date")
    for a, b in zip(A, B):
        assert (a.signal.signal_type, a.signal.bar_index, a.is_first) == (b.signal.signal_type, b.signal.bar_index, b.is_first)
        for f in fields:
            assert getattr(a.signal.snapshot, f) == getattr(b.signal.snapshot, f), (f, a.signal.signal_type)
        assert a.signal == b.signal                                 # ALL snapshot + overlap + sample columns
        assert a.results == b.results
    kinds = {o.signal.signal_type for o in A}
    assert SignalType.PULLBACK in kinds and any(t.category.value == "FEATURE" for t in kinds)


def test_explicit_fetch_start_warns_history_truncation(monkeypatch, tmp_path, caplog):
    cut = SIG_START - timedelta(days=600)                          # the old "fixed warm-up" fetch start
    fake = FakePykrx({"LONG": DF}).install(monkeypatch)
    out = tmp_path / "out"
    args = _args("--fetch-start", str(cut), "--output", str(out))
    with caplog.at_level(logging.WARNING):
        assert cc.dispatch(args) == 0
    assert any("history truncated" in r.getMessage() for r in caplog.records)
    assert fake.ohlcv_calls[0][0] == cut.strftime("%Y%m%d")
    with closing(sqlite3.connect(out / "backtest.db")) as c:
        trunc, reason, warns = c.execute(
            "SELECT history_truncated, history_truncation_reason, warnings_json FROM backtest_experiments").fetchone()
        eps = {r[0] for r in c.execute("SELECT DISTINCT episode_id FROM backtest_signals")}
    assert trunc == 1 and reason.startswith(f"explicit --fetch-start={cut}")
    warns = json.loads(warns)
    assert any(w.startswith("history truncated:") and str(cut) in w for w in warns)
    assert warns[-1] == ex.SURVIVORSHIP_WARNING                     # survivorship sentence stays last, verbatim
    assert ANCHOR_ID not in eps                                     # the truncated history lost the long episode
    md = next(out.glob("summary_*.md")).read_text(encoding="utf-8")
    assert "history truncated" in md and "- history_truncated: 1" in md
    meta = json.loads(next(out.glob("experiment_*.json")).read_text(encoding="utf-8"))
    assert meta["history_truncated"] == 1 and meta["history_truncation_reason"].startswith("explicit --fetch-start=")


def test_explicit_fetch_start_breaks_equality_which_is_why_the_warning_exists(monkeypatch):
    cut = SIG_START - timedelta(days=600)
    fake = FakePykrx({"LONG": DF}).install(monkeypatch)
    _, _, reason = cc.resolve_fetch_window(SIG_START, SIG_END, 20, cut, None)
    assert reason == f"explicit --fetch-start={cut}"
    args = _args("--fetch-start", str(cut))
    fs, fe, _ = cc.resolve_fetch_window(SIG_START, SIG_END, 20, cut, None)
    C = cc._build_provider(args, fs, fe).get_ohlcv("LONG")
    assert len(C) < N and C["date"].iloc[0].date() >= cut
    A, T = outcomes(DF), outcomes(C)
    assert [o.signal for o in A] != [o.signal for o in T]          # DIVERGES: not equal to full history
    assert {o.signal.episode_id for o in A} != {o.signal.episode_id for o in T}
    a_ids, t_ids = {o.signal.episode_id for o in A}, {o.signal.episode_id for o in T}
    assert ANCHOR_ID in a_ids and ANCHOR_ID not in t_ids           # the episode is re-anchored on the truncated frame
    assert fake.ohlcv_calls


def test_resolve_fetch_window_semantics():
    from datetime import date
    today = date(2026, 9, 20)
    s, e, r = cc.resolve_fetch_window(date(2022, 1, 1), date(2022, 12, 31), 40, today=today)
    assert (s, e, r) == (date(1990, 1, 1), date(2022, 12, 31) + timedelta(days=74), None)   # ceil(40*1.6)+10
    s, e, r = cc.resolve_fetch_window(None, None, 5, today=today)
    assert (s, e, r) == (date(1990, 1, 1), today, None)                 # concrete dates, never None
    s, e, r = cc.resolve_fetch_window(date(2026, 8, 1), date(2026, 9, 15), 40, today=today)
    assert e == today                                                    # forward buffer capped at today
    s, e, r = cc.resolve_fetch_window(date(2022, 1, 1), date(2022, 12, 31), 5, date(2020, 1, 1), None, today)
    assert s == date(2020, 1, 1) and r == "explicit --fetch-start=2020-01-01"
    with pytest.raises(cc.CliError, match="after --start"):
        cc.resolve_fetch_window(date(2022, 1, 1), None, 5, date(2023, 1, 1), None, today)
    with pytest.raises(cc.CliError, match="before --end"):
        cc.resolve_fetch_window(date(2022, 1, 1), date(2022, 12, 31), 5, None, date(2022, 6, 1), today)
    with pytest.raises(cc.CliError, match="empty"):
        cc.resolve_fetch_window(None, None, 5, date(2030, 1, 1), None, today)


def test_rolling_warmup_is_only_a_warning_not_a_fetch_lookback():
    assert CFG.backtest_rolling_warmup_calendar_days == 600
    assert not hasattr(CFG, "backtest_warmup_calendar_days")
    short = DF.iloc[1100:].reset_index(drop=True)                      # starts ~ 3 months before the window
    start = DATES[SIG_START_BAR].date()
    from tests.core.test_backtest_experiments import DictProvider
    res = run_experiment(DictProvider({"LONG": short}), CFG, ExperimentOptions(
        signal_start=start, signal_end=SIG_END, horizons=(1,)))
    assert any("less than 600 calendar days of history before signal_start" in w for w in res.warnings)
    assert res.warnings[-1] == ex.SURVIVORSHIP_WARNING
    full = run_experiment(DictProvider({"LONG": DF}), CFG, ExperimentOptions(
        signal_start=start, signal_end=SIG_END, horizons=(1,)))
    assert not any("calendar days of history" in w for w in full.warnings)
    from jusmo_scanner.config import override_config
    with pytest.raises(ValueError, match="rolling_warmup"):
        override_config(CFG, backtest_rolling_warmup_calendar_days=0)
