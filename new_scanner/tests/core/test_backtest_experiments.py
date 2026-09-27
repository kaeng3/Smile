from __future__ import annotations

import json
import math
import sqlite3
import subprocess
from collections import defaultdict
from contextlib import closing

import pandas as pd
import pytest

from jusmo_scanner.backtest import experiments as ex
from jusmo_scanner.backtest.analysis import (
    ALL_ANALYSES, INTERACTION_ANALYSES, PULLBACK_ANALYSES, SINGLE_ANALYSES)
from jusmo_scanner.backtest.buckets import MISSING
from jusmo_scanner.backtest.engine import SampleMode, backtest_ticker
from jusmo_scanner.backtest.experiments import ExperimentOptions, run_experiment
from jusmo_scanner.backtest.metrics import EntryMode, aggregate_group
from jusmo_scanner.config import load_config, override_config
from jusmo_scanner.data.base import DataProvider, PriceAdjustmentMode, ShareCountBasis
from jusmo_scanner.storage import sqlite_store as store
from tests import synthetic as syn

CFG = load_config("config/scanner.yaml")
FIRST, ALL = SampleMode.FIRST_SIGNAL_PER_EPISODE, SampleMode.ALL_SIGNALS


class DictProvider(DataProvider):
    def __init__(self, frames, adjustment=PriceAdjustmentMode.UNKNOWN, basis=ShareCountBasis.UNKNOWN):
        self.frames = frames
        self._adj, self._basis = adjustment, basis

    @property
    def price_adjustment_mode(self):
        return self._adj

    @property
    def share_count_basis(self):
        return self._basis

    def get_tickers(self):
        return list(self.frames)

    def get_ohlcv(self, ticker):
        return self.frames[ticker]


def fixtures():
    return {"SUCC": syn.success_frame(), "FAIL": syn.failure_frame(), "MULTI": syn.repeated_events_frame()}


def _rows(res, analysis, variant="baseline", mode=None, signal_type=None, horizon=None):
    return [r for r in res.summary_rows if r["analysis_name"] == analysis and r["variant"] == variant
            and (mode is None or r["sample_mode"] == mode.value)
            and (signal_type is None or r["signal_type"] == signal_type)
            and (horizon is None or r["horizon"] == horizon)]


def _query(db, sql, *args):
    with closing(sqlite3.connect(db)) as c:
        return c.execute(sql, args).fetchall()


# --- variants / baseline ----------------------------------------------------------------------

def test_only_requested_variants_are_run():
    p = DictProvider(fixtures())
    assert run_experiment(p, CFG, ExperimentOptions(horizons=(1,))).variants == ["baseline"]
    r = run_experiment(p, CFG, ExperimentOptions(horizons=(1,), sweeps=True, sweep_parameters=("vcr",)))
    assert r.variants == ["baseline"] + [f"vcr={x}" for x in (0.2, 0.25, 0.3, 0.35, 0.4, 0.5)]
    full = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(horizons=(1,), sweeps=True))
    assert len(full.variants) == 43


def test_variants_change_results_and_baseline_equals_plain_backtest():
    frames = fixtures()
    res = run_experiment(DictProvider(frames), CFG, ExperimentOptions(
        horizons=(1, 5), sweeps=True, sweep_parameters=("event_value",)))
    counts = res.signal_counts
    assert counts["event_value=100000000000"] < counts["baseline"]     # 100bn drops the 80bn / 60bn events
    assert counts["event_value=150000000000"] < counts["event_value=100000000000"] or counts[
        "event_value=150000000000"] == 0
    assert counts["event_value=30000000000"] >= counts["baseline"]
    assert counts["event_value=50000000000"] == counts["baseline"]     # the base value itself
    # baseline == a plain backtest_ticker run, mode by mode
    for mode in (FIRST, ALL):
        plain = defaultdict(list)
        for t, df in frames.items():
            for r in backtest_ticker(df, t, CFG, horizons=(1, 5), mode=mode).results:
                plain[(r.signal.signal_type.value, r.horizon)].append(r.forward)
        rows = {(r["signal_type"], r["horizon"]): r for r in _rows(res, "by_signal_type", mode=mode)}
        assert set(rows) == set(plain)
        for key, fr in plain.items():
            want = aggregate_group(fr)
            got = rows[key]
            assert got["sample_count"] == want.sample_count
            assert got["mean_return"] == pytest.approx(want.mean_return, abs=1e-15)
            assert got["median_mae"] == pytest.approx(want.median_mae, abs=1e-15)
            assert got["hit_up_10"] == pytest.approx(want.hit_up_10)
    assert not _rows(res, "by_signal_type", variant="vcr=0.2")          # only requested variants exist


def test_swept_variant_equals_plain_backtest_with_overridden_config():
    frames = fixtures()
    res = run_experiment(DictProvider(frames), CFG, ExperimentOptions(
        horizons=(3,), sweeps=True, sweep_parameters=("cost_tolerance",)))
    cfg_v = override_config(CFG, cost_hold_tolerance_pct=0.05)
    total = sum(len(backtest_ticker(df, t, cfg_v, horizons=(3,), mode=ALL).signals) for t, df in frames.items())
    assert res.signal_counts["cost_tolerance=5%"] == total
    assert CFG.cost_hold_tolerance_pct is None                            # base untouched


def test_first_vs_all_sample_counts_differ_on_repeated_event_fixture():
    res = run_experiment(DictProvider({"MULTI": syn.repeated_events_frame()}), CFG,
                         ExperimentOptions(horizons=(1,)))
    first = _rows(res, "by_signal_type", mode=FIRST, signal_type="EVENT", horizon=1)[0]
    allm = _rows(res, "by_signal_type", mode=ALL, signal_type="EVENT", horizon=1)[0]
    assert (first["sample_count"], allm["sample_count"]) == (1, 3)
    m_first = _rows(res, "by_signal_type", mode=FIRST, signal_type="MULTI_EVENT_CLUSTER", horizon=1)[0]
    m_all = _rows(res, "by_signal_type", mode=ALL, signal_type="MULTI_EVENT_CLUSTER", horizon=1)[0]
    assert (m_first["sample_count"], m_all["sample_count"]) == (1, 2)
    only_first = run_experiment(DictProvider({"MULTI": syn.repeated_events_frame()}), CFG,
                                ExperimentOptions(horizons=(1,), sample_modes=(FIRST,)))
    assert {r["sample_mode"] for r in only_first.summary_rows} == {"FIRST_SIGNAL_PER_EPISODE"}


# --- analyses ------------------------------------------------------------------------------------

def test_interaction_analyses_are_exactly_the_six():
    assert [a.name for a in INTERACTION_ANALYSES] == [
        "state_x_vcr", "state_x_cost_distance", "state_x_location120",
        "event_value_x_capital_impact", "pullback_depth_x_vcr", "structure_score_x_trigger_score"]
    assert [a.dims for a in INTERACTION_ANALYSES] == [
        ("state", "vcr_anchor"), ("state", "cost_distance"), ("state", "location120"),
        ("event_value", "event_capital_impact"), ("pullback_depth", "vcr_anchor"),
        ("structure_score", "trigger_score")]
    assert [a.name for a in PULLBACK_ANALYSES] == ["pullback_depth_x_volume_ratio"]
    assert all(len(a.dims) == 1 for a in SINGLE_ANALYSES) and len(ALL_ANALYSES) == len(
        {a.name for a in ALL_ANALYSES})
    for needed in ("by_event_value", "by_value_ratio", "by_turnover", "by_capital_impact", "by_location120",
                   "by_vcr_anchor", "by_range10", "by_cost_distance", "by_event_low_distance",
                   "by_event_age", "by_event_count", "by_cluster_value", "by_events_in_last_20d",
                   "by_structure_score", "by_trigger_score", "by_pullback_depth", "by_days_since_breakout",
                   "by_state", "by_transition", "by_signal_type", "by_accumulation_confirmed"):
        assert needed in {a.name for a in ALL_ANALYSES}


def test_analyses_never_drop_rows_and_missing_is_labelled():
    res = run_experiment(DictProvider(fixtures()), CFG, ExperimentOptions(horizons=(1, 5)))
    totals = {(r["sample_mode"], r["signal_type"], r["horizon"]): r["sample_count"]
              for r in _rows(res, "by_signal_type")}
    assert totals
    for a in ALL_ANALYSES:
        per = defaultdict(int)
        for r in _rows(res, a.name):
            per[(r["sample_mode"], r["signal_type"], r["horizon"])] += r["sample_count"]
        for key, n in per.items():
            assert n == totals[key], (a.name, key)       # every sample is in exactly one group
        if a.signal_types is None:
            assert set(per) == set(totals), a.name
        else:
            assert {k[1] for k in per} <= {t.value for t in a.signal_types}
    # signals without a breakout context have no pullback depth: labelled, not dropped
    miss = [r for r in _rows(res, "by_pullback_depth") if r["dim1"] == MISSING and r["signal_type"] == "EVENT"]
    assert miss and all(r["sample_count"] > 0 for r in miss)
    inter = _rows(res, "pullback_depth_x_vcr")
    assert inter and {r["signal_type"] for r in inter} == {"PULLBACK"}
    assert all(r["dim1_name"] == "pullback_depth" and r["dim2_name"] == "vcr_anchor" for r in inter)
    single = _rows(res, "by_state")[0]
    assert single["dim2_name"] == "" and single["dim2"] == ""


def test_pullback_specific_analysis_present():
    res = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(horizons=(1,)))
    rows = _rows(res, "pullback_depth_x_volume_ratio", mode=ALL)
    assert rows and rows[0]["dim1_name"] == "pullback_depth" and rows[0]["dim2_name"] == "pullback_volume_ratio"
    assert "-8~-5%" in {r["dim1"] for r in rows}                          # the fixture's ~-7.1% pullback
    assert any(r["analysis_name"] == "by_days_since_breakout" for r in res.summary_rows)


def test_identical_sample_rows_carry_a_note():
    res = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(horizons=(1,)))
    ev = _rows(res, "by_signal_type", mode=FIRST, signal_type="EVENT")[0]
    assert "IDENTICAL_SAMPLES" in ev["note"] and "ACCUMULATION" in ev["note"] and "EVENT_TO_ACCUMULATION" in ev["note"]
    acc = _rows(res, "by_signal_type", mode=FIRST, signal_type="ACCUMULATION")[0]
    assert "EVENT_BASELINE (unconfirmed" in acc["note"]
    brk = _rows(res, "by_signal_type", mode=FIRST, signal_type="BREAKOUT")[0]
    assert "EVENT_BASELINE" not in (brk["note"] or "")


def test_sweep_variants_run_only_the_signal_type_analysis():
    res = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(
        horizons=(1,), sweeps=True, sweep_parameters=("vcr",)))
    assert {r["analysis_name"] for r in res.summary_rows if r["variant"] == "vcr=0.3"} == {"by_signal_type"}
    assert {r["analysis_name"] for r in res.summary_rows if r["variant"] == "baseline"} == {
        a.name for a in ALL_ANALYSES if a.name != "pullback_depth_x_vcr" or True} - set()
    only = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(
        horizons=(1,), analyses=("by_state", "state_x_vcr")))
    assert {r["analysis_name"] for r in only.summary_rows} == {"by_state", "state_x_vcr"}


# --- NaN / empty -------------------------------------------------------------------------------

def _no_nan(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            _no_nan(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _no_nan(v)
    elif isinstance(obj, float):
        assert math.isfinite(obj), obj


def test_backtest_does_not_create_nan_summary(tmp_path):
    frames = {**fixtures(), "R1": syn.random_frame(1, 320), "R2": syn.random_frame(2, 320)}
    db = tmp_path / "n.db"
    res = run_experiment(DictProvider(frames), CFG, ExperimentOptions(
        horizons=(1, 40), sweeps=True, sweep_parameters=("vcr", "event_low_atr"), db_path=db))
    assert res.summary_rows
    _no_nan(res.summary_rows)
    for r in res.summary_rows:
        json.dumps(r, allow_nan=False)
        if r["sample_count"] < 2:
            assert r["std_return"] is None        # missing -> None, not NaN / 0
    with closing(sqlite3.connect(db)) as c:
        cols = [x[1] for x in c.execute("PRAGMA table_info(backtest_summary)")]
        for col in cols:
            assert c.execute(f"SELECT COUNT(*) FROM backtest_summary WHERE {col} != {col}").fetchone()[0] == 0
            assert c.execute(f"SELECT COUNT(*) FROM backtest_summary WHERE typeof({col}) = 'blob'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM backtest_summary WHERE std_return IS NULL AND sample_count >= 2"
                         ).fetchone()[0] == 0


def test_empty_signal_set_is_handled(tmp_path):
    quiet = syn.to_frame([syn._bar(1000.0 + (i % 5), volume=100_000.0) for i in range(300)], ticker="QUIET")
    db = tmp_path / "e.db"
    res = run_experiment(DictProvider({"QUIET": quiet}), CFG, ExperimentOptions(
        sweeps=True, sweep_parameters=("vcr",), db_path=db))
    assert res.summary_rows == [] and res.tickers_scanned == 1 and res.failed_tickers == {}
    assert all(n == 0 for n in res.signal_counts.values())
    assert _query(db, "SELECT status, tickers_scanned FROM backtest_experiments") == [("COMPLETE", 1)]
    for t in ("backtest_signals", "backtest_results", "backtest_summary"):
        assert _query(db, f"SELECT COUNT(*) FROM {t}") == [(0,)]
    # a signal-type filter that matches nothing is equally fine
    r2 = run_experiment(DictProvider(fixtures()), CFG, ExperimentOptions(signal_types={"TREND_BREAK"}, horizons=(1,)))
    assert all(r["signal_type"] == "TREND_BREAK" for r in r2.summary_rows)


# --- end to end / storage -------------------------------------------------------------------------

def test_experiment_end_to_end_into_sqlite(tmp_path):
    db = tmp_path / "x.db"
    frames = {**fixtures(), "R1": syn.random_frame(1, 320)}
    res = run_experiment(DictProvider(frames), CFG, ExperimentOptions(horizons=(1, 5, 20), db_path=db))
    (row,) = _query(db, "SELECT experiment_id, status, config_hash, universe_size, tickers_scanned, tickers_failed,"
                        " sample_modes, entry_mode, price_adjustment_mode, share_count_basis, horizons,"
                        " min_sample_size, schema_version, source_data_start, source_data_end, config_json, options_json,"
                        " warnings_json FROM backtest_experiments")
    assert row[0] == res.experiment_id and row[1] == "COMPLETE" and row[2] == ex.config_hash(CFG)
    assert row[3:6] == (4, 4, 0) and row[6] == "FIRST_SIGNAL_PER_EPISODE,ALL_SIGNALS"
    assert row[7:10] == ("NEXT_OPEN", "UNKNOWN", "UNKNOWN") and json.loads(row[10]) == [1, 5, 20]
    assert row[11:13] == (100, store.SCHEMA_VERSION) and row[13] < row[14]
    assert json.loads(row[15])["core_event_trading_value"] == 50_000_000_000
    assert json.loads(row[16])["entry_mode"] == "NEXT_OPEN"
    warns = json.loads(row[17])
    assert ex.UNKNOWN_ADJUSTMENT_WARNING in warns and warns[-1] == (
        "Survivorship bias may exist because historical delisted securities are not included.")
    assert res.warnings == warns
    n_sig = res.signal_counts["baseline"]
    assert _query(db, "SELECT COUNT(*) FROM backtest_signals") == [(n_sig,)]
    n_res = _query(db, "SELECT COUNT(*) FROM backtest_results")[0][0]
    assert 0 < n_res <= n_sig * 3
    assert _query(db, "SELECT COUNT(*) FROM backtest_summary") == [(len(res.summary_rows),)]
    assert _query(db, "SELECT COUNT(DISTINCT signal_uid) FROM backtest_signals") == [(n_sig,)]
    # every result row references an existing signal row; first samples are flagged, not duplicated
    assert _query(db, "SELECT COUNT(*) FROM backtest_results r LEFT JOIN backtest_signals s ON "
                      "s.experiment_id=r.experiment_id AND s.variant=r.variant AND s.signal_uid=r.signal_uid "
                      "WHERE s.id IS NULL") == [(0,)]
    n_first = _query(db, "SELECT COUNT(*) FROM backtest_signals WHERE is_first_sample=1")[0][0]
    assert 0 < n_first < n_sig
    assert _query(db, "SELECT COUNT(*) FROM backtest_signals WHERE is_first_sample=0 AND "
                      "days_since_previous_same_sample IS NOT NULL") == [(0,)]
    # result rows match the plain backtest (ALL basis), horizon by horizon
    plain = sum(len(backtest_ticker(df, t, CFG, horizons=(1, 5, 20), mode=ALL).results) for t, df in frames.items())
    assert n_res == plain


def test_rerun_of_same_experiment_id_is_idempotent(tmp_path):
    db = tmp_path / "i.db"
    opts = ExperimentOptions(horizons=(1, 5), db_path=db, experiment_id="fixed-id")
    run_experiment(DictProvider(fixtures()), CFG, opts)
    counts = [_query(db, f"SELECT COUNT(*) FROM {t}")[0][0] for t in (
        "backtest_experiments", "backtest_signals", "backtest_results", "backtest_summary")]
    run_experiment(DictProvider(fixtures()), CFG, opts)
    assert counts == [_query(db, f"SELECT COUNT(*) FROM {t}")[0][0] for t in (
        "backtest_experiments", "backtest_signals", "backtest_results", "backtest_summary")]
    assert counts[0] == 1 and all(c > 0 for c in counts)


def test_one_sqlite_connection_per_run(tmp_path, monkeypatch):
    opened = []
    real = sqlite3.connect

    def spy(*a, **k):
        opened.append(a)
        return real(*a, **k)

    monkeypatch.setattr(store.sqlite3, "connect", spy)
    run_experiment(DictProvider({**fixtures(), "R1": syn.random_frame(1, 320)}), CFG, ExperimentOptions(
        horizons=(1, 5), db_path=tmp_path / "c.db", sweeps=True, sweep_parameters=("vcr",), store_variant_rows=True))
    assert len(opened) == 2      # init_db + ONE job connection, not one per ticker/signal/variant


def test_variant_rows_are_stored_only_on_request(tmp_path):
    frames = {"SUCC": syn.success_frame()}
    base = dict(horizons=(1,), sweeps=True, sweep_parameters=("vcr",))
    db1, db2 = tmp_path / "a.db", tmp_path / "b.db"
    run_experiment(DictProvider(frames), CFG, ExperimentOptions(db_path=db1, **base))
    run_experiment(DictProvider(frames), CFG, ExperimentOptions(db_path=db2, store_variant_rows=True, **base))
    assert _query(db1, "SELECT DISTINCT variant FROM backtest_signals") == [("baseline",)]
    # vcr=0.4 equals the base config: not re-scanned, flagged, no duplicate rows
    assert len(_query(db2, "SELECT DISTINCT variant FROM backtest_signals")) == 6
    assert _query(db1, "SELECT COUNT(DISTINCT variant) FROM backtest_summary") == [(7,)]


# --- metadata --------------------------------------------------------------------------------------

def test_experiment_records_config_hash(tmp_path):
    p = DictProvider({"SUCC": syn.success_frame()})
    a = run_experiment(p, CFG, ExperimentOptions(horizons=(1,)))
    b = run_experiment(p, CFG, ExperimentOptions(horizons=(1,)))
    assert a.metadata["config_hash"] == b.metadata["config_hash"] == ex.config_hash(CFG)   # stable across runs
    assert a.experiment_id != b.experiment_id
    same = load_config("config/scanner.yaml")
    assert same is not CFG and ex.config_hash(same) == ex.config_hash(CFG)               # equal configs
    changed = override_config(CFG, dormant_vcr_max=0.41)
    assert ex.config_hash(changed) != ex.config_hash(CFG)
    assert run_experiment(p, changed, ExperimentOptions(horizons=(1,))).metadata["config_hash"] == ex.config_hash(changed)
    # nested dataclass fields are part of the hash
    import dataclasses
    nested = dataclasses.replace(CFG, structure_scoring=dataclasses.replace(
        CFG.structure_scoring, low_hold_points=CFG.structure_scoring.low_hold_points + 1))
    assert ex.config_hash(nested) != ex.config_hash(CFG)
    js = json.loads(ex.config_to_json(CFG))
    assert list(js) == sorted(js) and js["structure_scoring"]["vcr"]["strong_threshold"] == 0.25
    assert len(a.metadata["config_hash"]) == 64


def test_experiment_records_git_commit_when_available(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw.get("cwd")))
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="deadbeef1234\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=" M file.py\n", stderr="")

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    res = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(horizons=(1,)))
    assert res.metadata["git_commit"] == "deadbeef1234" and res.metadata["git_dirty"] is True
    assert calls and all(str(c[1]).endswith("backtest") for c in calls)     # cwd = the package dir


@pytest.mark.parametrize("failure", ["missing", "not_a_repo", "timeout", "empty"])
def test_experiment_records_git_commit_none_when_unavailable(monkeypatch, failure):
    def fake_run(cmd, **kw):
        if failure == "missing":
            raise FileNotFoundError("git")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd, 10)
        if failure == "empty":
            return subprocess.CompletedProcess(cmd, 0, stdout="\n", stderr="")
        return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: not a git repository")

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    assert ex.git_info() == (None, None)
    res = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(horizons=(1,)))
    assert res.metadata["git_commit"] is None and res.metadata["git_dirty"] is None


def test_git_dirty_failure_keeps_commit(monkeypatch):
    def fake_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc\n", stderr="")
        raise OSError("no status")

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    assert ex.git_info() == ("abc", None)


def test_warnings_for_provider_metadata_and_entry_mode():
    frames = {"SUCC": syn.success_frame()}
    unknown = run_experiment(DictProvider(frames), CFG, ExperimentOptions(horizons=(1,)))
    assert unknown.warnings == [ex.UNKNOWN_ADJUSTMENT_WARNING, ex.SURVIVORSHIP_WARNING]
    assert ex.UNKNOWN_ADJUSTMENT_WARNING == "price adjustment unknown: splits/mergers may distort returns"
    assert ex.SURVIVORSHIP_WARNING == "Survivorship bias may exist because historical delisted securities are not included."
    pykrx_like = run_experiment(
        DictProvider(frames, PriceAdjustmentMode.ADJUSTED, ShareCountBasis.OUTSTANDING), CFG,
        ExperimentOptions(horizons=(1,)))
    assert pykrx_like.warnings == [ex.ADJUSTED_NOT_RESTATED_WARNING, "turnover uses shares outstanding, not free float",
                                  ex.SURVIVORSHIP_WARNING]
    assert pykrx_like.metadata["price_adjustment_mode"] == "ADJUSTED"
    assert pykrx_like.metadata["share_count_basis"] == "OUTSTANDING"
    clean = run_experiment(DictProvider(frames, PriceAdjustmentMode.ADJUSTED, ShareCountBasis.FREE_FLOAT), CFG,
                           ExperimentOptions(horizons=(1,)))
    assert clean.warnings == [ex.ADJUSTED_NOT_RESTATED_WARNING, ex.SURVIVORSHIP_WARNING]
    assert ex.ADJUSTED_NOT_RESTATED_WARNING == "volume/trading value/share counts are not restated for corporate actions"
    close = run_experiment(DictProvider(frames), CFG, ExperimentOptions(horizons=(1,), entry_mode=EntryMode.CLOSE))
    assert any(w.startswith("optimistic assumption") for w in close.warnings)
    assert close.metadata["entry_mode"] == "CLOSE"
    assert all("optimistic assumption (CLOSE entry)" in r["note"] for r in close.summary_rows)
    assert all("optimistic" not in (r["note"] or "") for r in unknown.summary_rows)
    raw = run_experiment(DictProvider(frames, PriceAdjustmentMode.RAW, ShareCountBasis.FREE_FLOAT), CFG,
                         ExperimentOptions(horizons=(1,)))
    assert ex.RAW_ADJUSTMENT_WARNING in raw.warnings
    # experiment wording never claims an optimum
    text = json.dumps([unknown.warnings, [r['note'] for r in unknown.summary_rows]]).lower()
    assert "best" not in text and "optimal" not in text


# --- failure isolation ---------------------------------------------------------------------------------

def test_ticker_failures_are_isolated_and_counted(tmp_path):
    bad = syn.success_frame()
    bad.loc[10, "date"] = bad.loc[9, "date"]            # duplicate date -> ValueError in prepare_ticker
    frames = {"BAD": bad, "EMPTY": pd.DataFrame(), "SUCC": syn.success_frame()}
    db = tmp_path / "f.db"
    res = run_experiment(DictProvider(frames), CFG, ExperimentOptions(horizons=(1,), db_path=db))
    assert res.tickers_scanned == 1 and set(res.failed_tickers) == {"BAD", "EMPTY"}
    assert "duplicate dates" in res.failed_tickers["BAD"] and "no data" in res.failed_tickers["EMPTY"]
    assert res.metadata["tickers_failed"] == 1 + 1 and res.metadata["universe_size"] == 3
    assert _query(db, "SELECT tickers_scanned, tickers_failed, status FROM backtest_experiments") == [(1, 2, "COMPLETE")]
    assert set(json.loads(_query(db, "SELECT failed_tickers_json FROM backtest_experiments")[0][0])) == {"BAD", "EMPTY"}
    assert res.summary_rows


def test_experiment_fails_only_if_no_ticker_succeeded(tmp_path):
    bad = syn.success_frame()
    bad.loc[10, "date"] = bad.loc[9, "date"]
    db = tmp_path / "g.db"
    with pytest.raises(RuntimeError, match="no ticker could be backtested"):
        run_experiment(DictProvider({"BAD": bad}), CFG, ExperimentOptions(db_path=db, experiment_id="dead"))
    assert _query(db, "SELECT status, tickers_scanned, tickers_failed FROM backtest_experiments") == [("FAILED", 0, 1)]
    with pytest.raises(ValueError, match="empty universe"):
        run_experiment(DictProvider({}), CFG, ExperimentOptions())


def test_provider_error_is_isolated():
    class Flaky(DictProvider):
        def get_ohlcv(self, ticker):
            if ticker == "SUCC":
                raise OSError("network")
            return super().get_ohlcv(ticker)

    res = run_experiment(Flaky(fixtures()), CFG, ExperimentOptions(horizons=(1,)))
    assert res.tickers_scanned == 2 and "OSError" in res.failed_tickers["SUCC"]


# --- options -----------------------------------------------------------------------------------------------

def test_option_validation():
    for bad in ((), (0,), (1.5,), ("x",)):
        with pytest.raises(ValueError, match="horizons"):
            ExperimentOptions(horizons=bad)
    with pytest.raises(ValueError, match="start"):
        ExperimentOptions(signal_start="2021-01-02", signal_end="2021-01-01")
    with pytest.raises(ValueError, match="sample_modes"):
        ExperimentOptions(sample_modes=())
    with pytest.raises(ValueError, match="unknown analysis"):
        ExperimentOptions(analyses=("nope",))
    with pytest.raises(ValueError, match="min_sample_size"):
        ExperimentOptions(min_sample_size=0)
    with pytest.raises(KeyError):
        ExperimentOptions(signal_types={"NOT_A_SIGNAL"})
    o = ExperimentOptions(horizons=(5, 1, 5), signal_types=["BREAKOUT"], entry_mode="CLOSE",
                          sample_modes=("ALL_SIGNALS",))
    assert o.horizons == (1, 5) and o.entry_mode is EntryMode.CLOSE and o.sample_modes == (ALL,)
    # validated before any scanning: an invalid explicit horizons fails immediately
    with pytest.raises(ValueError):
        run_experiment(DictProvider(fixtures()), CFG, ExperimentOptions(horizons=(0,)))


def test_cartesian_is_off_by_default_and_guarded():
    p = DictProvider({"SUCC": syn.success_frame()})
    assert run_experiment(p, CFG, ExperimentOptions(horizons=(1,))).variants == ["baseline"]
    with pytest.raises(ValueError, match="max_combos"):
        run_experiment(p, CFG, ExperimentOptions(horizons=(1,), cartesian=True, max_combos=10))
    res = run_experiment(p, CFG, ExperimentOptions(
        horizons=(1,), cartesian=True, cartesian_parameters=("vcr", "range10"), max_combos=30))
    assert len(res.variants) == 1 + 30
    assert res.variants[1] == "vcr=0.2|range10=0.08"


def test_min_sample_size_flag_marks_but_never_hides():
    res = run_experiment(DictProvider(fixtures()), CFG, ExperimentOptions(horizons=(1,), min_sample_size=2))
    rows = _rows(res, "by_signal_type", mode=ALL)
    assert any(r["low_sample"] for r in rows) and any(not r["low_sample"] for r in rows)
    assert all(r["low_sample"] == (r["sample_count"] < 2) for r in rows)
    assert all(r["mean_return"] is not None for r in rows)
    assert res.metadata["min_sample_size"] == 2
    default = run_experiment(DictProvider(fixtures()), CFG, ExperimentOptions(horizons=(1,)))
    assert res.metadata["min_sample_size"] != default.metadata["min_sample_size"] == 100
    assert all(r["low_sample"] for r in default.summary_rows)          # fixtures are tiny


def test_close_entry_mode_uses_signal_close():
    nxt = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(horizons=(1,), sample_modes=(ALL,)))
    close = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(
        horizons=(1,), sample_modes=(ALL,), entry_mode=EntryMode.CLOSE))
    a = _rows(nxt, "by_signal_type", signal_type="BREAKOUT")[0]
    b = _rows(close, "by_signal_type", signal_type="BREAKOUT")[0]
    assert a["entry_mode"] == "NEXT_OPEN" and b["entry_mode"] == "CLOSE" and a["mean_return"] != b["mean_return"]


# --- purity / causality ----------------------------------------------------------------------------------------

def test_per_ticker_function_is_pure_and_deterministic():
    df = syn.repeated_events_frame()
    before = df.copy()
    variants = [("baseline", CFG), ("vcr=0.2", override_config(CFG, dormant_vcr_max=0.2))]
    opts = ExperimentOptions(horizons=(1, 5))
    a = ex.run_ticker_experiment(df, "M", variants, opts, (1, 5))
    b = ex.run_ticker_experiment(df, "M", variants, opts, (1, 5))
    pd.testing.assert_frame_equal(df, before)
    assert a == b and set(a.outcomes) == {"baseline", "vcr=0.2"}
    assert CFG.dormant_vcr_max == 0.40


def _signal_table(db, variant):
    with closing(sqlite3.connect(db)) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(backtest_signals)")
                if r[1] not in ("id", "experiment_id")]
        rows = c.execute(f"SELECT {', '.join(cols)} FROM backtest_signals WHERE variant = ? "
                         "ORDER BY signal_uid", (variant,)).fetchall()
    return cols, rows


def test_truncated_data_experiment_signals_equal_full_data_signals(tmp_path):
    """Experiment-level look-ahead regression: removing every bar after `cut` from the raw
    frames (i.e. the scanner never sees them) must not change any stored signal (all
    snapshot fields, first-sample flags, overlap columns) on or before that bar - for the
    baseline AND swept variants."""
    cases = [("SUCC", syn.success_frame(), (272, 280, 289, 293)),
             ("MULTI", syn.repeated_events_frame(), (84, 90, 105)),
             ("R3", syn.random_frame(3, 320), (150, 260))]
    checked = 0
    for name, df, cuts in cases:
        opts = dict(horizons=(1, 5), sweeps=True, sweep_parameters=("event_value", "cost_tolerance", "vcr"),
                    store_variant_rows=True)
        full_db = tmp_path / f"{name}_full.db"
        run_experiment(DictProvider({name: df}), CFG, ExperimentOptions(db_path=full_db, **opts))
        for cut in cuts:
            cut_db = tmp_path / f"{name}_{cut}.db"
            run_experiment(DictProvider({name: df.iloc[:cut + 1].reset_index(drop=True)}), CFG,
                           ExperimentOptions(db_path=cut_db, **opts))
            for variant in [v.id for v in ex.parameter_grid.ofat_variants(("event_value", "cost_tolerance", "vcr"))]:
                cols, cut_rows = _signal_table(cut_db, variant)
                _, full_rows = _signal_table(full_db, variant)
                i = cols.index("bar_index")
                want = [r for r in full_rows if r[i] <= cut]
                assert cut_rows == want, (name, cut, variant)
                checked += len(want)
    assert checked > 500


def test_swept_variant_truncation_actually_exercises_signals():
    # guard against a vacuous look-ahead test: the swept variant must produce signals up to the cut
    df = syn.success_frame()
    res = run_experiment(DictProvider({"SUCC": df.iloc[:290].reset_index(drop=True)}), CFG, ExperimentOptions(
        horizons=(1,), sweeps=True, sweep_parameters=("event_value",)))
    assert res.signal_counts["event_value=30000000000"] > 0 and res.signal_counts["event_value=100000000000"] == 0


# --- accumulator internals / atomicity ---------------------------------------------------------------------

def test_merge_equals_single_accumulator_and_fingerprint_matches_exact_identity_groups():
    from jusmo_scanner.backtest.analysis import SummaryAccumulator, select_analyses
    from jusmo_scanner.backtest.signals import identical_sample_groups
    frames = fixtures()
    analyses = select_analyses(["by_signal_type", "by_state", "state_x_vcr"])
    single = SummaryAccumulator(analyses, EntryMode.NEXT_OPEN, (FIRST, ALL))
    merged = SummaryAccumulator(analyses, EntryMode.NEXT_OPEN, (FIRST, ALL))
    opts = ExperimentOptions(horizons=(1, 5))
    for t, df in frames.items():
        local = merged.empty_like()
        for vid, outs in ex.iter_ticker_variants(df, t, [("baseline", CFG)], opts, (1, 5)):
            for o in outs:
                single.add(vid, o.signal, o.is_first, o.results)
                local.add(vid, o.signal, o.is_first, o.results)
        merged.merge(local)
    assert single.finalize() == merged.finalize() and len(single) == len(merged) > 0
    for mode, sm in (("FIRST_SIGNAL_PER_EPISODE", FIRST), ("ALL_SIGNALS", ALL)):
        exact = []
        for t, df in frames.items():
            exact += backtest_ticker(df, t, CFG, horizons=(1, 5), mode=sm).signals
        assert merged.identical_groups("baseline", mode) == identical_sample_groups(exact)
    assert merged.identical_groups("baseline", "FIRST_SIGNAL_PER_EPISODE")      # the hazard is detected


def test_ticker_is_all_or_nothing_when_a_later_variant_fails(tmp_path, monkeypatch):
    real = ex.scan_signals

    def flaky(prepared, ticker, cfg, max_h):
        if ticker == "MULTI" and cfg.dormant_vcr_max == 0.2:
            raise RuntimeError("variant blew up")
        return real(prepared, ticker, cfg, max_h)

    monkeypatch.setattr(ex, "scan_signals", flaky)
    db = tmp_path / "a.db"
    res = run_experiment(DictProvider(fixtures()), CFG, ExperimentOptions(
        horizons=(1,), sweeps=True, sweep_parameters=("vcr",), db_path=db, store_variant_rows=True))
    assert set(res.failed_tickers) == {"MULTI"} and "variant blew up" in res.failed_tickers["MULTI"]
    assert res.tickers_scanned == 2
    tickers = {t for (t,) in _query(db, "SELECT DISTINCT ticker FROM backtest_signals")}
    assert tickers == {"SUCC", "FAIL"} or tickers == {"SUCC"}        # no partial MULTI rows
    assert not any(k.startswith("MULTI") for (k,) in _query(db, "SELECT DISTINCT episode_id FROM backtest_signals"))
    plain = run_experiment(DictProvider({k: v for k, v in fixtures().items() if k != "MULTI"}), CFG, ExperimentOptions(
        horizons=(1,), sweeps=True, sweep_parameters=("vcr",)))
    assert res.summary_rows == plain.summary_rows                      # and none in the summaries


# --- commit-2 review follow-ups -----------------------------------------------------------------------------------

def test_config_hash_is_independent_of_int_vs_float_spelling():
    assert CFG.strong_event_value_ratio_min == 2.0
    as_int = override_config(CFG, strong_event_value_ratio_min=2)
    assert isinstance(as_int.strong_event_value_ratio_min, int)
    assert ex.config_hash(as_int) == ex.config_hash(CFG) and ex.config_to_json(as_int) == ex.config_to_json(CFG)
    assert ex.config_hash(override_config(CFG, strong_event_value_ratio_min=2.5)) != ex.config_hash(CFG)
    js = json.loads(ex.config_to_json(CFG))
    assert js["breakout_swing_window"] == 5 and js["dormant_vcr_max"] == 0.4 and js["cost_hold_tolerance_pct"] is None
    assert js["trigger_scoring"]["use_state_bonus"] is False       # bools stay bools
    a = run_experiment(DictProvider({"SUCC": syn.success_frame()}), as_int, ExperimentOptions(horizons=(1,)))
    assert a.metadata["config_hash"] == ex.config_hash(CFG)


def test_variant_equal_to_baseline_is_flagged_not_rescanned(tmp_path, monkeypatch):
    calls = []
    real = ex.scan_signals

    def counting(prepared, ticker, cfg, max_h):
        calls.append(cfg.dormant_vcr_max)
        return real(prepared, ticker, cfg, max_h)

    monkeypatch.setattr(ex, "scan_signals", counting)
    db = tmp_path / "eq.db"
    res = run_experiment(DictProvider(fixtures()), CFG, ExperimentOptions(
        horizons=(1, 5), sweeps=True, sweep_parameters=("vcr",), db_path=db, store_variant_rows=True))
    assert len(calls) == 3 * 6 and calls.count(0.4) == 3           # per ticker: baseline + 5 variants (vcr=0.4 skipped)
    assert res.variants[0] == "baseline" and "vcr=0.4" in res.variants
    eq = [r for r in res.summary_rows if r["variant"] == "vcr=0.4"]
    base = {(r["sample_mode"], r["signal_type"], r["horizon"]): r
            for r in res.summary_rows if r["variant"] == "baseline" and r["analysis_name"] == "by_signal_type"}
    assert eq and all(r["variant_equals_baseline"] is True and "same config as baseline" in r["note"] for r in eq)
    for r in eq:
        b = base[(r["sample_mode"], r["signal_type"], r["horizon"])]
        assert (r["sample_count"], r["mean_return"], r["median_mae"]) == (b["sample_count"], b["mean_return"], b["median_mae"])
    assert all(r["variant_equals_baseline"] is False for r in res.summary_rows if r["variant"] != "vcr=0.4")
    assert res.signal_counts["vcr=0.4"] == res.signal_counts["baseline"]
    assert _query(db, "SELECT COUNT(*) FROM backtest_summary WHERE variant='vcr=0.4' AND variant_equals_baseline=1")[0][0] == len(eq)
    variants = json.loads(_query(db, "SELECT variants_json FROM backtest_experiments")[0][0])
    assert {v["id"]: v["equals_baseline"] for v in variants}["vcr=0.4"] is True
    assert sum(v["equals_baseline"] for v in variants) == 1


def test_signal_types_on_bar_and_results_carry_signal_type(tmp_path):
    db = tmp_path / "s.db"
    run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(
        horizons=(1,), db_path=db, sample_modes=(ALL,)))
    rows = _query(db, "SELECT ticker, bar_index, signal_type, signal_types_on_bar FROM backtest_signals")
    per_bar = defaultdict(set)
    for t, bar, st, _ in rows:
        per_bar[(t, bar)].add(st)
    assert all(n == len(per_bar[(t, bar)]) for t, bar, _, n in rows)
    assert max(n for *_, n in rows) >= 3                    # several types fire on the event bar
    res_rows = _query(db, "SELECT signal_type, signal_semantics FROM backtest_results")
    assert res_rows and all(st and sem for st, sem in res_rows)
    assert any(sem.startswith("EVENT_BASELINE") for st, sem in res_rows if st == "ACCUMULATION")
    joined = _query(db, "SELECT COUNT(*) FROM backtest_results r JOIN backtest_signals s USING (experiment_id, variant, signal_uid)"
                        " WHERE r.signal_type != s.signal_type")
    assert joined == [(0,)]


def test_overlapping_samples_note_is_informational():
    res = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(horizons=(1,)))
    ev = _rows(res, "by_signal_type", mode=FIRST, signal_type="EVENT")[0]
    assert "OVERLAPPING_SAMPLES(100%)" in ev["note"]        # the event bar carries other signal types too
    assert all(r["mean_return"] is not None for r in res.summary_rows if "OVERLAPPING" in (r["note"] or ""))


def test_variants_must_share_breakout_swing_window():
    with pytest.raises(ValueError, match="breakout_swing_window"):
        list(ex.iter_ticker_variants(
            syn.success_frame(), "S", [("baseline", CFG), ("w6", override_config(CFG, breakout_swing_window=6))],
            ExperimentOptions(horizons=(1,)), (1,)))
    with pytest.raises(ValueError, match="breakout_swing_window"):
        ex.run_ticker_experiment(syn.success_frame(), "S",
                                 [("a", CFG), ("b", override_config(CFG, breakout_swing_window=7))],
                                 ExperimentOptions(horizons=(1,)), (1,))


def test_git_commit_env_fallback(monkeypatch):
    def no_git(cmd, **kw):
        raise FileNotFoundError("git")

    monkeypatch.setattr(ex.subprocess, "run", no_git)
    monkeypatch.setenv("JUSMO_GIT_COMMIT", " cafe1234 ")
    assert ex.git_info() == ("cafe1234", None)
    res = run_experiment(DictProvider({"SUCC": syn.success_frame()}), CFG, ExperimentOptions(horizons=(1,)))
    assert res.metadata["git_commit"] == "cafe1234" and res.metadata["git_dirty"] is None
    monkeypatch.setenv("JUSMO_GIT_COMMIT", "")
    assert ex.git_info() == (None, None)
    monkeypatch.delenv("JUSMO_GIT_COMMIT")
    assert ex.git_info() == (None, None)

    def repo(cmd, **kw):     # a working git wins over the env var
        return subprocess.CompletedProcess(cmd, 0, stdout="abc\n", stderr="")

    monkeypatch.setattr(ex.subprocess, "run", repo)
    monkeypatch.setenv("JUSMO_GIT_COMMIT", "zzz")
    assert ex.git_info()[0] == "abc"
